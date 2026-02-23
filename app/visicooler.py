# # import os
# # import cv2
# # from ultralytics import YOLO
# # import logging
# # from app.db_handler import close_db_connection, get_classtext
# # from app.config_loader import load_config
# # from app.s3_handler import S3Handler
# # from app.db_retry import retry_on_network_error, verify_connection
# # from datetime import datetime
# # import re
# # from collections import defaultdict
# # import pg8000.dbapi as pg

# # logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# # logger = logging.getLogger(__name__)


# # def check_visibilitydetails_schema(cur):
# #     # Check if visibilitydetails table exists and has correct schema (stub)
# #     return True


# # def upload_to_visibilitydetails(conn, cur, records, cyclecountid):
# #     # Upload visicooler records to orgi.visibilitydetails (stub - not currently used)
# #     pass


# # def should_ignore_class(cls_id: int, class_names: dict) -> bool:
# #     # Filter out unwanted detections
# #     name = class_names.get(cls_id, "").lower()
# #     false_negative_keywords = [" 700ml", "750ml","visicooler", "cooler"]
# #     return any(keyword in name for keyword in false_negative_keywords)


# # def extract_brand_from_name(name: str) -> str:
# #     # Extract brand from product name
# #     name_lower = name.lower().strip()
    
# #     # Remove size and package type info
# #     name_lower = re.sub(r'\d+ml|\d+l|pet|glass|bottle|can|cap', '', name_lower)
# #     name_lower = name_lower.strip()
    
# #     # Check for specific brands
# #     if "coca-cola zero" in name_lower or "coca cola zero" in name_lower:
# #         return "coca-cola zero"
# #     if "coca-cola" in name_lower or "coca cola" in name_lower or "coke" in name_lower:
# #         return "coca-cola"
# #     if "mountain dew" in name_lower:
# #         return "mountain dew"
# #     if "kinley soda" in name_lower:
# #         return "kinley soda"
# #     if "kinley water" in name_lower:
# #         return "kinley water"
# #     if "sprite" in name_lower:
# #         return "sprite"
# #     if "fanta" in name_lower:
# #         return "fanta"
# #     if "thums up" in name_lower or "thumbs up" in name_lower:
# #         return "thums up"
# #     if "limca" in name_lower:
# #         return "limca"
# #     if "maaza" in name_lower:
# #         return "maaza"
# #     if "pepsi" in name_lower:
# #         return "pepsi"
# #     if "mirinda" in name_lower:
# #         return "mirinda"
# #     if "7up" in name_lower or "7 up" in name_lower:
# #         return "7up"
# #     if "slice" in name_lower:
# #         return "slice"
# #     if "sting" in name_lower:
# #         return "sting"
# #     if "aquafina" in name_lower:
# #         return "aquafina"
# #     if "other" in name_lower:
# #         return "other"
    
# #     # Default to first word if no match
# #     words = name_lower.split()
# #     return words[0] if words else ""


# # @retry_on_network_error(max_retries=3, delay=5)
# # def insert_cap_predictions(cur, cap_records):
# #     # Insert cap predictions with retry on network errors
# #     if not cap_records:
# #         return
    
# #     # Check if connection is still alive
# #     if not verify_connection(cur):
# #         raise Exception("Database connection lost before cap insert")
    
# #     insert_query = """
# #     INSERT INTO temp.cap_prediction_temp
# #     (store_id, image_file_name, iteration_id, cap_class_id, x1, x2, y1, y2, prod_class_id, shelfnumber, s3path_annotated_file)
# #     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
# #     """
    
# #     try:
# #         cur.executemany(insert_query, cap_records)
# #         logger.info(f"Inserted {len(cap_records)} cap predictions")
# #     except Exception as e:
# #         logger.error(f"Failed to insert cap predictions: {type(e).__name__}: {e}")
# #         raise


# # @retry_on_network_error(max_retries=3, delay=5)
# # def insert_sku_predictions(cur, sku_records):
# #     # Insert SKU predictions with retry on network errors
# #     if not sku_records:
# #         return
    
# #     # Check if connection is still alive
# #     if not verify_connection(cur):
# #         raise Exception("Database connection lost before SKU insert")
    
# #     insert_query = """
# #     INSERT INTO temp.sku_prediction_temp
# #     (store_id, image_file_name, iteration_id, prod_class_id, x1, x2, y1, y2, shelfnumber, brand_name, s3path_annotated_file)
# #     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
# #     """
    
# #     try:
# #         cur.executemany(insert_query, sku_records)
# #         logger.info(f"Inserted {len(sku_records)} SKU predictions")
# #     except Exception as e:
# #         logger.error(f"Failed to insert SKU predictions: {type(e).__name__}: {e}")
# #         raise


# # def reconnect_database(config):
# #     # Reconnect to database after connection loss
# #     try:
# #         db_config = config['db_config']
# #         conn = pg.connect(
# #             host=db_config['host'],
# #             port=db_config['port'],
# #             database=db_config['database'],
# #             user=db_config['user'],
# #             password=db_config['password'],
# #             timeout=30
# #         )
# #         cur = conn.cursor()
# #         logger.info("Database reconnected successfully")
# #         return conn, cur
# #     except Exception as e:
# #         logger.error(f"Failed to reconnect to database: {e}")
# #         raise


# # def run_visicooler_analysis(image_paths, config, s3_handler, conn, cur, 
# #                             output_folder_path, cyclecountid, iterationid=None):

# #     try:
# #         # Load model paths from config
# #         shelf_model_path = config['visicooler_config']['caps_model_path']
# #         sku_model_path = config['visicooler_config']['sku_model_path']
# #         annotation_model_path = config['visicooler_config']['model_path']
        
# #         # Get confidence thresholds
# #         cap_conf_threshold = config['visicooler_config'].get('cap_conf_threshold', 0.1)
# #         sku_conf_threshold = config['visicooler_config'].get('sku_conf_threshold', 0.35)
# #         annotation_conf_threshold = config['visicooler_config'].get('conf_threshold', 0.12)

# #         # Load YOLO models
# #         shelf_model = YOLO(shelf_model_path)
# #         sku_model = YOLO(sku_model_path)
# #         annotation_model = YOLO(annotation_model_path)

# #         # Get class names from models
# #         sku_class_names = sku_model.names
# #         shelf_class_names = shelf_model.names

# #         def _norm_storeid(sid):
# #             # Normalize store ID format
# #             if sid is None:
# #                 return None
# #             if isinstance(sid, str):
# #                 s = sid.strip()
# #                 if s.isdigit():
# #                     return int(s)
# #                 return s
# #             return sid

# #         def _get_canonical_storeid(filename, orig_storeid):
# #             # Get canonical store ID from database
# #             canonical = orig_storeid
# #             try:
# #                 cur.execute("""
# #                     SELECT storeid
# #                     FROM orgi.batchtransactionvisibilityitems
# #                     WHERE imagefilename = %s
# #                     LIMIT 1
# #                 """, (filename,))
# #                 row = cur.fetchone()
# #                 if row and row[0] is not None:
# #                     canonical = row[0]
# #             except Exception:
# #                 pass
# #             return canonical

# #         def normalize_subcat(val):
# #             # Normalize subcategory ID
# #             if val is None:
# #                 return None
# #             s = str(val).strip().replace(',', '')
# #             if s.endswith('.0'):
# #                 s = s[:-2]
# #             m = re.search(r'(\d+)', s)
# #             return int(m.group(1)) if m else None

# #         # Group images by store
# #         store_images = {}
# #         for row in image_paths:
# #             fileseqid, storename, filename, local_path, s3_key, orig_storeid, subcategory_id = row
# #             canonical_storeid = _get_canonical_storeid(filename, orig_storeid)
# #             sid = _norm_storeid(canonical_storeid)
# #             subcat_norm = normalize_subcat(subcategory_id)
# #             store_images.setdefault(sid, []).append(
# #                 (fileseqid, storename, filename, local_path, s3_key, canonical_storeid, subcat_norm)
# #             )

# #         logger.info("Processing subcategory 605 only")

# #         # Get or generate iteration ID
# #         if iterationid is None:
# #             try:
# #                 cur.execute("SELECT COALESCE(MAX(iterationid), 0) FROM orgi.coolermetricsmaster")
# #                 iterationid = cur.fetchone()[0] + 1
# #                 logger.info(f"Generated new iterationid: {iterationid}")
# #             except Exception as e:
# #                 logger.warning(f"Failed to get iterationid from database: {e}")
# #                 iterationid = 1
# #                 logger.info(f"Using default iterationid: {iterationid}")
# #         else:
# #             logger.info(f"Using provided iterationid: {iterationid}")

# #         # Close database before long processing
# #         try:
# #             if conn is not None and cur is not None:
# #                 close_db_connection(conn, cur)
# #                 logger.info("Database closed before inference (will reopen for insert)")
# #         except Exception as e:
# #             logger.warning(f"Connection already closed or error closing: {e}")
        
# #         conn = None
# #         cur = None

# #         # Initialize counters
# #         total_processed = 0
# #         total_cap_detections = 0
# #         total_sku_detections = 0
        
# #         # Storage for all detections
# #         all_cap_records = []
# #         all_sku_records = []

# #         # Process each store
# #         for sid, rows in store_images.items():
# #             # Get only subcategory 605 images for shelf numbering
# #             shelf_605_images = [r for r in rows if r[6] == 605]
            
# #             # Process each image in the store
# #             for stored_row in rows:
# #                 fileseqid, storename, filename, local_path, s3_key, final_storeid, subcat_norm = stored_row

# #                 # Skip if not subcategory 605
# #                 if subcat_norm != 605:
# #                     continue

# #                 try:
# #                     # Calculate shelf number for this image
# #                     shelf_index = shelf_605_images.index(stored_row) + 1
                    
# #                     # Read image
# #                     image = cv2.imread(local_path)
# #                     if image is None:
# #                         logger.warning(f"Failed to read image: {filename}")
# #                         continue

# #                     image_height, image_width = image.shape[:2]
# #                     os.makedirs(output_folder_path, exist_ok=True)

# #                     # Generate S3 path for annotated image
# #                     s3path_annotated = f"ModelResults/Visicooler_{cyclecountid}/segmented_{filename}"

# #                     # Run SKU detection model
# #                     sku_results = sku_model(local_path, conf=sku_conf_threshold)

# #                     for result in sku_results:
# #                         if not result.orig_shape:
# #                             continue
                        
# #                         # Calculate scaling factors
# #                         sw = image_width / result.orig_shape[1]
# #                         sh = image_height / result.orig_shape[0]

# #                         for box in result.boxes:
# #                             cls_id = int(box.cls[0])
                            
# #                             # Skip unwanted classes
# #                             if should_ignore_class(cls_id, sku_class_names):
# #                                 logger.debug(f"Filtered out: {sku_class_names[cls_id]}")
# #                                 continue

# #                             # Get bounding box coordinates
# #                             x1, y1, x2, y2 = box.xyxy[0]
# #                             x1_px, y1_px = int(x1 * sw), int(y1 * sh)
# #                             x2_px, y2_px = int(x2 * sw), int(y2 * sh)
                            
# #                             # Extract brand name from product name
# #                             product_name = sku_class_names[cls_id]
# #                             brand_name = extract_brand_from_name(product_name)
                            
# #                             # Store detection with shelf number, brand, and s3path_annotated_file
# #                             all_sku_records.append((
# #                                 final_storeid,
# #                                 filename,
# #                                 iterationid,
# #                                 cls_id,
# #                                 x1_px,
# #                                 x2_px,
# #                                 y1_px,
# #                                 y2_px,
# #                                 shelf_index,
# #                                 brand_name,
# #                                 s3path_annotated  # Added s3path_annotated_file
# #                             ))
                            
# #                             total_sku_detections += 1

# #                     # Run cap detection model
# #                     cap_results = shelf_model(local_path, conf=cap_conf_threshold)

# #                     for result in cap_results:
# #                         if not result.orig_shape:
# #                             continue
                        
# #                         # Calculate scaling factors
# #                         sw = image_width / result.orig_shape[1]
# #                         sh = image_height / result.orig_shape[0]

# #                         for box in result.boxes:
# #                             cls_id = int(box.cls[0])
# #                             name = shelf_class_names.get(cls_id, "").lower()
                            
# #                             # Only process cap detections
# #                             if "cap" not in name:
# #                                 continue

# #                             # Get bounding box coordinates
# #                             x1, y1, x2, y2 = box.xyxy[0]
# #                             x1_px, y1_px = int(x1 * sw), int(y1 * sh)
# #                             x2_px, y2_px = int(x2 * sw), int(y2 * sh)
                            
# #                             # Store detection with shelf number and s3path_annotated_file
# #                             all_cap_records.append((
# #                                 final_storeid,
# #                                 filename,
# #                                 iterationid,
# #                                 cls_id,
# #                                 x1_px,
# #                                 x2_px,
# #                                 y1_px,
# #                                 y2_px,
# #                                 None,
# #                                 shelf_index,
# #                                 s3path_annotated  # Added s3path_annotated_file
# #                             ))
                            
# #                             total_cap_detections += 1

# #                     # Generate annotated image for visualization
# #                     try:
# #                         annotation_results = annotation_model(local_path, conf=annotation_conf_threshold)
# #                         rendered = annotation_results[0].plot()
# #                         out = os.path.join(output_folder_path, f"segmented_{filename}")
# #                         cv2.imwrite(out, rendered)
# #                         s3_handler.upload_file_to_s3(out, s3path_annotated)
# #                     except Exception as e:
# #                         logger.warning(f"Annotation failed: {e}")

# #                     total_processed += 1
                    
# #                     logger.info(
# #                         f"Processed {filename}: store={final_storeid}, shelf={shelf_index}, "
# #                         f"caps={len([r for r in all_cap_records if r[1] == filename])}, "
# #                         f"skus={len([r for r in all_sku_records if r[1] == filename])}"
# #                     )

# #                 except Exception as e:
# #                     logger.error(f"Error processing {filename}: {e}")

# #         # Inference complete, now reopen database for insertion
# #         logger.info("=" * 70)
# #         logger.info("Reopening database for insertion...")
        
# #         db_config = config['db_config']
        
# #         # Retry connection up to 3 times
# #         max_retries = 3
# #         for attempt in range(max_retries):
# #             try:
# #                 conn = pg.connect(
# #                     host=db_config['host'],
# #                     port=db_config['port'],
# #                     database=db_config['database'],
# #                     user=db_config['user'],
# #                     password=db_config['password'],
# #                     timeout=30
# #                 )
# #                 cur = conn.cursor()
# #                 logger.info("Database reconnected successfully")
# #                 break
# #             except Exception as e:
# #                 logger.warning(f"Failed to reconnect (attempt {attempt + 1}/{max_retries}): {e}")
# #                 if attempt < max_retries - 1:
# #                     import time
# #                     time.sleep(5)
# #                 else:
# #                     logger.error("Failed to reconnect to database after all retries")
# #                     raise
        
# #         # Insert SKU detections into temp table
# #         if all_sku_records:
# #             insert_sku_predictions(cur, all_sku_records)
        
# #         # Insert cap detections into temp table
# #         if all_cap_records:
# #             insert_cap_predictions(cur, all_cap_records)
        
# #         # Commit all changes
# #         conn.commit()
# #         logger.info("Database commit successful")
        
# #         # Close database connection
# #         try:
# #             close_db_connection(conn, cur)
# #             logger.info("Database closed after insert")
# #         except Exception as e:
# #             logger.warning(f"Error closing connection: {e}")

# #         # Log final statistics
# #         logger.info("=" * 70)
# #         logger.info(f"VISICOOLER BATCH COMPLETE:")
# #         logger.info(f"  Iteration ID: {iterationid}")
# #         logger.info(f"  Images processed (this batch): {total_processed}")
# #         logger.info(f"  SKU detections (this batch): {total_sku_detections}")
# #         logger.info(f"  Cap detections (this batch): {total_cap_detections}")
# #         logger.info(f"  Batch data APPENDED to temp tables (not deleted)")
# #         logger.info("=" * 70)

# #         return []

# #     except Exception as e:
# #         logger.error(f"Fatal error: {type(e).__name__}: {e}")
        
# #         # Try to close database connection if still open
# #         if conn is not None:
# #             try:
# #                 close_db_connection(conn, cur)
# #             except Exception as close_error:
# #                 logger.warning(f"Error closing connection during cleanup: {close_error}")
        
# #         raise

# import os
# import cv2
# from ultralytics import YOLO
# import logging
# from app.db_handler import close_db_connection, get_classtext
# from app.config_loader import load_config
# from app.s3_handler import S3Handler
# from app.db_retry import retry_on_network_error, verify_connection
# from datetime import datetime
# import re
# from collections import defaultdict
# import pg8000.dbapi as pg

# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)


# def check_visibilitydetails_schema(cur):
#     # Check if visibilitydetails table exists and has correct schema (stub)
#     return True


# def upload_to_visibilitydetails(conn, cur, records, cyclecountid):
#     # Upload visicooler records to orgi.visibilitydetails (stub - not currently used)
#     pass


# def should_ignore_class(cls_id: int, class_names: dict) -> bool:
#     # Filter out unwanted detections
#     name = class_names.get(cls_id, "").lower()
#     false_negative_keywords = [" 700ml", "750ml","visicooler", "cooler"]
#     return any(keyword in name for keyword in false_negative_keywords)


# def extract_brand_from_name(name: str) -> str:
#     # Extract brand from product name
#     name_lower = name.lower().strip()
    
#     # Remove size and package type info
#     name_lower = re.sub(r'\d+ml|\d+l|pet|glass|bottle|can|cap', '', name_lower)
#     name_lower = name_lower.strip()
    
#     # Check for specific brands
#     if "coca-cola zero" in name_lower or "coca cola zero" in name_lower:
#         return "coca-cola zero"
#     if "coca-cola" in name_lower or "coca cola" in name_lower or "coke" in name_lower:
#         return "coca-cola"
#     if "mountain dew" in name_lower:
#         return "mountain dew"
#     if "kinley soda" in name_lower:
#         return "kinley soda"
#     if "kinley water" in name_lower:
#         return "kinley water"
#     if "sprite" in name_lower:
#         return "sprite"
#     if "fanta" in name_lower:
#         return "fanta"
#     if "thums up" in name_lower or "thumbs up" in name_lower:
#         return "thums up"
#     if "limca" in name_lower:
#         return "limca"
#     if "maaza" in name_lower:
#         return "maaza"
#     if "pepsi" in name_lower:
#         return "pepsi"
#     if "mirinda" in name_lower:
#         return "mirinda"
#     if "7up" in name_lower or "7 up" in name_lower:
#         return "7up"
#     if "slice" in name_lower:
#         return "slice"
#     if "sting" in name_lower:
#         return "sting"
#     if "aquafina" in name_lower:
#         return "aquafina"
#     if "other" in name_lower:
#         return "other"
    
#     # Default to first word if no match
#     words = name_lower.split()
#     return words[0] if words else ""


# @retry_on_network_error(max_retries=3, delay=5)
# def insert_cap_predictions(cur, cap_records):
#     # Insert cap predictions with retry on network errors
#     if not cap_records:
#         return
    
#     # Check if connection is still alive
#     if not verify_connection(cur):
#         raise Exception("Database connection lost before cap insert")
    
#     insert_query = """
#     INSERT INTO temp.cap_prediction_temp
#     (store_id, image_file_name, iteration_id, cap_class_id, x1, x2, y1, y2, prod_class_id, shelfnumber, s3path_annotated_file)
#     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
#     """
    
#     try:
#         cur.executemany(insert_query, cap_records)
#         logger.info(f"Inserted {len(cap_records)} cap predictions")
#     except Exception as e:
#         logger.error(f"Failed to insert cap predictions: {type(e).__name__}: {e}")
#         raise


# @retry_on_network_error(max_retries=3, delay=5)
# def insert_sku_predictions(cur, sku_records):
#     # Insert SKU predictions with retry on network errors
#     if not sku_records:
#         return
    
#     # Check if connection is still alive
#     if not verify_connection(cur):
#         raise Exception("Database connection lost before SKU insert")
    
#     insert_query = """
#     INSERT INTO temp.sku_prediction_temp
#     (store_id, image_file_name, iteration_id, prod_class_id, x1, x2, y1, y2, shelfnumber, brand_name, s3path_annotated_file)
#     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
#     """
    
#     try:
#         cur.executemany(insert_query, sku_records)
#         logger.info(f"Inserted {len(sku_records)} SKU predictions")
#     except Exception as e:
#         logger.error(f"Failed to insert SKU predictions: {type(e).__name__}: {e}")
#         raise


# def reconnect_database(config):
#     # Reconnect to database after connection loss
#     try:
#         db_config = config['db_config']
#         conn = pg.connect(
#             host=db_config['host'],
#             port=db_config['port'],
#             database=db_config['database'],
#             user=db_config['user'],
#             password=db_config['password'],
#             timeout=30
#         )
#         cur = conn.cursor()
#         logger.info("Database reconnected successfully")
#         return conn, cur
#     except Exception as e:
#         logger.error(f"Failed to reconnect to database: {e}")
#         raise


