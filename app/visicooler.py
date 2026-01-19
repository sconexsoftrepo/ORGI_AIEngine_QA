import os
import cv2
from ultralytics import YOLO
import logging
from app.db_handler import initialize_db_connection, close_db_connection, get_classtext
from app.config_loader import load_config
from app.s3_handler import S3Handler
from datetime import datetime
import re
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def check_visibilitydetails_schema(cur):
    """Check if visibilitydetails table exists and has correct schema (stub)"""
    return True


def upload_to_visibilitydetails(conn, cur, records, cyclecountid):
    """Upload visicooler records to orgi.visibilitydetails (stub - not currently used)"""
    pass


def should_ignore_class(cls_id: int, class_names: dict) -> bool:
    """Filter out unwanted detections"""
    name = class_names.get(cls_id, "").lower()
    false_negative_keywords = [" 700ml", "750ml","visicooler", "cooler"]
    return any(keyword in name for keyword in false_negative_keywords)


def extract_brand_from_name(name: str) -> str:
    """Extract brand from product name"""
    name_lower = name.lower().strip()
    
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
    
    words = name_lower.split()
    return words[0] if words else ""


def insert_cap_predictions(cur, cap_records):
    
    if not cap_records:
        return
    
    insert_query = """
    INSERT INTO temp.cap_prediction_temp
    (store_id, image_file_name, iteration_id, cap_class_id, x1, x2, y1, y2, prod_class_id, shelfnumber)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    try:
        cur.executemany(insert_query, cap_records)
        logger.info(f"Inserted {len(cap_records)} cap predictions with shelfnumber")
    except Exception as e:
        logger.error(f"Failed to insert cap predictions: {e}")
        raise


def insert_sku_predictions(cur, sku_records):
    if not sku_records:
        return
    
    insert_query = """
    INSERT INTO temp.sku_prediction_temp
    (store_id, image_file_name, iteration_id, prod_class_id, x1, x2, y1, y2, shelfnumber, brand_name)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    try:
        cur.executemany(insert_query, sku_records)
        logger.info(f"Inserted {len(sku_records)} SKU predictions with shelfnumber and brand_name")
    except Exception as e:
        logger.error(f"Failed to insert SKU predictions: {e}")
        raise


