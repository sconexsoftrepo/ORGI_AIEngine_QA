# import os
# import cv2
# from ultralytics import YOLO
# import logging
# from app.db_handler import initialize_db_connection, close_db_connection, get_classtext
# from app.config_loader import load_config
# from app.s3_handler import S3Handler
# from datetime import datetime
# import re
# from collections import defaultdict

# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

# def should_ignore_class(cls_id: int, class_names: dict) -> bool:
#     name = class_names.get(cls_id, "").lower()
#     ignore_keywords = ["700ml", "750ml", "visicooler", "cooler"]
#     return any(keyword in name for keyword in ignore_keywords)

# def merge_overlapping_boxes(boxes, threshold=3):
#     # retained for engine compatibility (not used)
#     if not boxes:
#         return []
#     boxes = sorted(boxes, key=lambda b: b["top_y"])
#     merged = [boxes[0]]
#     for box in boxes[1:]:
#         prev = merged[-1]
#         if box["top_y"] <= prev["bottom_y"] + threshold:
#             prev["bottom_y"] = max(prev["bottom_y"], box["bottom_y"])
#         else:
#             merged.append(box)
#     return merged

# def check_visibilitydetails_schema(cur):
#     return True

# def upload_to_visibilitydetails(conn, cur, records, cyclecountid):
#     """Upload visicooler records to orgi.visibilitydetails (stub - not currently used)"""
#     pass

# def run_visicooler_analysis(image_paths, config, s3_handler, conn, cur, output_folder_path, cyclecountid):
#     try:
#         # --------------------------------------------------
#         # Model declarations (THREE MODELS ARE USED)
#         # --------------------------------------------------
#         shelf_model_path = config['visicooler_config']['caps_model_path']   # caps only
#         sku_model_path   = config['visicooler_config']['sku_model_path']    # front SKUs only
#         annotation_model_path = config['visicooler_config']['model_path']   # for annotations (capmodelnew.pt)
#         conf_threshold   = config['visicooler_config']['conf_threshold']

#         shelf_model = YOLO(shelf_model_path)
#         sku_model   = YOLO(sku_model_path)
#         annotation_model = YOLO(annotation_model_path)  # For generating annotated images

#         sku_class_names   = sku_model.names
#         shelf_class_names = shelf_model.names

#         def _norm_storeid(sid):
#             if sid is None:
#                 return None
#             if isinstance(sid, str):
#                 s = sid.strip()
#                 if s.isdigit():
#                     return int(s)
#                 return s
#             return sid

#         def _get_canonical_storeid(filename, orig_storeid):
#             canonical = orig_storeid
#             try:
#                 cur.execute("""
#                     SELECT storeid
#                     FROM orgi.batchtransactionvisibilityitems
#                     WHERE imagefilename = %s
#                     LIMIT 1
#                 """, (filename,))
#                 row = cur.fetchone()
#                 if row and row[0] is not None:
#                     canonical = row[0]
#             except Exception:
#                 pass
#             return canonical

#         def normalize_subcat(val):
#             if val is None:
#                 return None
#             s = str(val).strip().replace(',', '')
#             if s.endswith('.0'):
#                 s = s[:-2]
#             m = re.search(r'(\d+)', s)
#             return int(m.group(1)) if m else None

#         # --------------------------------------------------
#         # Group images by store
#         # --------------------------------------------------
#         store_images = {}
#         for row in image_paths:
#             fileseqid, storename, filename, local_path, s3_key, orig_storeid, subcategory_id = row
#             canonical_storeid = _get_canonical_storeid(filename, orig_storeid)
#             sid = _norm_storeid(canonical_storeid)
#             subcat_norm = normalize_subcat(subcategory_id)
#             store_images.setdefault(sid, []).append(
#                 (fileseqid, storename, filename, local_path, s3_key, canonical_storeid, subcat_norm)
#             )

#         logger.info("Store targets locked to subcategory 605")

#         cur.execute("SELECT COALESCE(MAX(iterationid), 0) FROM orgi.coolermetricsmaster")
#         iterationid = cur.fetchone()[0] + 1

#         total_processed = 0
#         total_products = 0

#         for sid, rows in store_images.items():
#             # Generate iterationtranid ONCE per store
#             iterationtranid = (
#                 int(rows[0][0])
#                 if rows[0][0] and str(rows[0][0]).isdigit()
#                 else int(datetime.now().timestamp() * 1000) % 100000000
#             )
            
#             for stored_row in rows:
#                 fileseqid, storename, filename, local_path, s3_key, final_storeid, subcat_norm = stored_row

#                 # ONLY process subcategory 605
#                 if subcat_norm != 605:
#                     continue

#                 try:
#                     image = cv2.imread(local_path)
#                     if image is None:
#                         logger.warning(f"Failed to read image: {filename}")
#                         continue

#                     image_height, image_width = image.shape[:2]
#                     os.makedirs(output_folder_path, exist_ok=True)

#                     # --------------------------------------------------
#                     # Single shelf region (605 = one image = one shelf)
#                     # --------------------------------------------------
#                     shelf_605_rows = [r for r in store_images[sid] if r[6] == 605]
#                     shelf_index = shelf_605_rows.index(stored_row) + 1