# def run_visicooler_analysis(image_paths, config, s3_handler, conn, cur, 
#                             output_folder_path, cyclecountid, iterationid=None):

#     try:
#         # Load model paths from config
#         shelf_model_path = config['visicooler_config']['caps_model_path']
#         sku_model_path = config['visicooler_config']['sku_model_path']
#         annotation_model_path = config['visicooler_config']['model_path']
        
#         # Get confidence thresholds
#         cap_conf_threshold = config['visicooler_config'].get('cap_conf_threshold', 0.1)
#         sku_conf_threshold = config['visicooler_config'].get('sku_conf_threshold', 0.35)
#         annotation_conf_threshold = config['visicooler_config'].get('conf_threshold', 0.12)

#         # Load YOLO models
#         logger.info("Loading YOLO models for visicooler analysis")
#         shelf_model = YOLO(shelf_model_path)
#         sku_model = YOLO(sku_model_path)
#         annotation_model = YOLO(annotation_model_path)
#         logger.info("YOLO models loaded successfully")

#         # Get class names from models
#         sku_class_names = sku_model.names
#         shelf_class_names = shelf_model.names

#         def _norm_storeid(sid):
#             # Normalize store ID format
#             if sid is None:
#                 return None
#             if isinstance(sid, str):
#                 s = sid.strip()
#                 if s.isdigit():
#                     return int(s)
#                 return s
#             return sid

#         def _get_canonical_storeid(filename, orig_storeid):
#             # Get canonical store ID from database
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
#             # Normalize subcategory ID
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

#         # Get or generate iteration ID
#         if iterationid is None:
#             try:
#                 cur.execute("SELECT COALESCE(MAX(iterationid), 0) FROM orgi.coolermetricsmaster")
#                 iterationid = cur.fetchone()[0] + 1
#                 logger.info(f"Generated new iterationid: {iterationid}")
#             except Exception as e:
#                 logger.warning(f"Failed to get iterationid from database: {e}")
#                 iterationid = 1
#                 logger.info(f"Using default iterationid: {iterationid}")
#         else:
#             logger.info(f"Using provided iterationid: {iterationid}")

#         # Close database before long processing
#         try:
#             if conn is not None and cur is not None:
#                 close_db_connection(conn, cur)
#                 logger.info("Database closed before inference (will reopen for insert)")
#         except Exception as e:
#             logger.warning(f"Connection already closed or error closing: {e}")
        
#         conn = None
#         cur = None

#         # Initialize counters
#         total_processed = 0
#         total_cap_detections = 0
#         total_sku_detections = 0
        
#         # Storage for all detections
#         all_cap_records = []
#         all_sku_records = []

#         # Count total subcategory 605 images
#         total_605_images = sum(1 for rows in store_images.values() for r in rows if r[6] == 605)
#         logger.info(f"Starting visicooler analysis on {total_605_images} images (subcategory 605 only)")

#         # Process each store
#         for sid, rows in store_images.items():
#             # Get only subcategory 605 images for shelf numbering
#             shelf_605_images = [r for r in rows if r[6] == 605]
            
#             # Process each image in the store
#             for stored_row in rows:
#                 fileseqid, storename, filename, local_path, s3_key, final_storeid, subcat_norm = stored_row

#                 # Skip if not subcategory 605
#                 if subcat_norm != 605:
#                     continue

#                 try:
#                     # Calculate shelf number for this image
#                     shelf_index = shelf_605_images.index(stored_row) + 1
                    
#                     # Read image
#                     image = cv2.imread(local_path)
#                     if image is None:
#                         logger.warning(f"Failed to read image: {filename}")
#                         continue

#                     image_height, image_width = image.shape[:2]
#                     os.makedirs(output_folder_path, exist_ok=True)

#                     # Generate S3 path for annotated image
#                     s3path_annotated = f"ModelResults/Visicooler_{cyclecountid}/segmented_{filename}"

#                     # Run SKU detection model
#                     sku_results = sku_model(local_path, conf=sku_conf_threshold)

#                     for result in sku_results:
#                         if not result.orig_shape:
#                             continue
                        
#                         # Calculate scaling factors
#                         sw = image_width / result.orig_shape[1]
#                         sh = image_height / result.orig_shape[0]

#                         for box in result.boxes:
#                             cls_id = int(box.cls[0])
                            
#                             # Skip unwanted classes
#                             if should_ignore_class(cls_id, sku_class_names):
#                                 continue

#                             # Get bounding box coordinates
#                             x1, y1, x2, y2 = box.xyxy[0]
#                             x1_px, y1_px = int(x1 * sw), int(y1 * sh)
#                             x2_px, y2_px = int(x2 * sw), int(y2 * sh)
                            
#                             # Extract brand name from product name
#                             product_name = sku_class_names[cls_id]
#                             brand_name = extract_brand_from_name(product_name)
                            
#                             # Store detection with shelf number, brand, and s3path_annotated_file
#                             all_sku_records.append((
#                                 final_storeid,
#                                 filename,
#                                 iterationid,
#                                 cls_id,
#                                 x1_px,
#                                 x2_px,
#                                 y1_px,
#                                 y2_px,
#                                 shelf_index,
#                                 brand_name,
#                                 s3path_annotated
#                             ))
                            
#                             total_sku_detections += 1

#                     # Run cap detection model
#                     cap_results = shelf_model(local_path, conf=cap_conf_threshold)

#                     for result in cap_results:
#                         if not result.orig_shape:
#                             continue
                        
#                         # Calculate scaling factors
#                         sw = image_width / result.orig_shape[1]
#                         sh = image_height / result.orig_shape[0]

#                         for box in result.boxes:
#                             cls_id = int(box.cls[0])
#                             name = shelf_class_names.get(cls_id, "").lower()
                            
#                             # Only process cap detections
#                             if "cap" not in name:
#                                 continue

#                             # Get bounding box coordinates
#                             x1, y1, x2, y2 = box.xyxy[0]
#                             x1_px, y1_px = int(x1 * sw), int(y1 * sh)
#                             x2_px, y2_px = int(x2 * sw), int(y2 * sh)
                            
#                             # Store detection with shelf number and s3path_annotated_file
#                             all_cap_records.append((
#                                 final_storeid,
#                                 filename,
#                                 iterationid,
#                                 cls_id,
#                                 x1_px,
#                                 x2_px,
#                                 y1_px,
#                                 y2_px,
#                                 None,
#                                 shelf_index,
#                                 s3path_annotated
#                             ))
                            
#                             total_cap_detections += 1

#                     # Generate annotated image for visualization
#                     try:
#                         annotation_results = annotation_model(local_path, conf=annotation_conf_threshold)
#                         rendered = annotation_results[0].plot()
#                         out = os.path.join(output_folder_path, f"segmented_{filename}")
#                         cv2.imwrite(out, rendered)
#                         s3_handler.upload_file_to_s3(out, s3path_annotated)
#                     except Exception as e:
#                         logger.warning(f"Annotation failed: {e}")

#                     total_processed += 1
                    
#                     # Show progress every 5 images or for the last image
#                     if total_processed % 5 == 0 or total_processed == total_605_images:
#                         remaining = total_605_images - total_processed
#                         logger.info(f"Visicooler progress: {total_processed}/{total_605_images} images processed, {remaining} remaining")

#                 except Exception as e:
#                     logger.error(f"Error processing {filename}: {e}")

#         # Inference complete, now reopen database for insertion
#         logger.info("Visicooler analysis complete, reopening database for insertion")
        
#         db_config = config['db_config']
        
#         # Retry connection up to 3 times
#         max_retries = 3
#         for attempt in range(max_retries):
#             try:
#                 conn = pg.connect(
#                     host=db_config['host'],
#                     port=db_config['port'],
#                     database=db_config['database'],
#                     user=db_config['user'],
#                     password=db_config['password'],
#                     timeout=30
#                 )
#                 cur = conn.cursor()
#                 logger.info("Database reconnected successfully")
#                 break
#             except Exception as e:
#                 logger.warning(f"Failed to reconnect (attempt {attempt + 1}/{max_retries}): {e}")
#                 if attempt < max_retries - 1:
#                     import time
#                     time.sleep(5)
#                 else:
#                     logger.error("Failed to reconnect to database after all retries")
#                     raise
        
#         # Insert SKU detections into temp table
#         if all_sku_records:
#             insert_sku_predictions(cur, all_sku_records)
        
#         # Insert cap detections into temp table
#         if all_cap_records:
#             insert_cap_predictions(cur, all_cap_records)
        
#         # Commit all changes
#         conn.commit()
#         logger.info("Database commit successful")
        
#         # Close database connection
#         try:
#             close_db_connection(conn, cur)
#             logger.info("Database closed after insert")
#         except Exception as e:
#             logger.warning(f"Error closing connection: {e}")

#         # Log final statistics
#         logger.info("Visicooler batch complete")
#         logger.info(f"Iteration ID: {iterationid}")
#         logger.info(f"Images processed: {total_processed}")
#         logger.info(f"SKU detections: {total_sku_detections}")
#         logger.info(f"Cap detections: {total_cap_detections}")

#         return []

#     except Exception as e:
#         logger.error(f"Fatal error: {type(e).__name__}: {e}")
        
#         # Try to close database connection if still open
#         if conn is not None:
#             try:
#                 close_db_connection(conn, cur)
#             except Exception as close_error:
#                 logger.warning(f"Error closing connection during cleanup: {close_error}")
        
#         raise


import os
import cv2
from ultralytics import YOLO
import logging
from app.db_handler import close_db_connection, get_classtext
from app.config_loader import load_config
from app.s3_handler import S3Handler
from app.db_retry import retry_on_network_error, verify_connection
from datetime import datetime
import re
from collections import defaultdict
import pg8000.dbapi as pg

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def check_visibilitydetails_schema(cur):
    # Check if visibilitydetails table exists and has correct schema (stub)
    return True


def upload_to_visibilitydetails(conn, cur, records, cyclecountid):
    # Upload visicooler records to orgi.visibilitydetails (stub - not currently used)
    pass


def should_ignore_class(cls_id: int, class_names: dict) -> bool:
    # Filter out unwanted detections
    name = class_names.get(cls_id, "").lower()
    false_negative_keywords = [" 700ml", "750ml","visicooler", "cooler"]
    return any(keyword in name for keyword in false_negative_keywords)


def extract_brand_from_name(name: str) -> str:
    # Extract brand from product name
    name_lower = name.lower().strip()
    
    # Remove size and package type info
    name_lower = re.sub(r'\d+ml|\d+l|pet|glass|bottle|can|cap', '', name_lower)
    name_lower = name_lower.strip()
    
    # Check for specific brands
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


@retry_on_network_error(max_retries=3, delay=5)
def insert_cap_predictions(cur, cap_records):
    # Insert cap predictions with retry on network errors
    if not cap_records:
        return
    
    # Check if connection is still alive
    if not verify_connection(cur):
        raise Exception("Database connection lost before cap insert")
    
    insert_query = """
    INSERT INTO temp.cap_prediction_temp
    (store_id, image_file_name, iteration_id, cap_class_id, x1, x2, y1, y2, prod_class_id, shelfnumber, s3path_annotated_file)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    try:
        cur.executemany(insert_query, cap_records)
        logger.info(f"Inserted {len(cap_records)} cap predictions")
    except Exception as e:
        logger.error(f"Failed to insert cap predictions: {type(e).__name__}: {e}")
        raise


@retry_on_network_error(max_retries=3, delay=5)
def insert_sku_predictions(cur, sku_records):
    # Insert SKU predictions with retry on network errors
    if not sku_records:
        return
    
    # Check if connection is still alive
    if not verify_connection(cur):
        raise Exception("Database connection lost before SKU insert")
    
    insert_query = """
    INSERT INTO temp.sku_prediction_temp
    (store_id, image_file_name, iteration_id, prod_class_id, x1, x2, y1, y2, shelfnumber, brand_name, s3path_annotated_file)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    try:
        cur.executemany(insert_query, sku_records)
        logger.info(f"Inserted {len(sku_records)} SKU predictions")
    except Exception as e:
        logger.error(f"Failed to insert SKU predictions: {type(e).__name__}: {e}")
        raise


def reconnect_database(config):
    # Reconnect to database after connection loss
    try:
        db_config = config['db_config']
        conn = pg.connect(
            host=db_config['host'],
            port=db_config['port'],
            database=db_config['database'],
            user=db_config['user'],
            password=db_config['password'],
            timeout=30
        )
        cur = conn.cursor()
        logger.info("Database reconnected successfully")
        return conn, cur
    except Exception as e:
        logger.error(f"Failed to reconnect to database: {e}")
        raise


def run_visicooler_analysis(image_paths, config, s3_handler, conn, cur, 
                            output_folder_path, cyclecountid, iterationid=None):

    try:
        # Load model paths from config
        shelf_model_path = config['visicooler_config']['caps_model_path']
        sku_model_path = config['visicooler_config']['sku_model_path']
        # annotation_model_path (model_path / capmodelnew.pt) no longer used —
        # sku_model (weights.pt) now handles both detection and S3 annotation.
        
        # Get confidence thresholds
        cap_conf_threshold = config['visicooler_config'].get('cap_conf_threshold', 0.1)
        sku_conf_threshold = config['visicooler_config'].get('sku_conf_threshold', 0.35)
        # annotation_conf_threshold removed — sku_conf_threshold is used for annotation too.

        # Load YOLO models
        # Note: annotation_model (capmodelnew.pt) removed — sku_model (weights.pt)
        # is used for both detection AND annotated image generation, as it is the
        # upgraded model with more accurate results.
        logger.info("Loading YOLO models for visicooler analysis")
        shelf_model = YOLO(shelf_model_path)
        sku_model = YOLO(sku_model_path)
        logger.info("YOLO models loaded successfully")

        # Get class names from models
        sku_class_names = sku_model.names
        shelf_class_names = shelf_model.names

        def _norm_storeid(sid):
            # Normalize store ID format
            if sid is None:
                return None
            if isinstance(sid, str):
                s = sid.strip()
                if s.isdigit():
                    return int(s)
                return s
            return sid

        def _get_canonical_storeid(filename, orig_storeid):
            # Get canonical store ID from database
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
            # Normalize subcategory ID
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

        # Get or generate iteration ID
        if iterationid is None:
            try:
                cur.execute("SELECT COALESCE(MAX(iterationid), 0) FROM orgi.coolermetricsmaster")
                iterationid = cur.fetchone()[0] + 1
                logger.info(f"Generated new iterationid: {iterationid}")
            except Exception as e:
                logger.warning(f"Failed to get iterationid from database: {e}")
                iterationid = 1
                logger.info(f"Using default iterationid: {iterationid}")
        else:
            logger.info(f"Using provided iterationid: {iterationid}")

        # Close database before long processing
        try:
            if conn is not None and cur is not None:
                close_db_connection(conn, cur)
                logger.info("Database closed before inference (will reopen for insert)")
        except Exception as e:
            logger.warning(f"Connection already closed or error closing: {e}")
        
        conn = None
        cur = None

        # Initialize counters
        total_processed = 0
        total_cap_detections = 0
        total_sku_detections = 0
        
        # Storage for all detections
        all_cap_records = []
        all_sku_records = []

        # Count total subcategory 605 images
        total_605_images = sum(1 for rows in store_images.values() for r in rows if r[6] == 605)
        logger.info(f"Starting visicooler analysis on {total_605_images} images (subcategory 605 only)")

        # Process each store
        for sid, rows in store_images.items():
            # Get only subcategory 605 images for shelf numbering
            shelf_605_images = [r for r in rows if r[6] == 605]
            
            # Process each image in the store
            for stored_row in rows:
                fileseqid, storename, filename, local_path, s3_key, final_storeid, subcat_norm = stored_row

                # Skip if not subcategory 605
                if subcat_norm != 605:
                    continue

                try:
                    # Calculate shelf number for this image
                    shelf_index = shelf_605_images.index(stored_row) + 1
                    
                    # Read image
                    image = cv2.imread(local_path)
                    if image is None:
                        logger.warning(f"Failed to read image: {filename}")
                        continue

                    image_height, image_width = image.shape[:2]
                    os.makedirs(output_folder_path, exist_ok=True)

                    # Generate S3 path for annotated image
                    s3path_annotated = f"ModelResults/Visicooler_{cyclecountid}/segmented_{filename}"

                    # Run SKU detection model
                    sku_results = sku_model(local_path, conf=sku_conf_threshold)

                    for result in sku_results:
                        if not result.orig_shape:
                            continue
                        
                        # Calculate scaling factors
                        sw = image_width / result.orig_shape[1]
                        sh = image_height / result.orig_shape[0]

                        for box in result.boxes:
                            cls_id = int(box.cls[0])
                            
                            # Skip unwanted classes
                            if should_ignore_class(cls_id, sku_class_names):
                                continue

                            # Get bounding box coordinates
                            x1, y1, x2, y2 = box.xyxy[0]
                            x1_px, y1_px = int(x1 * sw), int(y1 * sh)
                            x2_px, y2_px = int(x2 * sw), int(y2 * sh)
                            
                            # Extract brand name from product name
                            product_name = sku_class_names[cls_id]
                            brand_name = extract_brand_from_name(product_name)
                            
                            # Store detection with shelf number, brand, and s3path_annotated_file
                            all_sku_records.append((
                                final_storeid,
                                filename,
                                iterationid,
                                cls_id,
                                x1_px,
                                x2_px,
                                y1_px,
                                y2_px,
                                shelf_index,
                                brand_name,
                                s3path_annotated
                            ))
                            
                            total_sku_detections += 1

                    # Run cap detection model
                    cap_results = shelf_model(local_path, conf=cap_conf_threshold)

                    for result in cap_results:
                        if not result.orig_shape:
                            continue
                        
                        # Calculate scaling factors
                        sw = image_width / result.orig_shape[1]
                        sh = image_height / result.orig_shape[0]

                        for box in result.boxes:
                            cls_id = int(box.cls[0])
                            name = shelf_class_names.get(cls_id, "").lower()
                            
                            # Only process cap detections
                            if "cap" not in name:
                                continue

                            # Get bounding box coordinates
                            x1, y1, x2, y2 = box.xyxy[0]
                            x1_px, y1_px = int(x1 * sw), int(y1 * sh)
                            x2_px, y2_px = int(x2 * sw), int(y2 * sh)
                            
                            # Store detection with shelf number and s3path_annotated_file
                            all_cap_records.append((
                                final_storeid,
                                filename,
                                iterationid,
                                cls_id,
                                x1_px,
                                x2_px,
                                y1_px,
                                y2_px,
                                None,
                                shelf_index,
                                s3path_annotated
                            ))
                            
                            total_cap_detections += 1

                    # Generate annotated image using the upgraded SKU model (weights.pt).
                    # Previously used annotation_model (capmodelnew.pt), but sku_model
                    # produces more accurate detections and richer visualizations.
                    try:
                        sku_annotation_results = sku_model(local_path, conf=sku_conf_threshold)
                        rendered = sku_annotation_results[0].plot()
                        out = os.path.join(output_folder_path, f"segmented_{filename}")
                        cv2.imwrite(out, rendered)
                        s3_handler.upload_file_to_s3(out, s3path_annotated)
                        logger.info(f"Uploaded SKU-annotated image: segmented_{filename}")
                    except Exception as e:
                        logger.warning(f"Annotation failed: {e}")

                    total_processed += 1
                    
                    # Show progress every 5 images or for the last image
                    if total_processed % 5 == 0 or total_processed == total_605_images:
                        remaining = total_605_images - total_processed
                        logger.info(f"Visicooler progress: {total_processed}/{total_605_images} images processed, {remaining} remaining")

                except Exception as e:
                    logger.error(f"Error processing {filename}: {e}")

        # Inference complete, now reopen database for insertion
        logger.info("Visicooler analysis complete, reopening database for insertion")
        
        db_config = config['db_config']
        
        # Retry connection up to 3 times
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
                logger.info("Database reconnected successfully")
                break
            except Exception as e:
                logger.warning(f"Failed to reconnect (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(5)
                else:
                    logger.error("Failed to reconnect to database after all retries")
                    raise
        
        # Insert SKU detections into temp table
        if all_sku_records:
            insert_sku_predictions(cur, all_sku_records)
        
        # Insert cap detections into temp table
        if all_cap_records:
            insert_cap_predictions(cur, all_cap_records)
        
        # Commit all changes
        conn.commit()
        logger.info("Database commit successful")
        
        # Close database connection
        try:
            close_db_connection(conn, cur)
            logger.info("Database closed after insert")
        except Exception as e:
            logger.warning(f"Error closing connection: {e}")

        # Log final statistics
        logger.info("Visicooler batch complete")
        logger.info(f"Iteration ID: {iterationid}")
        logger.info(f"Images processed: {total_processed}")
        logger.info(f"SKU detections: {total_sku_detections}")
        logger.info(f"Cap detections: {total_cap_detections}")

        return []

    except Exception as e:
        logger.error(f"Fatal error: {type(e).__name__}: {e}")
        
        # Try to close database connection if still open
        if conn is not None:
            try:
                close_db_connection(conn, cur)
            except Exception as close_error:
                logger.warning(f"Error closing connection during cleanup: {close_error}")
        
        raise