def run_visicooler_analysis(image_paths, config, s3_handler, conn, cur, 
                            output_folder_path, cyclecountid, iterationid=None):

    try:
        shelf_model_path = config['visicooler_config']['caps_model_path']
        sku_model_path = config['visicooler_config']['sku_model_path']
        annotation_model_path = config['visicooler_config']['model_path']
        
        # Separate confidence thresholds for better accuracy
        cap_conf_threshold = config['visicooler_config'].get('cap_conf_threshold', 0.1)
        sku_conf_threshold = config['visicooler_config'].get('sku_conf_threshold', 0.35)
        annotation_conf_threshold = config['visicooler_config'].get('conf_threshold', 0.12)

        shelf_model = YOLO(shelf_model_path)
        sku_model = YOLO(sku_model_path)
        annotation_model = YOLO(annotation_model_path)

        sku_class_names = sku_model.names
        shelf_class_names = shelf_model.names

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

        # Group images by store
        store_images = {}
        for row in image_paths:
            fileseqid, storename, filename, local_path, s3_key, orig_storeid, subcategory_id = row
            canonical_storeid = _get_canonical_storeid(filename, orig_storeid)
            sid = _norm_storeid(canonical_storeid)
            subcat_norm = normalize_subcat(subcategory_id)
            store_images.setdefault(sid, []).append(
                (fileseqid, storename, filename, local_path, s3_key, canonical_storeid, subcat_norm)
            )

        logger.info("Processing subcategory 605 only")

        if iterationid is None:
            cur.execute("SELECT COALESCE(MAX(iterationid), 0) FROM orgi.coolermetricsmaster")
            iterationid = cur.fetchone()[0] + 1
            logger.info(f"Generated new iterationid: {iterationid}")
        else:
            logger.info(f"Using provided iterationid: {iterationid}")

        

        total_processed = 0
        total_cap_detections = 0
        total_sku_detections = 0
        
        all_cap_records = []
        all_sku_records = []

        for sid, rows in store_images.items():
            # Track shelf numbers per store (605 images only)
            shelf_605_images = [r for r in rows if r[6] == 605]
            
            for stored_row in rows:
                fileseqid, storename, filename, local_path, s3_key, final_storeid, subcat_norm = stored_row

                if subcat_norm != 605:
                    continue

                try:
                    # Calculate shelfnumber for this image
                    shelf_index = shelf_605_images.index(stored_row) + 1
                    
                    image = cv2.imread(local_path)
                    if image is None:
                        logger.warning(f"Failed to read image: {filename}")
                        continue

                    image_height, image_width = image.shape[:2]
                    os.makedirs(output_folder_path, exist_ok=True)

                    # SKU detection
                    sku_results = sku_model(local_path, conf=sku_conf_threshold)

                    for result in sku_results:
                        if not result.orig_shape:
                            continue
                        sw = image_width / result.orig_shape[1]
                        sh = image_height / result.orig_shape[0]

                        for box in result.boxes:
                            cls_id = int(box.cls[0])
                            
                            if should_ignore_class(cls_id, sku_class_names):
                                logger.debug(f"Filtered out: {sku_class_names[cls_id]}")
                                continue

                            x1, y1, x2, y2 = box.xyxy[0]
                            x1_px, y1_px = int(x1 * sw), int(y1 * sh)
                            x2_px, y2_px = int(x2 * sw), int(y2 * sh)
                            
                            product_name = sku_class_names[cls_id]
                            brand_name = extract_brand_from_name(product_name)
                            
                            # Store with shelfnumber and brand_name
                            all_sku_records.append((
                                final_storeid,
                                filename,
                                iterationid,
                                cls_id,
                                x1_px,
                                x2_px,
                                y1_px,
                                y2_px,
                                shelf_index,  # shelfnumber
                                brand_name    # brand_name
                            ))
                            
                            total_sku_detections += 1

                    # Cap detection
                    cap_results = shelf_model(local_path, conf=cap_conf_threshold)

                    for result in cap_results:
                        if not result.orig_shape:
                            continue
                        sw = image_width / result.orig_shape[1]
                        sh = image_height / result.orig_shape[0]

                        for box in result.boxes:
                            cls_id = int(box.cls[0])
                            name = shelf_class_names.get(cls_id, "").lower()
                            if "cap" not in name:
                                continue

                            x1, y1, x2, y2 = box.xyxy[0]
                            x1_px, y1_px = int(x1 * sw), int(y1 * sh)
                            x2_px, y2_px = int(x2 * sw), int(y2 * sh)
                            
                            # Store with shelfnumber (prod_class_id will be filled by SQL)
                            all_cap_records.append((
                                final_storeid,
                                filename,
                                iterationid,
                                cls_id,
                                x1_px,
                                x2_px,
                                y1_px,
                                y2_px,
                                None,         # prod_class_id (filled by SQL matching)
                                shelf_index   # shelfnumber
                            ))
                            
                            total_cap_detections += 1

                    # Generate annotated image
                    s3path_annotated = f"ModelResults/Visicooler_{cyclecountid}/segmented_{filename}"
                    
                    try:
                        annotation_results = annotation_model(local_path, conf=annotation_conf_threshold)
                        rendered = annotation_results[0].plot()
                        out = os.path.join(output_folder_path, f"segmented_{filename}")
                        cv2.imwrite(out, rendered)
                        s3_handler.upload_file_to_s3(out, s3path_annotated)
                    except Exception as e:
                        logger.warning(f"Annotation failed: {e}")

                    total_processed += 1
                    
                    logger.info(
                        f"✓ {filename}: store={final_storeid}, shelf={shelf_index}, "
                        f"caps={len([r for r in all_cap_records if r[1] == filename])}, "
                        f"skus={len([r for r in all_sku_records if r[1] == filename])}"
                    )

                except Exception as e:
                    logger.error(f"Error processing {filename}: {e}")

        # Insert into temp tables (data accumulates across batches)
        if all_sku_records:
            insert_sku_predictions(cur, all_sku_records)
        
        if all_cap_records:
            insert_cap_predictions(cur, all_cap_records)
        
        conn.commit()

        logger.info("=" * 70)
        logger.info(f"VISICOOLER BATCH COMPLETE:")
        logger.info(f"  Iteration ID: {iterationid}")
        logger.info(f"  Images processed (this batch): {total_processed}")
        logger.info(f"  SKU detections (this batch): {total_sku_detections}")
        logger.info(f"  Cap detections (this batch): {total_cap_detections}")
        logger.info(f"  Batch data APPENDED to temp tables (not deleted)")
        logger.info("=" * 70)

        return []

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise