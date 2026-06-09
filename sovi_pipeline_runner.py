"""
sovi_pipeline_runner.py
=======================
SOVI Prediction Post-Processing Pipeline
-----------------------------------------
Executes all 8 SQL steps sequentially after the SOVI image-analysis pipeline
completes.  Call ``run_sovi_pipeline(db_config, iteration_id)`` from main.py
immediately after run_cap_pipeline().

Steps
-----
1.  Create unique index on temp.cap_prediction_temp_sovi
2.  Insert CAP predictions from SKU table (sovi)
3.  Vertical match  – assign prod_class_id by horizontal overlap
4.  Nearest-match fallback – centroid distance for remaining NULLs
5.  Remove small caps inside SKU bounding box (< 15 % area)
6.  Remove duplicate rows
7.  Populate orgi.coolermetricsmaster_sovi
8.  Populate orgi.coolermetricstransaction_sovi
"""

from __future__ import annotations

import logging
import time
import traceback
from dataclasses import dataclass, field
from typing import Optional

import psycopg2

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class StepResult:
    step: int
    name: str
    status: str                   # "success" | "failed" | "skipped"
    rows_affected: Optional[int]
    duration_ms: float
    error: Optional[str] = None

    def __str__(self) -> str:
        rows = f"{self.rows_affected} rows" if self.rows_affected is not None else "n/a"
        return (
            f"  Step {self.step:>2}  [{self.status.upper():<7}]  "
            f"{self.name:<55}  {rows:<12}  {self.duration_ms:>8.1f} ms"
        )


@dataclass
class PipelineResult:
    iteration_id: int
    overall_status: str           # "success" | "failed"
    total_duration_ms: float
    steps: list[StepResult] = field(default_factory=list)

    def log_summary(self) -> None:
        sep = "=" * 100
        logger.info(sep)
        logger.info("  SOVI PREDICTION PIPELINE  –  SUMMARY")
        logger.info(sep)
        logger.info(f"  Iteration ID   : {self.iteration_id}")
        logger.info(f"  Overall status : {self.overall_status.upper()}")
        logger.info(f"  Total duration : {self.total_duration_ms:.1f} ms")
        logger.info("-" * 100)
        logger.info(
            f"  {'Step':>4}  {'Status':<9}  {'Name':<55}  {'Rows':<12}  {'Duration':>10}"
        )
        logger.info("-" * 100)
        for s in self.steps:
            logger.info(str(s))
        logger.info(sep)

        failed = [s for s in self.steps if s.status == "failed"]
        if failed:
            logger.error(f"  {len(failed)} step(s) failed:")
            for s in failed:
                logger.error(f"    Step {s.step} – {s.name}")
                if s.error:
                    first_line = s.error.strip().splitlines()[-1]
                    logger.error(f"      {first_line}")
            logger.info(sep)


