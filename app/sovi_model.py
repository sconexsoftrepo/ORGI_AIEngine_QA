import os
import cv2
import re
import time
import logging

import pg8000.dbapi as pg
from ultralytics import YOLO

from app.db_handler import close_db_connection
from app.db_retry import retry_on_network_error, verify_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SOVI processes:
#   category_id 1, 2 → all subcategory_ids
# ---------------------------------------------------------------------------
SOVI_CATEGORIES = {1, 2}


# ---------------------------------------------------------------------------
# Exact copies of helper functions from visicooler.py
# ---------------------------------------------------------------------------

def should_ignore_class(cls_id: int, class_names: dict) -> bool:
    # Filter out unwanted detections
    name = class_names.get(cls_id, "").lower()
    false_negative_keywords = [" 700ml", "750ml", "visicooler", "cooler"]
    return any(keyword in name for keyword in false_negative_keywords)


def extract_brand_from_name(name: str) -> str:
    # Extract brand from product name
    name_lower = name.lower().strip()

    # Remove size and package type info
    name_lower = re.sub(r'\d+ml|\d+l|pet|glass|bottle|can|cap', '', name_lower)
    name_lower = name_lower.strip()

    if "coca-cola zero" in name_lower or "coca cola zero" in name_lower:
        return "coca-cola zero"
    if "coca-cola" in name_lower or "coca cola" in name_lower or "coke" in name_lower:
        return "coca-cola"
    if "mountain dew" in name_lower:
        return "mountain dew"
    if "kinley soda" in name_lower:
        return "kinley soda"
    if "kinley water" in name_lower:
        return "kinley water"
    if "sprite" in name_lower:
        return "sprite"
    if "fanta" in name_lower:
        return "fanta"
    if "thums up" in name_lower or "thumbs up" in name_lower:
        return "thums up"
    if "limca" in name_lower:
        return "limca"
    if "maaza" in name_lower:
        return "maaza"
    if "pepsi" in name_lower:
        return "pepsi"
    if "mirinda" in name_lower:
        return "mirinda"
    if "7up" in name_lower or "7 up" in name_lower:
        return "7up"
    if "slice" in name_lower:
        return "slice"
    if "sting" in name_lower:
        return "sting"
    if "aquafina" in name_lower:
        return "aquafina"
    if "other" in name_lower:
        return "other"

    # Default to first word if no match
    words = name_lower.split()
    return words[0] if words else ""


# ---------------------------------------------------------------------------
# DB insert helpers
#
# Visicooler cap tuple (11 values — no brand_name):
#   store_id, image_file_name, iteration_id, cap_class_id,
#   x1, x2, y1, y2, prod_class_id, shelfnumber, s3path_annotated_file
#
# SOVI cap tuple (12 values — has brand_name per your SELECT):
#   store_id, image_file_name, iteration_id, cap_class_id,
#   x1, x2, y1, y2, prod_class_id, shelfnumber,
#   brand_name, s3path_annotated_file
#
# SKU tuple is identical in both (11 values):
#   store_id, image_file_name, iteration_id, prod_class_id,
#   x1, x2, y1, y2, shelfnumber, brand_name, s3path_annotated_file
# ---------------------------------------------------------------------------

@retry_on_network_error(max_retries=3, delay=5)
def insert_sovi_cap_predictions(cur, cap_records):
    # Insert SOVI cap predictions with retry on network errors
    if not cap_records:
        return

    if not verify_connection(cur):
        raise Exception("Database connection lost before SOVI cap insert")

    insert_query = """
    INSERT INTO temp.cap_prediction_temp_sovi
    (store_id, image_file_name, iteration_id, cap_class_id,
     x1, x2, y1, y2, prod_class_id, shelfnumber,
     brand_name, s3path_annotated_file)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING
    """
    try:
        cur.executemany(insert_query, cap_records)
        logger.info(f"Inserted SOVI cap predictions (up to {len(cap_records)} rows, duplicates skipped)")
    except Exception as e:
        logger.error(f"Failed to insert SOVI cap predictions: {type(e).__name__}: {e}")
        logger.warning("Falling back to row-by-row insert to isolate failures...")
        inserted = 0
        skipped = 0
        for record in cap_records:
            try:
                cur.execute(insert_query, record)
                inserted += 1
            except Exception as row_err:
                err_str = str(row_err)
                if '23505' in err_str or 'duplicate key' in err_str.lower():
                    skipped += 1
                else:
                    logger.error(f"Unexpected error inserting cap record {record}: {row_err}")
        logger.info(f"Row-by-row insert complete: {inserted} inserted, {skipped} duplicates skipped")


@retry_on_network_error(max_retries=3, delay=5)
def insert_sovi_sku_predictions(cur, sku_records):
    # Insert SOVI SKU predictions with retry on network errors
    if not sku_records:
        return

    if not verify_connection(cur):
        raise Exception("Database connection lost before SOVI SKU insert")

    insert_query = """
    INSERT INTO temp.sku_prediction_temp_sovi
    (store_id, image_file_name, iteration_id, prod_class_id,
     x1, x2, y1, y2, shelfnumber, brand_name, s3path_annotated_file)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT ON CONSTRAINT pk_sku_prediction_temp_sovi DO NOTHING
    """
    try:
        cur.executemany(insert_query, sku_records)
        logger.info(f"Inserted SOVI SKU predictions (up to {len(sku_records)} rows, duplicates skipped)")
    except Exception as e:
        logger.error(f"Failed to insert SOVI SKU predictions: {type(e).__name__}: {e}")
        logger.warning("Falling back to row-by-row insert to isolate failures...")
        inserted = 0
        skipped = 0
        for record in sku_records:
            try:
                cur.execute(insert_query, record)
                inserted += 1
            except Exception as row_err:
                err_str = str(row_err)
                if '23505' in err_str or 'duplicate key' in err_str.lower():
                    skipped += 1
                else:
                    logger.error(f"Unexpected error inserting SKU record {record}: {row_err}")
        logger.info(f"Row-by-row insert complete: {inserted} inserted, {skipped} duplicates skipped")


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def run_sovi_analysis(image_paths, config, s3_handler, conn, cur,
                      output_folder_path, cyclecountid, iterationid):
    """
    SOVI analysis — runs immediately after run_visicooler_analysis and
    before run_ollama_analysis in execute_models().

    Models
    ------
    shelf_model  visicooler_config.caps_model_path  (capmodelnew.pt)
                 SAME model as visicooler — cap detection only
    sku_model    sovi_config.model_path             (dipto.pt)
                 SOVI-specific — SKU detection + annotated image

    Categories processed
    --------------------
    category_id 1, 2  all subcategory_ids

    Iteration ID
    ------------
    Passed in from main.py — shared across visicooler, sovi, ollama and all
    batches.  Never regenerated inside this function.
    """

    try:
        db_config = config['db_config']

        # -------------------------------------------------------------------
        # Model paths and thresholds
        # -------------------------------------------------------------------
        # Cap model — from visicooler_config (shared, not duplicated)
        shelf_model_path   = config['visicooler_config']['caps_model_path']
        cap_conf_threshold = config['visicooler_config'].get('cap_conf_threshold', 0.1)

        # SKU model — SOVI-specific
        sovi_sku_model_path = config['sovi_config']['model_path']
        sku_conf_threshold  = config['sovi_config'].get('conf_threshold', 0.25)

        # -------------------------------------------------------------------
        # Inner helpers — identical to visicooler.py
        # -------------------------------------------------------------------
        def _norm_storeid(sid):
            if sid is None:
                return None
            if isinstance(sid, str):
                s = sid.strip()
                if s.isdigit():
                    return int(s)
                return s
            return sid

        def _get_canonical_storeid(filename, orig_storeid):
            # Requires live cur — must be called before DB is closed
            canonical = orig_storeid
            try:
                cur.execute("""
                    SELECT storeid
                    FROM orgi.batchtransactionvisibilityitems
                    WHERE imagefilename = %s
                    LIMIT 1
                """, (filename,))
                row = cur.fetchone()
                if row and row[0] is not None:
                    canonical = row[0]
            except Exception:
                pass
            return canonical

        def normalize_subcat(val):
            if val is None:
                return None
            s = str(val).strip().replace(',', '')
            if s.endswith('.0'):
                s = s[:-2]
            m = re.search(r'(\d+)', s)
            return int(m.group(1)) if m else None

        def normalize_category(val):
            if val is None:
                return None
            try:
                return int(str(val).strip().split('.')[0])
            except (ValueError, AttributeError):
                return None

        # -------------------------------------------------------------------
        # Step 1 — Re-open DB if visicooler already closed it
        # -------------------------------------------------------------------
        if conn is None or cur is None:
            logger.info("SOVI: Reconnecting to database")
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    conn = pg.connect(
                        host=db_config['host'],
                        port=db_config['port'],
                        database=db_config['database'],
                        user=db_config['user'],
                        password=db_config['password'],
                        timeout=30
                    )
                    cur = conn.cursor()
                    logger.info("SOVI: Database reconnected successfully")
                    break
                except Exception as e:
                    logger.warning(
                        f"SOVI: Reconnect attempt {attempt + 1}/{max_retries} failed: {e}"
                    )
                    if attempt < max_retries - 1:
                        time.sleep(5)
                    else:
                        logger.error("SOVI: All reconnect attempts failed")
                        raise

        # -------------------------------------------------------------------
        # Step 2 — Fetch category_id for every file in this batch
        # -------------------------------------------------------------------
        filenames_in_batch = [os.path.basename(row[2]) for row in image_paths]
        category_map = {}   # basename → (category_id, subcategory_id)

        try:
            cur.execute(
                """
                SELECT filename, category_id, subcategory_id
                FROM orgi.fileupload
                WHERE filename = ANY(%s)
                """,
                (filenames_in_batch,)
            )
            for fname, cat_id, sub_id in cur.fetchall():
                category_map[os.path.basename(fname)] = (cat_id, sub_id)
            logger.info(f"SOVI: Fetched category data for {len(category_map)} files")
        except Exception as e:
            logger.warning(
                f"SOVI: Could not fetch category data ({e}). "
                "Falling back to subcategory_id from image_paths."
            )

        # -------------------------------------------------------------------
        # Step 3 — Group images by store, applying SOVI category filter.
        #          Also resolve canonical store ID (same as visicooler).
        # -------------------------------------------------------------------
        store_images = {}

        for row in image_paths:
            fileseqid, storename, filename, local_path, s3_key, orig_storeid, subcategory_id = row
            basename = os.path.basename(filename)

            # category_id from DB; fall back to treating as category 6
            cat_id_raw, sub_id_raw = category_map.get(basename, (6, subcategory_id))
            norm_cat    = normalize_category(cat_id_raw)
            norm_subcat = normalize_subcat(sub_id_raw)

            # SOVI filter
            is_sovi = norm_cat in SOVI_CATEGORIES
            if not is_sovi:
                continue

            # Canonical store ID (same DB lookup as visicooler)
            canonical_storeid = _get_canonical_storeid(filename, orig_storeid)
            sid = _norm_storeid(canonical_storeid)

            store_images.setdefault(sid, []).append(
                (fileseqid, storename, filename, local_path, s3_key,
                 canonical_storeid, norm_subcat, norm_cat)
            )

        total_sovi_images = sum(len(v) for v in store_images.values())
        logger.info(
            f"SOVI: {total_sovi_images} eligible images across "
            f"{len(store_images)} stores "
            f"(categories 1 and 2)"
        )
        logger.info(f"SOVI: Using provided iterationid: {iterationid}")

        if total_sovi_images == 0:
            logger.warning("SOVI: No eligible images found — skipping.")
            try:
                close_db_connection(conn, cur)
            except Exception:
                pass
            return []

        # -------------------------------------------------------------------
        # Step 4 — Close DB before long GPU inference  (mirrors visicooler.py)
        # -------------------------------------------------------------------
        try:
            if conn is not None and cur is not None:
                close_db_connection(conn, cur)
                logger.info("SOVI: Database closed before inference (will reopen for insert)")
        except Exception as e:
            logger.warning(f"SOVI: Error closing connection before inference: {e}")

        conn = None
        cur  = None

        # -------------------------------------------------------------------
        # Step 5 — Load models
        # -------------------------------------------------------------------
        logger.info(f"SOVI: Loading shelf (cap) model : {shelf_model_path}")
        logger.info(f"SOVI: Loading SKU model          : {sovi_sku_model_path}")
        shelf_model = YOLO(shelf_model_path)
        sku_model   = YOLO(sovi_sku_model_path)
        logger.info("SOVI: Models loaded successfully")

        shelf_class_names = shelf_model.names
        sku_class_names   = sku_model.names

        # -------------------------------------------------------------------
        # Step 6 — Counters and accumulators
        # -------------------------------------------------------------------
        total_processed      = 0
        total_sku_detections = 0
        total_cap_detections = 0
        all_sku_records      = []
        all_cap_records      = []

        os.makedirs(output_folder_path, exist_ok=True)
        logger.info(f"SOVI: Starting analysis on {total_sovi_images} images")

        # -------------------------------------------------------------------
        # Step 7 — Per-store inference loop
        # -------------------------------------------------------------------
        for sid, rows in store_images.items():

            # Group by (norm_cat, norm_subcat) so shelf numbering restarts
            # per subcategory within each store — mirrors how visicooler
            # builds shelf_605_images per store
            subcat_groups = {}
            for r in rows:
                group_key = (r[7], r[6])   # (norm_cat, norm_subcat)
                subcat_groups.setdefault(group_key, []).append(r)

            for group_key, group_rows in subcat_groups.items():

                for stored_row in group_rows:
                    (fileseqid, storename, filename, local_path, s3_key,
                     final_storeid, norm_subcat, norm_cat) = stored_row

                    try:
                        # 1-based shelf index within this group
                        # (mirrors: shelf_605_images.index(stored_row) + 1)
                        shelf_index = group_rows.index(stored_row) + 1

                        # Read image
                        image = cv2.imread(local_path)
                        if image is None:
                            logger.warning(f"SOVI: Failed to read image: {filename}")
                            continue

                        image_height, image_width = image.shape[:2]

                        # S3 path for annotated image
                        s3path_annotated = (
                            f"ModelResults/SOVI_{cyclecountid}/segmented_{filename}"
                        )

                        # ---------------------------------------------------
                        # SKU detection  (dipto.pt)
                        # Mirrors visicooler sku_model block exactly
                        # ---------------------------------------------------
                        sku_results = sku_model(local_path, conf=sku_conf_threshold)

                        for result in sku_results:
                            if not result.orig_shape:
                                continue

                            sw = image_width  / result.orig_shape[1]
                            sh = image_height / result.orig_shape[0]

                            for box in result.boxes:
                                cls_id = int(box.cls[0])

                                if should_ignore_class(cls_id, sku_class_names):
                                    continue

                                x1, y1, x2, y2 = box.xyxy[0]
                                x1_px, y1_px = int(x1 * sw), int(y1 * sh)
                                x2_px, y2_px = int(x2 * sw), int(y2 * sh)

                                product_name = sku_class_names[cls_id]
                                brand_name   = extract_brand_from_name(product_name)

                                all_sku_records.append((
                                    final_storeid,    # store_id
                                    filename,          # image_file_name
                                    iterationid,       # iteration_id
                                    cls_id,            # prod_class_id
                                    x1_px,             # x1
                                    x2_px,             # x2
                                    y1_px,             # y1
                                    y2_px,             # y2
                                    shelf_index,       # shelfnumber
                                    brand_name,        # brand_name
                                    s3path_annotated   # s3path_annotated_file
                                ))
                                total_sku_detections += 1

                        # ---------------------------------------------------
                        # Cap detection  (capmodelnew.pt — SAME as visicooler)
                        # Mirrors visicooler shelf_model block exactly
                        # ---------------------------------------------------
                        cap_results = shelf_model(local_path, conf=cap_conf_threshold)

                        for result in cap_results:
                            if not result.orig_shape:
                                continue

                            sw = image_width  / result.orig_shape[1]
                            sh = image_height / result.orig_shape[0]

                            for box in result.boxes:
                                cls_id = int(box.cls[0])
                                name   = shelf_class_names.get(cls_id, "").lower()

                                # Only process cap detections (mirrors visicooler)
                                if "cap" not in name:
                                    continue

                                x1, y1, x2, y2 = box.xyxy[0]
                                x1_px, y1_px = int(x1 * sw), int(y1 * sh)
                                x2_px, y2_px = int(x2 * sw), int(y2 * sh)

                                all_cap_records.append((
                                    final_storeid,    # store_id
                                    filename,          # image_file_name
                                    iterationid,       # iteration_id
                                    cls_id,            # cap_class_id
                                    x1_px,             # x1
                                    x2_px,             # x2
                                    y1_px,             # y1
                                    y2_px,             # y2
                                    None,              # prod_class_id  (NULL — post-proc fills)
                                    shelf_index,       # shelfnumber
                                    None,              # brand_name     (NULL — post-proc fills)
                                    s3path_annotated   # s3path_annotated_file
                                ))
                                total_cap_detections += 1

                        # ---------------------------------------------------
                        # Annotated image — use sku_model (dipto.pt).
                        # Mirrors visicooler: sku_model used for annotation,
                        # not the cap/shelf model.
                        # ---------------------------------------------------
                        try:
                            sku_annotation_results = sku_model(
                                local_path, conf=sku_conf_threshold
                            )
                            rendered = sku_annotation_results[0].plot()
                            out = os.path.join(
                                output_folder_path, f"segmented_{filename}"
                            )
                            cv2.imwrite(out, rendered)
                            s3_handler.upload_file_to_s3(out, s3path_annotated)
                            logger.info(
                                f"SOVI: Uploaded annotated image: segmented_{filename}"
                            )
                        except Exception as e:
                            logger.warning(f"SOVI: Annotation failed for {filename}: {e}")

                        total_processed += 1

                        # Progress log every 5 images or on the last image
                        if total_processed % 5 == 0 or total_processed == total_sovi_images:
                            remaining = total_sovi_images - total_processed
                            logger.info(
                                f"SOVI progress: {total_processed}/{total_sovi_images} "
                                f"images processed, {remaining} remaining"
                            )

                    except Exception as e:
                        logger.error(f"SOVI: Error processing {filename}: {e}")

        # -------------------------------------------------------------------
        # Step 8 — Re-open DB and insert  (mirrors visicooler.py exactly)
        # -------------------------------------------------------------------
        logger.info("SOVI: Analysis complete, reopening database for insertion")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                conn = pg.connect(
                    host=db_config['host'],
                    port=db_config['port'],
                    database=db_config['database'],
                    user=db_config['user'],
                    password=db_config['password'],
                    timeout=30
                )
                cur = conn.cursor()
                logger.info("SOVI: Database reconnected successfully")
                break
            except Exception as e:
                logger.warning(
                    f"SOVI: Failed to reconnect "
                    f"(attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    logger.error("SOVI: Failed to reconnect after all retries")
                    raise

        # Insert SKU detections into SOVI temp table
        if all_sku_records:
            insert_sovi_sku_predictions(cur, all_sku_records)

        # Insert cap detections into SOVI temp table
        if all_cap_records:
            insert_sovi_cap_predictions(cur, all_cap_records)

        # Commit all changes
        conn.commit()
        logger.info("SOVI: Database commit successful")

        # Close database connection
        try:
            close_db_connection(conn, cur)
            logger.info("SOVI: Database closed after insert")
        except Exception as e:
            logger.warning(f"SOVI: Error closing connection: {e}")

        # Final statistics
        logger.info("SOVI batch complete")
        logger.info(f"  Iteration ID     : {iterationid}")
        logger.info(f"  Images processed : {total_processed}")
        logger.info(f"  SKU detections   : {total_sku_detections}")
        logger.info(f"  Cap detections   : {total_cap_detections}")

        return []

    except Exception as e:
        logger.error(f"SOVI: Fatal error: {type(e).__name__}: {e}")

        # Close DB if still open (mirrors visicooler.py cleanup)
        if conn is not None:
            try:
                close_db_connection(conn, cur)
            except Exception as close_error:
                logger.warning(
                    f"SOVI: Error closing connection during cleanup: {close_error}"
                )

        raise