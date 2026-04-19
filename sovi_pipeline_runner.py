SOVI_SQL = """
/* =========================================================
   1. UNIQUE INDEX
   ========================================================= */
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

/* =========================================================
   2. INSERT CAP PREDICTIONS FROM SKU TABLE
   ========================================================= */
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

/* =========================================================
   3. VERTICAL MATCH
   ========================================================= */
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
      ON c.store_id = s.store_id
     AND c.image_file_name = s.image_file_name
     AND c.s3path_annotated_file = s.s3path_annotated_file
     AND c.iteration_id = s.iteration_id
    WHERE ((c.x1 + c.x2) / 2.0) BETWEEN s.x1 AND s.x2
)
UPDATE temp.cap_prediction_temp_sovi c
SET prod_class_id = v.prod_class_id
FROM vertical_match v
WHERE c.store_id = v.store_id
  AND c.image_file_name = v.image_file_name
  AND c.s3path_annotated_file = v.s3path_annotated_file
  AND c.iteration_id = v.iteration_id
  AND c.cap_class_id = v.cap_class_id
  AND c.x1 = v.x1
  AND c.y1 = v.y1
  AND v.rn = 1;

/* =========================================================
   4. NEAREST MATCH (FALLBACK)
   ========================================================= */
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
      ON c.store_id = s.store_id
     AND c.image_file_name = s.image_file_name
     AND c.s3path_annotated_file = s.s3path_annotated_file
     AND c.iteration_id = s.iteration_id
    WHERE c.prod_class_id IS NULL
)
UPDATE temp.cap_prediction_temp_sovi c
SET prod_class_id = n.prod_class_id
FROM nearest_match n
WHERE c.store_id = n.store_id
  AND c.image_file_name = n.image_file_name
  AND c.s3path_annotated_file = n.s3path_annotated_file
  AND c.iteration_id = n.iteration_id
  AND c.cap_class_id = n.cap_class_id
  AND c.x1 = n.x1
  AND c.y1 = n.y1
  AND n.rn = 1;

/* =========================================================
   5. REMOVE SMALL CAPS INSIDE SKU BOX
   ========================================================= */
DELETE FROM temp.cap_prediction_temp_sovi c
USING temp.sku_prediction_temp_sovi s
WHERE c.store_id = s.store_id
  AND c.image_file_name = s.image_file_name
  AND c.s3path_annotated_file = s.s3path_annotated_file
  AND c.iteration_id = s.iteration_id
  AND c.prod_class_id = s.prod_class_id
  AND c.x1 >= s.x1
  AND c.y1 >= s.y1
  AND c.x2 <= s.x2
  AND c.y2 <= s.y2
  AND ((c.x2 - c.x1) * (c.y2 - c.y1))
      < 0.15 * ((s.x2 - s.x1) * (s.y2 - s.y1));

/* =========================================================
   6. REMOVE DUPLICATES
   ========================================================= */
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
WHERE c.store_id = d.store_id
  AND c.image_file_name = d.image_file_name
  AND c.s3path_annotated_file = d.s3path_annotated_file
  AND c.iteration_id = d.iteration_id
  AND c.cap_class_id = d.cap_class_id
  AND c.x1 = d.x1
  AND c.y1 = d.y1
  AND c.ctid <> d.keep_ctid;

/* =========================================================
   7. COOLER METRICS MASTER
   ========================================================= */
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
    WHERE cpt.iteration_id = 69
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
JOIN orgi.puritymapping pm
  ON pm.caserid IS NOT NULL
ON CONFLICT (iterationid, iterationtranid) DO NOTHING;

/* =========================================================
   8. COOLER METRICS TRANSACTION (SOVI)
   ========================================================= */
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
    WHERE cpt.iteration_id = 69
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
        ORDER BY
            cpt.prod_class_id,
            cpt.x1
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
  ON im.iterationid = cpt.iteration_id
 AND im.storeid = cpt.store_id
 AND im.image_file_name = cpt.image_file_name
 AND im.s3path_annotated_file = cpt.s3path_annotated_file
WHERE cpt.iteration_id = 69;
"""