# ── SQL definitions ────────────────────────────────────────────────────────────
def _build_queries(iteration_id: int) -> list[dict]:
    """Return all SOVI pipeline SQL statements in execution order."""
    iid = int(iteration_id)          # guard against injection
    return [
        # ── 1 ─────────────────────────────────────────────────────────────────
        {
            "step": 1,
            "name": "Create unique index on cap_prediction_temp_sovi",
            "sql": """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_cap_box_sovi
                ON temp.cap_prediction_temp_sovi (
                    store_id,
                    image_file_name,
                    s3path_annotated_file,
                    iteration_id,
                    cap_class_id,
                    x1,
                    y1,
                    x2,
                    y2
                );
            """,
        },
        # ── 2 ─────────────────────────────────────────────────────────────────
        {
            "step": 2,
            "name": "Insert CAP predictions from SKU table (sovi)",
            "sql": """
                INSERT INTO temp.cap_prediction_temp_sovi (
                    store_id,
                    image_file_name,
                    s3path_annotated_file,
                    iteration_id,
                    cap_class_id,
                    prod_class_id,
                    x1,
                    x2,
                    y1,
                    y2,
                    shelfnumber,
                    brand_name
                )
                SELECT
                    s.store_id,
                    s.image_file_name,
                    s.s3path_annotated_file,
                    s.iteration_id,
                    s.prod_class_id AS cap_class_id,
                    NULL            AS prod_class_id,
                    s.x1,
                    s.x2,
                    s.y1,
                    s.y2,
                    s.shelfnumber,
                    s.brand_name
                FROM temp.sku_prediction_temp_sovi s
                ON CONFLICT DO NOTHING;
            """,
        },
        # ── 3 ─────────────────────────────────────────────────────────────────
        {
            "step": 3,
            "name": "Vertical match – assign prod_class_id by horizontal overlap",
            "sql": """
                WITH vertical_match AS (
                    SELECT
                        c.store_id,
                        c.image_file_name,
                        c.s3path_annotated_file,
                        c.iteration_id,
                        c.cap_class_id,
                        c.x1,
                        c.y1,
                        s.prod_class_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY
                                c.store_id,
                                c.image_file_name,
                                c.s3path_annotated_file,
                                c.iteration_id,
                                c.cap_class_id,
                                c.x1,
                                c.y1
                            ORDER BY ABS(
                                ((c.x1 + c.x2) / 2.0) - ((s.x1 + s.x2) / 2.0)
                            )
                        ) AS rn
                    FROM temp.cap_prediction_temp_sovi c
                    JOIN temp.sku_prediction_temp_sovi s
                      ON  c.store_id             = s.store_id
                     AND c.image_file_name       = s.image_file_name
                     AND c.s3path_annotated_file = s.s3path_annotated_file
                     AND c.iteration_id          = s.iteration_id
                    WHERE ((c.x1 + c.x2) / 2.0) BETWEEN s.x1 AND s.x2
                )
                UPDATE temp.cap_prediction_temp_sovi c
                SET prod_class_id = v.prod_class_id
                FROM vertical_match v
                WHERE c.store_id             = v.store_id
                  AND c.image_file_name      = v.image_file_name
                  AND c.s3path_annotated_file = v.s3path_annotated_file
                  AND c.iteration_id         = v.iteration_id
                  AND c.cap_class_id         = v.cap_class_id
                  AND c.x1                  = v.x1
                  AND c.y1                  = v.y1
                  AND v.rn                  = 1;
            """,
        },
        # ── 4 ─────────────────────────────────────────────────────────────────
        {
            "step": 4,
            "name": "Nearest-match fallback – centroid distance for NULL prod_class_id",
            "sql": """
                WITH nearest_match AS (
                    SELECT
                        c.store_id,
                        c.image_file_name,
                        c.s3path_annotated_file,
                        c.iteration_id,
                        c.cap_class_id,
                        c.x1,
                        c.y1,
                        s.prod_class_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY
                                c.store_id,
                                c.image_file_name,
                                c.s3path_annotated_file,
                                c.iteration_id,
                                c.cap_class_id,
                                c.x1,
                                c.y1
                            ORDER BY
                                POWER(((c.x1 + c.x2) / 2.0) - ((s.x1 + s.x2) / 2.0), 2)
                              + POWER(((c.y1 + c.y2) / 2.0) - ((s.y1 + s.y2) / 2.0), 2)
                        ) AS rn
                    FROM temp.cap_prediction_temp_sovi c
                    JOIN temp.sku_prediction_temp_sovi s
                      ON  c.store_id             = s.store_id
                     AND c.image_file_name       = s.image_file_name
                     AND c.s3path_annotated_file = s.s3path_annotated_file
                     AND c.iteration_id          = s.iteration_id
                    WHERE c.prod_class_id IS NULL
                )
                UPDATE temp.cap_prediction_temp_sovi c
                SET prod_class_id = n.prod_class_id
                FROM nearest_match n
                WHERE c.store_id             = n.store_id
                  AND c.image_file_name      = n.image_file_name
                  AND c.s3path_annotated_file = n.s3path_annotated_file
                  AND c.iteration_id         = n.iteration_id
                  AND c.cap_class_id         = n.cap_class_id
                  AND c.x1                  = n.x1
                  AND c.y1                  = n.y1
                  AND n.rn                  = 1;
            """,
        },
        # ── 5 ─────────────────────────────────────────────────────────────────
        {
            "step": 5,
            "name": "Remove small caps inside SKU bounding box (< 15 % area)",
            "sql": """
                DELETE FROM temp.cap_prediction_temp_sovi c
                USING temp.sku_prediction_temp_sovi s
                WHERE c.store_id             = s.store_id
                  AND c.image_file_name      = s.image_file_name
                  AND c.s3path_annotated_file = s.s3path_annotated_file
                  AND c.iteration_id         = s.iteration_id
                  AND c.prod_class_id        = s.prod_class_id
                  AND c.x1  >= s.x1
                  AND c.y1  >= s.y1
                  AND c.x2  <= s.x2
                  AND c.y2  <= s.y2
                  AND ((c.x2 - c.x1) * (c.y2 - c.y1))
                      < 0.15 * ((s.x2 - s.x1) * (s.y2 - s.y1));
            """,
        },
        # ── 6 ─────────────────────────────────────────────────────────────────
        {
            "step": 6,
            "name": "Remove duplicate rows",
            "sql": """
                DELETE FROM temp.cap_prediction_temp_sovi c
                USING (
                    SELECT
                        store_id,
                        image_file_name,
                        s3path_annotated_file,
                        iteration_id,
                        cap_class_id,
                        x1,
                        y1,
                        MIN(ctid) AS keep_ctid
                    FROM temp.cap_prediction_temp_sovi
                    GROUP BY
                        store_id,
                        image_file_name,
                        s3path_annotated_file,
                        iteration_id,
                        cap_class_id,
                        x1,
                        y1
                    HAVING COUNT(*) > 1
                ) d
                WHERE c.store_id             = d.store_id
                  AND c.image_file_name      = d.image_file_name
                  AND c.s3path_annotated_file = d.s3path_annotated_file
                  AND c.iteration_id         = d.iteration_id
                  AND c.cap_class_id         = d.cap_class_id
                  AND c.x1                  = d.x1
                  AND c.y1                  = d.y1
                  AND c.ctid                <> d.keep_ctid;
            """,
        },
        # ── 7 ─────────────────────────────────────────────────────────────────
        {
            "step": 7,
            "name": "Populate orgi.coolermetricsmaster_sovi",
            "sql": f"""
                WITH image_map AS (
                    SELECT DISTINCT
                        cpt.iteration_id AS iterationid,
                        cpt.store_id     AS storeid,
                        cpt.image_file_name,
                        cpt.s3path_annotated_file,
                        DENSE_RANK() OVER (
                            PARTITION BY cpt.iteration_id
                            ORDER BY
                                cpt.store_id,
                                cpt.image_file_name,
                                cpt.s3path_annotated_file
                        ) AS iterationtranid
                    FROM temp.cap_prediction_temp_sovi cpt
                    WHERE cpt.iteration_id = {iid}
                )
                INSERT INTO orgi.coolermetricsmaster_sovi (
                    iterationid,
                    iterationtranid,
                    storeid,
                    caserid,
                    modelrun,
                    processed_flag
                )
                SELECT
                    i.iterationid,
                    i.iterationtranid,
                    i.storeid,
                    pm.caserid,
                    NOW(),
                    'N'
                FROM image_map i
                JOIN orgi.puritymapping pm ON pm.caserid IS NOT NULL
                ON CONFLICT (iterationid, iterationtranid) DO NOTHING;
            """,
        },
        # ── 8 ─────────────────────────────────────────────────────────────────
        {
            "step": 8,
            "name": "Populate orgi.coolermetricstransaction_sovi",
            "sql": f"""
                WITH image_map AS (
                    SELECT DISTINCT
                        cpt.iteration_id AS iterationid,
                        cpt.store_id     AS storeid,
                        cpt.image_file_name,
                        cpt.s3path_annotated_file,
                        DENSE_RANK() OVER (
                            PARTITION BY cpt.iteration_id
                            ORDER BY
                                cpt.store_id,
                                cpt.image_file_name,
                                cpt.s3path_annotated_file
                        ) AS iterationtranid
                    FROM temp.cap_prediction_temp_sovi cpt
                    WHERE cpt.iteration_id = {iid}
                )
                INSERT INTO orgi.coolermetricstransaction_sovi (
                    iterationid,
                    iterationtranid,
                    shelfnumber,
                    productsequenceno,
                    productclassid,
                    x1,
                    y1,
                    x2,
                    y2,
                    confidence,
                    imagefilename,
                    s3path_actual_file,
                    s3path_annotated_file
                )
                SELECT
                    cpt.iteration_id,
                    im.iterationtranid,
                    cpt.shelfnumber,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            cpt.iteration_id,
                            cpt.store_id,
                            cpt.image_file_name,
                            cpt.s3path_annotated_file,
                            cpt.shelfnumber
                        ORDER BY cpt.prod_class_id, cpt.x1
                    ) AS productsequenceno,
                    cpt.prod_class_id,
                    cpt.x1,
                    cpt.y1,
                    cpt.x2,
                    cpt.y2,
                    NULL,
                    cpt.image_file_name,
                    'april_store_images/' || cpt.image_file_name,
                    cpt.s3path_annotated_file
                FROM temp.cap_prediction_temp_sovi cpt
                JOIN image_map im
                  ON  im.iterationid           = cpt.iteration_id
                 AND im.storeid                = cpt.store_id
                 AND im.image_file_name        = cpt.image_file_name
                 AND im.s3path_annotated_file  = cpt.s3path_annotated_file
                WHERE cpt.iteration_id = {iid};
            """,
        },
    ]