#                     # --------------------------------------------------
#                     # Caser mapping
#                     # --------------------------------------------------
#                     caserid = 0
#                     try:
#                         cur.execute("""
#                             SELECT cooler FROM orgi.storemaster
#                             WHERE storeid = %s LIMIT 1
#                         """, (final_storeid,))
#                         row = cur.fetchone()
#                         if row and row[0]:
#                             m = re.search(r'(\d+)', row[0])
#                             if m:
#                                 cur.execute("""
#                                     SELECT caserid FROM orgi.puritymapping
#                                     WHERE casername ILIKE %s LIMIT 1
#                                 """, (f"%{m.group(1)}%",))
#                                 prow = cur.fetchone()
#                                 if prow:
#                                     caserid = prow[0]
#                     except Exception as e:
#                         logger.warning(f"Failed to get caserid for store {final_storeid}: {e}")

#                     # --------------------------------------------------
#                     # FRONT SKU DETECTION (SKU MODEL ONLY)
#                     # --------------------------------------------------
#                     sku_results = sku_model(local_path, conf=conf_threshold)
#                     front_skus = []

#                     for result in sku_results:
#                         if not result.orig_shape:
#                             continue
#                         sw = image_width / result.orig_shape[1]
#                         sh = image_height / result.orig_shape[0]

#                         for box in result.boxes:
#                             cls_id = int(box.cls[0])
#                             if should_ignore_class(cls_id, sku_class_names):
#                                 continue

#                             x1, y1, x2, y2 = box.xyxy[0]
#                             front_skus.append({
#                                 "class_id": cls_id,
#                                 "name": sku_class_names[cls_id],
#                                 "conf": float(box.conf[0]),
#                                 "bbox": (
#                                     int(x1 * sw), int(y1 * sh),
#                                     int(x2 * sw), int(y2 * sh)
#                                 ),
#                                 "center_y": int((y1 + y2) * sh / 2)
#                             })

#                     # --------------------------------------------------
#                     # CAP DETECTION (SHELF MODEL ONLY)
#                     # --------------------------------------------------
#                     cap_results = shelf_model(local_path, conf=conf_threshold)
#                     cap_detections = []

#                     for result in cap_results:
#                         if not result.orig_shape:
#                             continue
#                         sw = image_width / result.orig_shape[1]
#                         sh = image_height / result.orig_shape[0]

#                         for box in result.boxes:
#                             cls_id = int(box.cls[0])
#                             name = shelf_class_names.get(cls_id, "").lower()
#                             if "cap" not in name:
#                                 continue

#                             x1, y1, x2, y2 = box.xyxy[0]
#                             cap_detections.append({
#                                 "conf": float(box.conf[0]),
#                                 "center_y": int((y1 + y2) * sh / 2)
#                             })

#                     # --------------------------------------------------
#                     # Cap → nearest front SKU inference
#                     # --------------------------------------------------
#                     inferred_skus = []
#                     for cap in cap_detections:
#                         closest = None
#                         bestd = 1e9
#                         for front in front_skus:
#                             d = abs(front["center_y"] - cap["center_y"])
#                             if d < bestd:
#                                 bestd = d
#                                 closest = front
#                         if closest:
#                             inferred_skus.append({
#                                 **closest,
#                                 "conf": cap["conf"],
#                                 "inferred": True
#                             })
                    
#                     # Choose the dominant interpretation (no double counting)
#                     if len(inferred_skus) > len(front_skus):
#                         final_skus = inferred_skus
#                     else:
#                         final_skus = front_skus
                    
#                     shelf_sku_map = {shelf_index: final_skus}

#                     # --------------------------------------------------
#                     # Annotated image (using capmodelnew.pt)
#                     # --------------------------------------------------
#                     s3path_annotated = f"ModelResults/Visicooler_{cyclecountid}/segmented_{filename}"
                    
#                     try:
#                         # Run capmodelnew.pt model for annotation
#                         annotation_results = annotation_model(local_path, conf=conf_threshold)
#                         rendered = annotation_results[0].plot()
#                         out = os.path.join(output_folder_path, f"segmented_{filename}")
#                         cv2.imwrite(out, rendered)
#                         s3_handler.upload_file_to_s3(out, s3path_annotated)
#                     except Exception as e:
#                         logger.warning(f"Failed to generate/upload annotated image for {filename}: {e}")

#                     # --------------------------------------------------
#                     # DB INSERTS (Updated with S3 paths)
#                     # --------------------------------------------------
#                     for shelf_id, sku_list in shelf_sku_map.items():
#                         productsequenceno = 1
#                         for sku in sku_list:
#                             x1, y1, x2, y2 = sku["bbox"]

#                             cur.execute("""
#                                 INSERT INTO orgi.coolermetricsmaster
#                                 (iterationid, iterationtranid, storeid, caserid, modelrun, processed_flag)
#                                 VALUES (%s, %s, %s, %s, %s, 'N')
#                                 ON CONFLICT DO NOTHING
#                             """, (
#                                 iterationid, iterationtranid,
#                                 final_storeid, caserid,
#                                 datetime.now()
#                             ))

#                             # Insert product detection with S3 paths
#                             cur.execute("""
#                                 INSERT INTO orgi.coolermetricstransaction
#                                 (iterationid, iterationtranid, shelfnumber,
#                                  productsequenceno, productclassid,
#                                  x1, x2, y1, y2, confidence, imagefilename,
#                                  s3path_actual_file, s3path_annotated_file)
#                                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
#                             """, (
#                                 iterationid, iterationtranid,
#                                 shelf_id, productsequenceno,
#                                 sku["class_id"],
#                                 x1, x2, y1, y2,
#                                 sku["conf"],
#                                 filename,           # imagefilename
#                                 s3_key,            # s3path_actual_file (original)
#                                 s3path_annotated   # s3path_annotated_file (segmented)
#                             ))
#                             productsequenceno += 1

#                     conn.commit()
#                     total_processed += 1
#                     total_products += len(final_skus)
#                     logger.info(
#                         f"✓ Processed {filename}: store={final_storeid}, shelf={shelf_index}, "
#                         f"products={len(final_skus)} (fronts={len(front_skus)}, caps={len(cap_detections)})"
#                     )

#                 except Exception as e:
#                     logger.error(f"Error processing image {filename}: {e}")
#                     conn.rollback()

#         logger.info("=" * 60)
#         logger.info(f"VISICOOLER ANALYSIS SUMMARY:")
#         logger.info(f"  Images processed: {total_processed}")
#         logger.info(f"  Total products detected: {total_products}")
#         logger.info(f"  Iteration ID: {iterationid}")
#         logger.info("=" * 60)

#         return []  # Return empty list (no longer used)

#     except Exception as e:
#         logger.error(f"Fatal visicooler error: {e}")
#         raise


# import os
# import cv2
# from ultralytics import YOLO
# import logging
# from app.db_handler import initialize_db_connection, close_db_connection, get_classtext
# from app.config_loader import load_config
# from app.s3_handler import S3Handler
# from datetime import datetime
# import re
# from collections import defaultdict

# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)


# def check_visibilitydetails_schema(cur):
#     """Check if visibilitydetails table exists and has correct schema (stub)"""
#     return True


# def upload_to_visibilitydetails(conn, cur, records, cyclecountid):
#     """Upload visicooler records to orgi.visibilitydetails (stub - not currently used)"""
#     pass


# def should_ignore_class(cls_id: int, class_names: dict) -> bool:
#     """Filter out unwanted detections"""
#     name = class_names.get(cls_id, "").lower()
    
#     # Remove false negatives - bottles that don't exist in your inventory
#     false_negative_keywords = [
#         "1500ml",  # You mentioned these don't exist
#         "visicooler", "cooler"  # Not products
#     ]
    
#     return any(keyword in name for keyword in false_negative_keywords)


# def extract_brand_from_name(name: str) -> str:
#     """
#     Extract brand name from product/cap name.
#     Examples:
#         "Sprite Cap" -> "sprite"
#         "Sprite 250ml PET" -> "sprite"
#         "Coca-Cola Zero 250ml Glass" -> "coca-cola zero"
#         "Kinley Soda Cap" -> "kinley soda"
#     """
#     name_lower = name.lower().strip()
    
#     # Remove size/packaging info
#     name_lower = re.sub(r'\d+ml|\d+l|pet|glass|bottle|can|cap', '', name_lower)
#     name_lower = name_lower.strip()
    
#     # Handle multi-word brands
#     if "coca-cola zero" in name_lower or "coca cola zero" in name_lower:
#         return "coca-cola zero"
#     if "coca-cola" in name_lower or "coca cola" in name_lower:
#         return "coca-cola"
#     if "mountain dew" in name_lower:
#         return "mountain dew"
#     if "thums up" in name_lower:
#         return "thums up"
#     if "kinley soda" in name_lower:
#         return "kinley soda"
#     if "kinley water" in name_lower:
#         return "kinley water"
    
#     # Single-word brands - take first word
#     words = name_lower.split()
#     return words[0] if words else ""


# def calculate_2d_distance(cap, sku):
#     """
#     Calculate weighted 2D distance between cap and SKU.
#     Horizontal alignment is MORE important than vertical.
#     """
#     # Horizontal distance (X-axis)
#     cap_center_x = cap.get("center_x", 0)
#     sku_center_x = sku.get("center_x", 0)
#     dx = abs(cap_center_x - sku_center_x)
    
#     # Vertical distance (Y-axis)
#     cap_center_y = cap["center_y"]
#     sku_center_y = sku["center_y"]
#     dy = abs(cap_center_y - sku_center_y)
    
#     # Weight horizontal distance MORE (caps are directly above bottles)
#     # If bottles are side-by-side, horizontal alignment is critical
#     weighted_distance = (dx * 2.0) + (dy * 1.0)
    
#     return weighted_distance


# def match_cap_to_sku(cap, front_skus, shelf_class_names):
#     """
#     Match a cap to its corresponding front SKU using:
#     1. Brand matching (priority)
#     2. 2D proximity (weighted)
#     """
#     cap_name = shelf_class_names.get(cap.get("class_id", -1), "")
#     cap_brand = extract_brand_from_name(cap_name)
    
#     logger.debug(f"Matching cap: {cap_name} (brand: {cap_brand})")
    
#     # Find SKUs with matching brand
#     brand_matches = []
#     for sku in front_skus:
#         sku_brand = extract_brand_from_name(sku["name"])
#         if cap_brand and sku_brand and cap_brand == sku_brand:
#             brand_matches.append(sku)
#             logger.debug(f"  Brand match: {sku['name']}")
    
#     # If brand matches exist, choose closest one
#     if brand_matches:
#         best_match = min(brand_matches, key=lambda s: calculate_2d_distance(cap, s))
#         logger.info(f"✓ Cap '{cap_name}' → SKU '{best_match['name']}' (brand match)")
#         return best_match
    
#     # Fallback: No brand match, use closest SKU by 2D distance
#     if front_skus:
#         best_match = min(front_skus, key=lambda s: calculate_2d_distance(cap, s))
#         distance = calculate_2d_distance(cap, best_match)
#         logger.warning(
#             f"⚠ Cap '{cap_name}' → SKU '{best_match['name']}' "
#             f"(no brand match, distance={distance:.1f})"
#         )
#         return best_match
    
#     return None


# def run_visicooler_analysis(image_paths, config, s3_handler, conn, cur, output_folder_path, cyclecountid):
#     try:
#         # Model declarations
#         shelf_model_path = config['visicooler_config']['caps_model_path']
#         sku_model_path = config['visicooler_config']['sku_model_path']
#         annotation_model_path = config['visicooler_config']['model_path']
#         conf_threshold = config['visicooler_config']['conf_threshold']

#         shelf_model = YOLO(shelf_model_path)
#         sku_model = YOLO(sku_model_path)
#         annotation_model = YOLO(annotation_model_path)

#         sku_class_names = sku_model.names
#         shelf_class_names = shelf_model.names

#         def _norm_storeid(sid):
#             if sid is None:
#                 return None
#             if isinstance(sid, str):
#                 s = sid.strip()
#                 if s.isdigit():
#                     return int(s)
#                 return s
#             return sid

#         def _get_canonical_storeid(filename, orig_storeid):
#             canonical = orig_storeid
#             try:
#                 cur.execute("""
#                     SELECT storeid
#                     FROM orgi.batchtransactionvisibilityitems
#                     WHERE imagefilename = %s
#                     LIMIT 1
#                 """, (filename,))
#                 row = cur.fetchone()
#                 if row and row[0] is not None:
#                     canonical = row[0]
#             except Exception:
#                 pass
#             return canonical

#         def normalize_subcat(val):
#             if val is None:
#                 return None
#             s = str(val).strip().replace(',', '')
#             if s.endswith('.0'):
#                 s = s[:-2]
#             m = re.search(r'(\d+)', s)
#             return int(m.group(1)) if m else None

#         # Group images by store
#         store_images = {}
#         for row in image_paths:
#             fileseqid, storename, filename, local_path, s3_key, orig_storeid, subcategory_id = row
#             canonical_storeid = _get_canonical_storeid(filename, orig_storeid)
#             sid = _norm_storeid(canonical_storeid)
#             subcat_norm = normalize_subcat(subcategory_id)
#             store_images.setdefault(sid, []).append(
#                 (fileseqid, storename, filename, local_path, s3_key, canonical_storeid, subcat_norm)
#             )

#         logger.info("Processing subcategory 605 only")

#         cur.execute("SELECT COALESCE(MAX(iterationid), 0) FROM orgi.coolermetricsmaster")
#         iterationid = cur.fetchone()[0] + 1

#         total_processed = 0
#         total_products = 0
#         total_brand_matches = 0
#         total_proximity_matches = 0

#         for sid, rows in store_images.items():
#             iterationtranid = (
#                 int(rows[0][0])
#                 if rows[0][0] and str(rows[0][0]).isdigit()
#                 else int(datetime.now().timestamp() * 1000) % 100000000
#             )
            
#             for stored_row in rows:
#                 fileseqid, storename, filename, local_path, s3_key, final_storeid, subcat_norm = stored_row

#                 if subcat_norm != 605:
#                     continue

#                 try:
#                     image = cv2.imread(local_path)
#                     if image is None:
#                         logger.warning(f"Failed to read image: {filename}")
#                         continue

#                     image_height, image_width = image.shape[:2]
#                     os.makedirs(output_folder_path, exist_ok=True)

#                     shelf_605_rows = [r for r in store_images[sid] if r[6] == 605]
#                     shelf_index = shelf_605_rows.index(stored_row) + 1

#                     # Get caserid
#                     caserid = 0
#                     try:
#                         cur.execute("""
#                             SELECT cooler FROM orgi.storemaster
#                             WHERE storeid = %s LIMIT 1
#                         """, (final_storeid,))
#                         row = cur.fetchone()
#                         if row and row[0]:
#                             m = re.search(r'(\d+)', row[0])
#                             if m:
#                                 cur.execute("""
#                                     SELECT caserid FROM orgi.puritymapping
#                                     WHERE casername ILIKE %s LIMIT 1
#                                 """, (f"%{m.group(1)}%",))
#                                 prow = cur.fetchone()
#                                 if prow:
#                                     caserid = prow[0]
#                     except Exception as e:
#                         logger.warning(f"Failed to get caserid: {e}")

#                     # ========================================
#                     # FRONT SKU DETECTION (with center_x calculation)
#                     # ========================================
#                     sku_results = sku_model(local_path, conf=conf_threshold)
#                     front_skus = []

#                     for result in sku_results:
#                         if not result.orig_shape:
#                             continue
#                         sw = image_width / result.orig_shape[1]
#                         sh = image_height / result.orig_shape[0]

#                         for box in result.boxes:
#                             cls_id = int(box.cls[0])
                            
#                             # Filter false negatives
#                             if should_ignore_class(cls_id, sku_class_names):
#                                 logger.debug(f"Filtered out: {sku_class_names[cls_id]}")
#                                 continue

#                             x1, y1, x2, y2 = box.xyxy[0]
#                             x1_px, y1_px = int(x1 * sw), int(y1 * sh)
#                             x2_px, y2_px = int(x2 * sw), int(y2 * sh)
                            