# ── Core runner ────────────────────────────────────────────────────────────────
def run_sovi_pipeline(db_config: dict, iteration_id: int) -> PipelineResult:
    """
    Execute all 8 SOVI post-processing steps sequentially.

    Parameters
    ----------
    db_config : dict
        Database credentials from config.json (keys: host, port, database,
        user, password).
    iteration_id : int
        The iteration ID used in the current pipeline run — same value passed
        to run_sovi_analysis().

    Returns
    -------
    PipelineResult
        Dataclass containing per-step outcomes and the overall status.
        Always logs a formatted summary table to the application logger.
    """
    pipeline_start = time.monotonic()
    step_results: list[StepResult] = []
    overall_status = "success"

    logger.info("=" * 100)
    logger.info(f"  SOVI PREDICTION PIPELINE  –  START  (iteration_id={iteration_id})")
    logger.info("=" * 100)

    # ── Open connection ────────────────────────────────────────────────────────
    try:
        conn = psycopg2.connect(
            host=db_config["host"],
            port=db_config["port"],
            dbname=db_config["database"],
            user=db_config["user"],
            password=db_config["password"],
        )
        conn.autocommit = False
        logger.info(
            f"  Connected to {db_config['host']}:{db_config['port']} "
            f"/ {db_config['database']}"
        )
    except Exception as exc:
        logger.error(f"  Database connection failed: {exc}")
        result = PipelineResult(
            iteration_id=iteration_id,
            overall_status="failed",
            total_duration_ms=round((time.monotonic() - pipeline_start) * 1000, 2),
            steps=[
                StepResult(
                    step=0,
                    name="Database connection",
                    status="failed",
                    rows_affected=None,
                    duration_ms=0.0,
                    error=str(exc),
                )
            ],
        )
        result.log_summary()
        return result

    # ── Execute steps ──────────────────────────────────────────────────────────
    try:
        with conn:
            with conn.cursor() as cur:
                for query in _build_queries(iteration_id):
                    step_start = time.monotonic()
                    step_num  = query["step"]
                    step_name = query["name"]

                    logger.info(f"  ▶  Step {step_num}/8 – {step_name} …")

                    try:
                        cur.execute(query["sql"])
                        rows     = cur.rowcount if cur.rowcount >= 0 else None
                        duration = round((time.monotonic() - step_start) * 1000, 2)

                        step_results.append(
                            StepResult(
                                step=step_num,
                                name=step_name,
                                status="success",
                                rows_affected=rows,
                                duration_ms=duration,
                            )
                        )
                        rows_label = f"{rows} rows" if rows is not None else ""
                        logger.info(
                            f"     ✓  Completed in {duration:.1f} ms  {rows_label}"
                        )

                    except Exception as exc:
                        duration  = round((time.monotonic() - step_start) * 1000, 2)
                        err_trace = traceback.format_exc()

                        step_results.append(
                            StepResult(
                                step=step_num,
                                name=step_name,
                                status="failed",
                                rows_affected=None,
                                duration_ms=duration,
                                error=err_trace,
                            )
                        )
                        logger.error(
                            f"     ✗  FAILED in {duration:.1f} ms – rolling back transaction"
                        )
                        logger.error(err_trace)

                        overall_status = "failed"
                        conn.rollback()
                        break   # abort remaining steps

    finally:
        try:
            conn.close()
        except Exception:
            pass

    # ── Assemble and return result ─────────────────────────────────────────────
    total_ms = round((time.monotonic() - pipeline_start) * 1000, 2)

    result = PipelineResult(
        iteration_id=iteration_id,
        overall_status=overall_status,
        total_duration_ms=total_ms,
        steps=step_results,
    )
    result.log_summary()
    return result