#                             front_skus.append({
#                                 "class_id": cls_id,
#                                 "name": sku_class_names[cls_id],
#                                 "conf": float(box.conf[0]),
#                                 "bbox": (x1_px, y1_px, x2_px, y2_px),
#                                 "center_x": (x1_px + x2_px) // 2,  # ADDED
#                                 "center_y": (y1_px + y2_px) // 2
#                             })

#                     # ========================================
#                     # CAP DETECTION (with center_x calculation)
#                     # ========================================
#                     cap_results = shelf_model(local_path, conf=conf_threshold)
#                     cap_detections = []

#                     for result in cap_results:
#                         if not result.orig_shape:
#                             continue
#                         sw = image_width / result.orig_shape[1]
#                         sh = image_height / result.orig_shape[0]

#                         for box in result.boxes:
#                             cls_id = int(box.cls[0])
#                             name = shelf_class_names.get(cls_id, "").lower()
#                             if "cap" not in name:
#                                 continue

#                             x1, y1, x2, y2 = box.xyxy[0]
#                             x1_px, y1_px = int(x1 * sw), int(y1 * sh)
#                             x2_px, y2_px = int(x2 * sw), int(y2 * sh)
                            
#                             cap_detections.append({
#                                 "class_id": cls_id,
#                                 "conf": float(box.conf[0]),
#                                 "center_x": (x1_px + x2_px) // 2,  # ADDED
#                                 "center_y": (y1_px + y2_px) // 2
#                             })

#                     # ========================================
#                     # IMPROVED CAP → SKU MATCHING
#                     # ========================================
#                     inferred_skus = []
#                     for cap in cap_detections:
#                         matched_sku = match_cap_to_sku(cap, front_skus, shelf_class_names)
#                         if matched_sku:
#                             inferred_skus.append({
#                                 **matched_sku,
#                                 "conf": cap["conf"],
#                                 "inferred": True
#                             })
                            
#                             # Track matching method
#                             cap_brand = extract_brand_from_name(
#                                 shelf_class_names.get(cap["class_id"], "")
#                             )
#                             sku_brand = extract_brand_from_name(matched_sku["name"])
#                             if cap_brand == sku_brand:
#                                 total_brand_matches += 1
#                             else:
#                                 total_proximity_matches += 1
                    
#                     # Choose dominant interpretation
#                     if len(inferred_skus) > len(front_skus):
#                         final_skus = inferred_skus
#                     else:
#                         final_skus = front_skus
                    
#                     shelf_sku_map = {shelf_index: final_skus}

#                     # ========================================
#                     # ANNOTATED IMAGE
#                     # ========================================
#                     s3path_annotated = f"ModelResults/Visicooler_{cyclecountid}/segmented_{filename}"
                    
#                     try:
#                         annotation_results = annotation_model(local_path, conf=conf_threshold)
#                         rendered = annotation_results[0].plot()
#                         out = os.path.join(output_folder_path, f"segmented_{filename}")
#                         cv2.imwrite(out, rendered)
#                         s3_handler.upload_file_to_s3(out, s3path_annotated)
#                     except Exception as e:
#                         logger.warning(f"Annotation failed: {e}")

#                     # ========================================
#                     # DATABASE INSERTS
#                     # ========================================
#                     for shelf_id, sku_list in shelf_sku_map.items():
#                         productsequenceno = 1
#                         for sku in sku_list:
#                             x1, y1, x2, y2 = sku["bbox"]

#                             cur.execute("""
#                                 INSERT INTO orgi.coolermetricsmaster
#                                 (iterationid, iterationtranid, storeid, caserid, modelrun, processed_flag)
#                                 VALUES (%s, %s, %s, %s, %s, 'N')
#                                 ON CONFLICT DO NOTHING
#                             """, (
#                                 iterationid, iterationtranid,
#                                 final_storeid, caserid,
#                                 datetime.now()
#                             ))

#                             cur.execute("""
#                                 INSERT INTO orgi.coolermetricstransaction
#                                 (iterationid, iterationtranid, shelfnumber,
#                                  productsequenceno, productclassid,
#                                  x1, x2, y1, y2, confidence, imagefilename,
#                                  s3path_actual_file, s3path_annotated_file)
#                                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
#                             """, (
#                                 iterationid, iterationtranid,
#                                 shelf_id, productsequenceno,
#                                 sku["class_id"],
#                                 x1, x2, y1, y2,
#                                 sku["conf"],
#                                 filename,
#                                 s3_key,
#                                 s3path_annotated
#                             ))
#                             productsequenceno += 1

#                     conn.commit()
#                     total_processed += 1
#                     total_products += len(final_skus)
                    
#                     logger.info(
#                         f"✓ {filename}: store={final_storeid}, shelf={shelf_index}, "
#                         f"products={len(final_skus)} "
#                         f"(fronts={len(front_skus)}, caps={len(cap_detections)}, "
#                         f"inferred={len(inferred_skus)})"
#                     )

#                 except Exception as e:
#                     logger.error(f"Error processing {filename}: {e}")
#                     conn.rollback()

#         logger.info("=" * 70)
#         logger.info(f"VISICOOLER ANALYSIS SUMMARY:")
#         logger.info(f"  Images processed: {total_processed}")
#         logger.info(f"  Total products: {total_products}")
#         logger.info(f"  Brand-matched caps: {total_brand_matches}")
#         logger.info(f"  Proximity-matched caps: {total_proximity_matches}")
#         logger.info(f"  Iteration ID: {iterationid}")
#         logger.info("=" * 70)

#         return []

#     except Exception as e:
#         logger.error(f"Fatal error: {e}")
#         raise


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
    
    # Remove false negatives - bottles that don't exist in your inventory
    false_negative_keywords = [
        "1500ml",  # You mentioned these don't exist
        "visicooler", "cooler"  # Not products
    ]
    
    return any(keyword in name for keyword in false_negative_keywords)


def extract_brand_from_name(name: str) -> str:
    """
    Extract brand name from product/cap name.
    Examples:
        "Sprite Cap" -> "sprite"
        "Sprite 250ml PET" -> "sprite"
        "Coca-Cola Zero 250ml Glass" -> "coca-cola zero"
        "Coke Zero" -> "coca-cola zero"
        "Coke Cap" -> "coca-cola"
        "Kinley Soda Cap" -> "kinley soda"
    """
    name_lower = name.lower().strip()
    
    # Remove size/packaging info
    name_lower = re.sub(r'\d+ml|\d+l|pet|glass|bottle|can|cap', '', name_lower)
    name_lower = name_lower.strip()
    
    # Handle multi-word brands and aliases
    # Check specific variants first, then general brands
    if "coca-cola zero" in name_lower or "coca cola zero" in name_lower or "coke zero" in name_lower:
        return "coca-cola"
    if "coca-cola" in name_lower or "coca cola" in name_lower or "coke" in name_lower:
        return "coca-cola"
    if "mountain dew" in name_lower:
        return "mountain dew"
    if "thums up" in name_lower or "thumbs up" in name_lower:
        return "thums up"
    if "kinley soda" in name_lower or "kinley club soda" in name_lower:
        return "kinley soda"
    if "kinley water" in name_lower or "kinley mineral water" in name_lower:
        return "kinley water"
    # Generic Kinley (if no specific type mentioned)
    if "kinley" in name_lower:
        return "kinley"
    
    # Single-word brands - take first word
    words = name_lower.split()
    return words[0] if words else ""


def calculate_2d_distance(cap, sku):
    """
    Calculate weighted 2D distance between cap and SKU.
    Horizontal alignment is MORE important than vertical.
    """
    # Horizontal distance (X-axis)
    cap_center_x = cap.get("center_x", 0)
    sku_center_x = sku.get("center_x", 0)
    dx = abs(cap_center_x - sku_center_x)
    
    # Vertical distance (Y-axis)
    cap_center_y = cap["center_y"]
    sku_center_y = sku["center_y"]
    dy = abs(cap_center_y - sku_center_y)
    
    # Weight horizontal distance MORE (caps are directly above bottles)
    # If bottles are side-by-side, horizontal alignment is critical
    weighted_distance = (dx * 2.0) + (dy * 1.0)
    
    return weighted_distance


def match_caps_to_skus_unique(cap_detections, front_skus, shelf_class_names):
    """
    Match caps to SKUs ensuring each SKU is matched AT MOST ONCE.
    This prevents duplicate counting.
    
    Returns:
        list: Matched SKUs with inferred confidence and match metadata
    """
    if not front_skus or not cap_detections:
        return []
    
    # Create copies to avoid modifying originals
    available_skus = front_skus.copy()
    matched_skus = []
    
    # Sort caps by confidence (match high-confidence caps first)
    sorted_caps = sorted(cap_detections, key=lambda c: c["conf"], reverse=True)
    
    # Maximum allowed distance in pixels (adjust based on your image resolution)
    # If cooler images are ~1920x1080, 300px is reasonable
    # If images are smaller, reduce this proportionally
    MAX_DISTANCE = 300
    
    for cap in sorted_caps:
        if not available_skus:
            logger.warning(
                f"No more SKUs available for matching. "
                f"Remaining caps: {len(sorted_caps) - len(matched_skus)}"
            )
            break
            
        cap_name = shelf_class_names.get(cap.get("class_id", -1), "")
        cap_brand = extract_brand_from_name(cap_name)
        
        logger.debug(f"Matching cap: {cap_name} (brand: {cap_brand})")
        
        # Find brand matches among AVAILABLE SKUs only
        brand_matches = []
        for sku in available_skus:
            sku_brand = extract_brand_from_name(sku["name"])
            if cap_brand and sku_brand and cap_brand == sku_brand:
                brand_matches.append(sku)
                logger.debug(f"  Brand match available: {sku['name']}")
        
        # Choose closest from brand matches, or fall back to all available SKUs
        candidates = brand_matches if brand_matches else available_skus
        best_match = min(candidates, key=lambda s: calculate_2d_distance(cap, s))
        distance = calculate_2d_distance(cap, best_match)
        
        # Only match if within reasonable distance threshold
        if distance > MAX_DISTANCE:
            logger.warning(
                f"⚠ Cap '{cap_name}' too far from nearest SKU '{best_match['name']}' "
                f"(distance={distance:.1f}px > {MAX_DISTANCE}px threshold) - SKIPPING"
            )
            continue
        
        # Determine match type
        match_type = "brand" if best_match in brand_matches else "proximity"
        
        # Create matched SKU with metadata
        matched_sku = {
            **best_match,
            "conf": cap["conf"],  # Use cap's confidence
            "inferred": True,
            "match_distance": distance,
            "match_type": match_type
        }
        matched_skus.append(matched_sku)
        
        # CRITICAL: Remove from available pool to prevent duplicate matching
        available_skus.remove(best_match)
        
        logger.info(
            f"✓ Cap '{cap_name}' → SKU '{best_match['name']}' "
            f"({match_type} match, dist={distance:.1f}px)"
        )
    
    # Log unmatched caps
    unmatched_count = len(cap_detections) - len(matched_skus)
    if unmatched_count > 0:
        logger.warning(
            f"⚠ {unmatched_count} caps could not be matched "
            f"(either too far or no SKUs available)"
        )
    
    return matched_skus


def merge_detections(front_skus, inferred_skus, confidence_threshold=0.5):
    """
    Intelligently merge front SKU detections with cap-inferred SKUs.
    
    Strategy:
    1. Start with all front-detected SKUs (ground truth)
    2. Add inferred SKUs only if they represent NEW products not already detected
    3. Avoid double-counting the same product
    
    Args:
        front_skus: SKUs detected directly from bottle bodies
        inferred_skus: SKUs inferred from cap detections
        confidence_threshold: Minimum confidence to trust inferred SKUs
    
    Returns:
        list: Final deduplicated SKU list
    """
    final_skus = front_skus.copy()
    
    # Track which brands/products are already represented
    existing_products = set()
    for sku in front_skus:
        brand = extract_brand_from_name(sku["name"])
        # Create a position-aware key to allow same brand in different locations
        position_key = (brand, sku["center_x"] // 100)  # 100px grid
        existing_products.add(position_key)
    
    # Add inferred SKUs only if they're genuinely new
    added_count = 0
    for inferred in inferred_skus:
        # Check confidence threshold
        if inferred["conf"] < confidence_threshold:
            logger.debug(
                f"Skipping low-confidence inferred SKU: {inferred['name']} "
                f"(conf={inferred['conf']:.2f})"
            )
            continue
        
        # Check if this product is already represented
        brand = extract_brand_from_name(inferred["name"])
        position_key = (brand, inferred["center_x"] // 100)
        
        if position_key not in existing_products:
            final_skus.append(inferred)
            existing_products.add(position_key)
            added_count += 1
            logger.info(
                f"➕ Added inferred SKU: {inferred['name']} "
                f"(not in front detections, conf={inferred['conf']:.2f})"
            )
    
    logger.info(
        f"Merge result: {len(front_skus)} front + {added_count} inferred = "
        f"{len(final_skus)} total SKUs"
    )
    
    return final_skus


def run_visicooler_analysis(image_paths, config, s3_handler, conn, cur, output_folder_path, cyclecountid):
    try:
        # Model declarations
        shelf_model_path = config['visicooler_config']['caps_model_path']
        sku_model_path = config['visicooler_config']['sku_model_path']
        annotation_model_path = config['visicooler_config']['model_path']
        conf_threshold = config['visicooler_config']['conf_threshold']

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

        cur.execute("SELECT COALESCE(MAX(iterationid), 0) FROM orgi.coolermetricsmaster")
        iterationid = cur.fetchone()[0] + 1

        # Statistics tracking
        total_processed = 0
        total_products = 0
        total_front_detections = 0
        total_cap_detections = 0
        total_brand_matches = 0
        total_proximity_matches = 0
        total_caps_unmatched = 0

        for sid, rows in store_images.items():
            iterationtranid = (
                int(rows[0][0])
                if rows[0][0] and str(rows[0][0]).isdigit()
                else int(datetime.now().timestamp() * 1000) % 100000000
            )
            
            for stored_row in rows:
                fileseqid, storename, filename, local_path, s3_key, final_storeid, subcat_norm = stored_row

                if subcat_norm != 605:
                    continue

                try:
                    image = cv2.imread(local_path)
                    if image is None:
                        logger.warning(f"Failed to read image: {filename}")
                        continue

                    image_height, image_width = image.shape[:2]
                    os.makedirs(output_folder_path, exist_ok=True)

                    shelf_605_rows = [r for r in store_images[sid] if r[6] == 605]
                    shelf_index = shelf_605_rows.index(stored_row) + 1

                    # Get caserid
                    caserid = 0
                    try:
                        cur.execute("""
                            SELECT cooler FROM orgi.storemaster
                            WHERE storeid = %s LIMIT 1
                        """, (final_storeid,))
                        row = cur.fetchone()
                        if row and row[0]:
                            m = re.search(r'(\d+)', row[0])
                            if m:
                                cur.execute("""
                                    SELECT caserid FROM orgi.puritymapping
                                    WHERE casername ILIKE %s LIMIT 1
                                """, (f"%{m.group(1)}%",))
                                prow = cur.fetchone()
                                if prow:
                                    caserid = prow[0]
                    except Exception as e:
                        logger.warning(f"Failed to get caserid: {e}")

                    # ========================================
                    # FRONT SKU DETECTION (with center_x calculation)
                    # ========================================
                    sku_results = sku_model(local_path, conf=conf_threshold)
                    front_skus = []

                    for result in sku_results:
                        if not result.orig_shape:
                            continue
                        sw = image_width / result.orig_shape[1]
                        sh = image_height / result.orig_shape[0]

                        for box in result.boxes:
                            cls_id = int(box.cls[0])
                            
                            # Filter false negatives
                            if should_ignore_class(cls_id, sku_class_names):
                                logger.debug(f"Filtered out: {sku_class_names[cls_id]}")
                                continue

                            x1, y1, x2, y2 = box.xyxy[0]
                            x1_px, y1_px = int(x1 * sw), int(y1 * sh)
                            x2_px, y2_px = int(x2 * sw), int(y2 * sh)
                            
                            front_skus.append({
                                "class_id": cls_id,
                                "name": sku_class_names[cls_id],
                                "conf": float(box.conf[0]),
                                "bbox": (x1_px, y1_px, x2_px, y2_px),
                                "center_x": (x1_px + x2_px) // 2,
                                "center_y": (y1_px + y2_px) // 2
                            })

                    # ========================================
                    # CAP DETECTION (with center_x calculation)
                    # ========================================
                    cap_results = shelf_model(local_path, conf=conf_threshold)
                    cap_detections = []

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
                            
                            cap_detections.append({
                                "class_id": cls_id,
                                "conf": float(box.conf[0]),
                                "center_x": (x1_px + x2_px) // 2,
                                "center_y": (y1_px + y2_px) // 2
                            })

                    # ========================================
                    # IMPROVED CAP → SKU MATCHING (ONE-TO-ONE)
                    # ========================================
                    logger.info(
                        f"Detection counts for {filename}: "
                        f"Front SKUs={len(front_skus)}, Caps={len(cap_detections)}"
                    )
                    
                    inferred_skus = match_caps_to_skus_unique(
                        cap_detections, front_skus, shelf_class_names
                    )
                    
                    # Update statistics
                    total_front_detections += len(front_skus)
                    total_cap_detections += len(cap_detections)
                    total_brand_matches += sum(
                        1 for s in inferred_skus if s.get("match_type") == "brand"
                    )
                    total_proximity_matches += sum(
                        1 for s in inferred_skus if s.get("match_type") == "proximity"
                    )
                    total_caps_unmatched += len(cap_detections) - len(inferred_skus)
                    
                    # ========================================
                    # MERGE FRONT + INFERRED DETECTIONS
                    # ========================================
                    final_skus = merge_detections(
                        front_skus, 
                        inferred_skus, 
                        confidence_threshold=0.5
                    )
                    
                    shelf_sku_map = {shelf_index: final_skus}

                    # ========================================
                    # ANNOTATED IMAGE
                    # ========================================
                    s3path_annotated = f"ModelResults/Visicooler_{cyclecountid}/segmented_{filename}"
                    
                    try:
                        annotation_results = annotation_model(local_path, conf=conf_threshold)
                        rendered = annotation_results[0].plot()
                        out = os.path.join(output_folder_path, f"segmented_{filename}")
                        cv2.imwrite(out, rendered)
                        s3_handler.upload_file_to_s3(out, s3path_annotated)
                    except Exception as e:
                        logger.warning(f"Annotation failed: {e}")

                    # ========================================
                    # DATABASE INSERTS
                    # ========================================
                    for shelf_id, sku_list in shelf_sku_map.items():
                        productsequenceno = 1
                        for sku in sku_list:
                            x1, y1, x2, y2 = sku["bbox"]

                            cur.execute("""
                                INSERT INTO orgi.coolermetricsmaster
                                (iterationid, iterationtranid, storeid, caserid, modelrun, processed_flag)
                                VALUES (%s, %s, %s, %s, %s, 'N')
                                ON CONFLICT DO NOTHING
                            """, (
                                iterationid, iterationtranid,
                                final_storeid, caserid,
                                datetime.now()
                            ))

                            cur.execute("""
                                INSERT INTO orgi.coolermetricstransaction
                                (iterationid, iterationtranid, shelfnumber,
                                 productsequenceno, productclassid,
                                 x1, x2, y1, y2, confidence, imagefilename,
                                 s3path_actual_file, s3path_annotated_file)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                iterationid, iterationtranid,
                                shelf_id, productsequenceno,
                                sku["class_id"],
                                x1, x2, y1, y2,
                                sku["conf"],
                                filename,
                                s3_key,
                                s3path_annotated
                            ))
                            productsequenceno += 1

                    conn.commit()
                    total_processed += 1
                    total_products += len(final_skus)
                    
                    logger.info(
                        f"✓ {filename}: store={final_storeid}, shelf={shelf_index}, "
                        f"FINAL_PRODUCTS={len(final_skus)} "
                        f"(fronts={len(front_skus)}, caps={len(cap_detections)}, "
                        f"matched={len(inferred_skus)}, added={len(final_skus)-len(front_skus)})"
                    )

                except Exception as e:
                    logger.error(f"Error processing {filename}: {e}")
                    conn.rollback()

        # ========================================
        # FINAL SUMMARY REPORT
        # ========================================
        logger.info("=" * 70)
        logger.info(f"VISICOOLER ANALYSIS SUMMARY:")
        logger.info(f"  Images processed: {total_processed}")
        logger.info(f"  Total products reported: {total_products}")
        logger.info(f"  ")
        logger.info(f"  Detection breakdown:")
        logger.info(f"    - Front SKUs detected: {total_front_detections}")
        logger.info(f"    - Caps detected: {total_cap_detections}")
        logger.info(f"    - Caps successfully matched: {total_brand_matches + total_proximity_matches}")
        logger.info(f"    - Caps unmatched: {total_caps_unmatched}")
        logger.info(f"  ")
        logger.info(f"  Matching methods:")
        logger.info(f"    - Brand-matched: {total_brand_matches}")
        logger.info(f"    - Proximity-matched: {total_proximity_matches}")
        logger.info(f"  ")
        logger.info(f"  Iteration ID: {iterationid}")
        logger.info("=" * 70)

        return []

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise