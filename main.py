# import matplotlib
# matplotlib.use('Agg')
# import traceback
# import logging
# import os
# import sys
# import tempfile
# import time
# from app.config_loader import load_config
# from app.s3_handler import S3Handler
# from app.ollama_analyzer import run_ollama_analysis
# from app.file_uploader import FileUploader
# from app.db_handler import initialize_db_connection, close_db_connection
# from app.visicooler import run_visicooler_analysis, check_visibilitydetails_schema


# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler('outputs/pipeline.log'),
#         logging.StreamHandler()
#     ]
# )
# logger = logging.getLogger(__name__)

# # Reset stale assignments after 60 minutes
# STALE_TIMEOUT_MINUTES = 60


# def get_unprocessed_store_count(conn):
#     """Count distinct unprocessed stores."""
#     try:
#         cur = conn.cursor()
#         cur.execute("""
#             SELECT COUNT(DISTINCT storeid) 
#             FROM orgi.fileupload 
#             WHERE (processed_flag IN ('N', '0.0') OR processed_flag IS NULL)
#               AND storeid IS NOT NULL
#         """)
#         count = cur.fetchone()[0]
#         cur.close()
#         return count
#     except Exception as e:
#         logger.error(f"Failed to get unprocessed store count: {e}")
#         return 0


# def reset_stale_batches(conn, stale_timeout_minutes):
#     """
#     Reset stores stuck in 'I' status beyond timeout period.
#     Handles crashed pods or interrupted processing.
#     """
#     try:
#         cur = conn.cursor()
#         cur.execute("""
#             UPDATE orgi.fileupload
#             SET processed_flag = 'N', podid = NULL
#             WHERE processed_flag = 'I' 
#               AND uploadtimestamp < NOW() - INTERVAL '%s minutes'
#         """ % stale_timeout_minutes)
        
#         reset_count = cur.rowcount
#         conn.commit()
#         cur.close()
        
#         if reset_count > 0:
#             logger.warning(f"Reset {reset_count} stale files (stuck >{stale_timeout_minutes}m)")
        
#         return reset_count
#     except Exception as e:
#         logger.error(f"Failed to reset stale batches: {e}")
#         conn.rollback()
#         return 0


# def assign_stores_to_pod(conn, store_count, pod_id):
#     """
#     Updates processed_flag from 'N' to 'I' and sets podid.
#     Fixed: Removed DISTINCT from FOR UPDATE query.
#     """
#     try:
#         cur = conn.cursor()
        
#         # First, get the distinct store IDs without FOR UPDATE
#         cur.execute("""
#             SELECT DISTINCT storeid
#             FROM orgi.fileupload
#             WHERE (processed_flag IN ('N', '0.0') OR processed_flag IS NULL)
#               AND storeid IS NOT NULL
#             ORDER BY storeid
#             LIMIT %s
#         """, (store_count,))
        
#         selected_stores = [row[0] for row in cur.fetchall()]
        
#         if not selected_stores:
#             cur.close()
#             return 0, 0
        
#         # Then update all images for those stores with row-level locking
#         cur.execute("""
#             UPDATE orgi.fileupload
#             SET processed_flag = 'I', podid = %s
#             WHERE storeid = ANY(%s)
#               AND (processed_flag IN ('N', '0.0') OR processed_flag IS NULL)
#         """, (pod_id, selected_stores))
        
#         assigned_files = cur.rowcount
#         assigned_stores = len(selected_stores)
        
#         conn.commit()
#         cur.close()
        
#         logger.info(f"Assigned {assigned_stores} stores ({assigned_files} images) to {pod_id}")
#         return assigned_stores, assigned_files
        
#     except Exception as e:
#         logger.error(f"Failed to assign stores to pod: {e}")
#         conn.rollback()
#         return 0, 0


# def get_or_create_iterationid(conn):
#     try:
#         cur = conn.cursor()
        
#         # Get max iterationid from coolermetricsmaster
#         cur.execute("SELECT COALESCE(MAX(iteration_id), 0) FROM temp.cap_prediction_temp")
#         max_iteration = cur.fetchone()[0]
#         iterationid = max_iteration + 1
        
#         cur.close()
#         logger.info(f"Using iterationid: {iterationid} for this pipeline run")
#         return iterationid
        
#     except Exception as e:
#         logger.error(f"Failed to get iterationid: {e}")
#         return 1


# # def execute_models(pod_id, iterationid):
# #     """Run the processing pipeline for stores assigned to this pod."""
# #     conn = None
# #     cur = None
# #     try:
# #         config = load_config('config.json')
# #         ollama_config = config['ollama_config']
# #         s3_config = config['s3_config']
# #         db_config = config['db_config']
# #         visicooler_config = config['visicooler_config']

# #         conn, cur = initialize_db_connection(db_config)

# #         if not check_visibilitydetails_schema(cur):
# #             logger.error("Schema validation failed for orgi.visibilitydetails")
# #             return False

# #         s3_handler = S3Handler(s3_config, db_config)

# #         with tempfile.TemporaryDirectory() as temp_dir:
# #             logger.info(f"Created temp directory: {temp_dir}")

# #             # Download images for stores assigned to this pod
# #             logger.info(f"Downloading images for {pod_id}...")
# #             image_paths, failed_files = s3_handler.download_images_from_s3(temp_dir, pod_id)

# #             if not image_paths:
# #                 logger.warning(f"No images downloaded for {pod_id}")
# #                 return False
            
# #             # Count unique stores being processed
# #             unique_stores = len(set(img[5] for img in image_paths if img[5]))
# #             logger.info(f"Processing {unique_stores} stores ({len(image_paths)} images)")

# #             if failed_files:
# #                 logger.warning(f"Failed downloads: {len(failed_files)}")

# #             # Get cyclecountid
# #             try:
# #                 cur.execute("""
# #                     SELECT GREATEST(
# #                         COALESCE((SELECT MAX(cyclecountid) FROM orgi.visibilitydetails), 0),
# #                         COALESCE((SELECT MAX(stagingid) FROM orgi.visibilityitemsstaging), 0)
# #                     ) AS max_cycle
# #                 """)
# #                 row = cur.fetchone()
# #                 max_cycle = int(row[0]) if row and row[0] is not None else 0
# #                 cyclecountid = max_cycle + 1
# #                 logger.info(f"Using cyclecountid: {cyclecountid}")
# #             except Exception as e:
# #                 logger.error(f"Failed to compute cyclecountid: {e}")
# #                 cyclecountid = 1

# #             # Run visicooler analysis (subcategory 605)
# #             logger.info(f"Running visicooler analysis (iterationid: {iterationid})...")
# #             try:
# #                 visicooler_records = run_visicooler_analysis(
# #                     image_paths=image_paths,
# #                     config=config,
# #                     s3_handler=s3_handler,
# #                     conn=conn,
# #                     cur=cur,
# #                     output_folder_path=visicooler_config['output_folder_path'],
# #                     cyclecountid=cyclecountid,
# #                     iterationid=iterationid
# #                 )
# #                 logger.info(f"Visicooler: {len(visicooler_records)} records")
# #             except Exception as e:
# #                 logger.error(f"Visicooler analysis failed: {e}")
# #                 visicooler_records = []

# #             close_db_connection(conn, cur)
# #             conn = None
# #             cur = None

# #             # Run Ollama analysis (visibility items)
# #             logger.info("Running Ollama analysis...")
# #             try:
# #                 ollama_results, ollama_csv = run_ollama_analysis(
# #                     image_paths=image_paths,
# #                     image_folder=temp_dir,
# #                     output_csv=ollama_config['output_csv'],
# #                     config_path='config.json',
# #                     class_ids_path=ollama_config['class_ids_path'],
# #                     ollama_host=ollama_config['ollama_host'],
# #                     s3_handler=s3_handler,
# #                     s3_annotated_folder=f"{ollama_config['output_s3_folder']}VisibleItem_{cyclecountid}",
# #                     db_config=db_config,
# #                     cyclecountid=cyclecountid
# #                 )
# #                 logger.info(f"Ollama: {len(ollama_results)} records")
# #             except Exception as e:
# #                 logger.error(f"Ollama analysis failed: {e}")
# #                 logger.error(traceback.format_exc())
# #                 ollama_results, ollama_csv = [], None

# #             # Upload Ollama CSV to S3
# #             if ollama_csv and os.path.exists(ollama_csv):
# #                 logger.info("Uploading Ollama CSV to S3...")
# #                 try:
# #                     s3_handler.upload_file_to_s3(
# #                         ollama_csv,
# #                         f"{ollama_config['output_s3_folder']}VisibleItem_{cyclecountid}/analysis_results.csv"
# #                     )
# #                     logger.info("Ollama CSV uploaded")
# #                 except Exception as e:
# #                     logger.error(f"CSV upload failed: {e}")
# #             else:
# #                 logger.warning("No Ollama CSV to upload")

# #             # Update processed_flag to 'Y'
# #             logger.info("Updating processed_flag...")
# #             try:
# #                 conn, cur = initialize_db_connection(db_config)
# #                 file_uploader = FileUploader(None)
# #                 failed_updates = file_uploader.update_processed_flag(conn, image_paths)
# #                 if failed_updates:
# #                     logger.warning(f"Failed updates: {len(failed_updates)}")
# #                 else:
# #                     logger.info(f"Updated {len(image_paths)} files")
# #             except Exception as e:
# #                 logger.error(f"Update failed: {e}")

# #             logger.info("=" * 60)
# #             logger.info(f"BATCH COMPLETE - Pod: {pod_id} (Iteration: {iterationid})")
# #             logger.info(f"  Stores: {unique_stores}")
# #             logger.info(f"  Images: {len(image_paths)}")
# #             logger.info(f"  Visicooler: {len(visicooler_records)}")
# #             logger.info(f"  Ollama: {len(ollama_results) if ollama_results else 0}")
# #             logger.info("=" * 60)

# #         return True

# #     except Exception as e:
# #         logger.error(f"Error in execute_models: {e}")
# #         logger.error(traceback.format_exc())
# #         if conn and 'conn' in locals():
# #             conn.rollback()
# #         return False
# #     finally:
# #         if conn is not None:
# #             close_db_connection(conn, cur)


# def execute_models(pod_id, iterationid):
#     # Run the processing pipeline for stores assigned to this pod
#     conn = None
#     cur = None
#     try:
#         config = load_config('config.json')
#         ollama_config = config['ollama_config']
#         s3_config = config['s3_config']
#         db_config = config['db_config']
#         visicooler_config = config['visicooler_config']

#         conn, cur = initialize_db_connection(db_config)

#         if not check_visibilitydetails_schema(cur):
#             logger.error("Schema validation failed for orgi.visibilitydetails")
#             return False

#         s3_handler = S3Handler(s3_config, db_config)

#         with tempfile.TemporaryDirectory() as temp_dir:
#             logger.info(f"Created temp directory: {temp_dir}")

#             # Download images for stores assigned to this pod
#             logger.info(f"Downloading images for {pod_id}...")
#             image_paths, failed_files = s3_handler.download_images_from_s3(temp_dir, pod_id)

#             if not image_paths:
#                 logger.warning(f"No images downloaded for {pod_id}")
#                 return False
            
#             # Count unique stores being processed
#             unique_stores = len(set(img[5] for img in image_paths if img[5]))
#             logger.info(f"Processing {unique_stores} stores ({len(image_paths)} images)")

#             if failed_files:
#                 logger.warning(f"Failed downloads: {len(failed_files)}")

#             # Get cyclecountid with retry on connection errors
#             cyclecountid = 1
#             max_retries = 3
#             for attempt in range(max_retries):
#                 try:
#                     cur.execute("""
#                         SELECT GREATEST(
#                             COALESCE((SELECT MAX(cyclecountid) FROM orgi.visibilitydetails), 0),
#                             COALESCE((SELECT MAX(stagingid) FROM orgi.visibilityitemsstaging), 0)
#                         ) AS max_cycle
#                     """)
#                     row = cur.fetchone()
#                     max_cycle = int(row[0]) if row and row[0] is not None else 0
#                     cyclecountid = max_cycle + 1
#                     logger.info(f"Using cyclecountid: {cyclecountid}")
#                     break
#                 except Exception as e:
#                     logger.warning(f"Failed to get cyclecountid (attempt {attempt + 1}/{max_retries}): {e}")
#                     if attempt < max_retries - 1:
#                         # Reconnect and retry
#                         try:
#                             close_db_connection(conn, cur)
#                         except:
#                             pass
                        
#                         import time
#                         time.sleep(2)
#                         conn, cur = initialize_db_connection(db_config)
#                     else:
#                         logger.error(f"Failed to compute cyclecountid after {max_retries} attempts")
#                         cyclecountid = 1

#             # Run visicooler analysis (subcategory 605)
#             logger.info(f"Running visicooler analysis (iterationid: {iterationid})...")
#             try:
#                 visicooler_records = run_visicooler_analysis(
#                     image_paths=image_paths,
#                     config=config,
#                     s3_handler=s3_handler,
#                     conn=conn,
#                     cur=cur,
#                     output_folder_path=visicooler_config['output_folder_path'],
#                     cyclecountid=cyclecountid,
#                     iterationid=iterationid
#                 )
#                 logger.info(f"Visicooler: {len(visicooler_records)} records")
#             except Exception as e:
#                 logger.error(f"Visicooler analysis failed: {e}")
#                 visicooler_records = []

#             # Connection is already closed by visicooler analysis, set to None
#             conn = None
#             cur = None

#             # Run Ollama analysis (visibility items)
#             logger.info("Running Ollama analysis...")
#             try:
#                 ollama_results, ollama_csv = run_ollama_analysis(
#                     image_paths=image_paths,
#                     image_folder=temp_dir,
#                     output_csv=ollama_config['output_csv'],
#                     config_path='config.json',
#                     class_ids_path=ollama_config['class_ids_path'],
#                     ollama_host=ollama_config['ollama_host'],
#                     s3_handler=s3_handler,
#                     s3_annotated_folder=f"{ollama_config['output_s3_folder']}VisibleItem_{cyclecountid}",
#                     db_config=db_config,
#                     cyclecountid=cyclecountid
#                 )
#                 logger.info(f"Ollama: {len(ollama_results)} records")
#             except Exception as e:
#                 logger.error(f"Ollama analysis failed: {e}")
#                 logger.error(traceback.format_exc())
#                 ollama_results, ollama_csv = [], None

#             # Upload Ollama CSV to S3
#             if ollama_csv and os.path.exists(ollama_csv):
#                 logger.info("Uploading Ollama CSV to S3...")
#                 try:
#                     s3_handler.upload_file_to_s3(
#                         ollama_csv,
#                         f"{ollama_config['output_s3_folder']}VisibleItem_{cyclecountid}/analysis_results.csv"
#                     )
#                     logger.info("Ollama CSV uploaded")
#                 except Exception as e:
#                     logger.error(f"CSV upload failed: {e}")
#             else:
#                 logger.warning("No Ollama CSV to upload")

#             # Update processed_flag to 'Y'
#             logger.info("Updating processed_flag...")
#             try:
#                 conn, cur = initialize_db_connection(db_config)
#                 file_uploader = FileUploader(None)
#                 failed_updates = file_uploader.update_processed_flag(conn, image_paths)
#                 if failed_updates:
#                     logger.warning(f"Failed updates: {len(failed_updates)}")
#                 else:
#                     logger.info(f"Updated {len(image_paths)} files")
#             except Exception as e:
#                 logger.error(f"Update failed: {e}")

#             logger.info("=" * 60)
#             logger.info(f"BATCH COMPLETE - Pod: {pod_id} (Iteration: {iterationid})")
#             logger.info(f"  Stores: {unique_stores}")
#             logger.info(f"  Images: {len(image_paths)}")
#             logger.info(f"  Visicooler: {len(visicooler_records)}")
#             logger.info(f"  Ollama: {len(ollama_results) if ollama_results else 0}")
#             logger.info("=" * 60)

#         return True

#     except Exception as e:
#         logger.error(f"Error in execute_models: {e}")
#         logger.error(traceback.format_exc())
#         if conn and 'conn' in locals():
#             try:
#                 conn.rollback()
#             except:
#                 pass
#         return False
#     finally:
#         if conn is not None:
#             try:
#                 close_db_connection(conn, cur)
#             except:
#                 pass


# def main():
#     if len(sys.argv) < 2:
#         logger.error("Usage: python main.py <pod-id>")
#         logger.error("Example: python main.py pod-1")
#         sys.exit(1)
    
#     pod_id = sys.argv[1]
#     logger.info(f"Starting pipeline for {pod_id}")
    
#     config = load_config('config.json')
#     db_config = config['db_config']
    
#     #  Generate iterationid once for the entire pipeline run
#     conn, cur = initialize_db_connection(db_config)
#     iterationid = get_or_create_iterationid(conn)
    
#     # CRITICAL FIX: Clear temp tables ONCE before batch loop
#     logger.info("=" * 60)
#     logger.info(f"CLEARING TEMP TABLES (iteration {iterationid})")
#     logger.info("=" * 60)
#     try:
#         cur.execute("DELETE FROM temp.sku_prediction_temp WHERE iteration_id = %s", (iterationid,))
#         deleted_sku = cur.rowcount
#         cur.execute("DELETE FROM temp.cap_prediction_temp WHERE iteration_id = %s", (iterationid,))
#         deleted_cap = cur.rowcount
#         conn.commit()
#         logger.info(f" Cleared {deleted_sku} SKU records, {deleted_cap} cap records")
#         logger.info(" Temp tables ready - batches will APPEND data")
#     except Exception as e:
#         logger.error(f"Failed to clear temp tables: {e}")
#         conn.rollback()
    
#     close_db_connection(conn, cur)
    
#     logger.info("=" * 60)
#     logger.info(f"Pipeline Run - Iteration ID: {iterationid}")
#     logger.info(f"All batches will use this iteration ID")
#     logger.info(f"Batch data will ACCUMULATE in temp tables")
#     logger.info("=" * 60)
    
#     batch_size = None
    
#     while True:
#         try:
#             conn, cur = initialize_db_connection(db_config)
            
#             # Reset stale assignments
#             reset_stale_batches(conn, STALE_TIMEOUT_MINUTES)
            
#             # Count unprocessed stores
#             unprocessed_stores = get_unprocessed_store_count(conn)
            
#             if unprocessed_stores == 0:
#                 logger.info("=" * 60)
#                 logger.info("*** All stores processed!")
#                 logger.info(f"Pipeline Run Complete - Iteration ID: {iterationid}")
#                 logger.info("=" * 60)
#                 close_db_connection(conn, cur)
#                 break
            
#             logger.info("=" * 60)
#             logger.info(f"Unprocessed stores: {unprocessed_stores}")
#             logger.info("=" * 60)
            
#             # Ask for batch size (first time only)
#             if batch_size is None:
#                 while True:
#                     try:
#                         batch_input = input(f"Enter batch size (stores) for {pod_id} (1-{unprocessed_stores}): ").strip()
#                         batch_size = int(batch_input)
#                         if 1 <= batch_size <= unprocessed_stores:
#                             break
#                         else:
#                             print(f"Enter a number between 1 and {unprocessed_stores}")
#                     except ValueError:
#                         print("Enter a valid number")
                
#                 logger.info(f"Batch size: {batch_size} stores")
            
#             # Assign stores to pod
#             assigned_stores, assigned_files = assign_stores_to_pod(conn, batch_size, pod_id)
#             close_db_connection(conn, cur)
            
#             if assigned_stores == 0:
#                 logger.warning("No stores assigned. Retrying in 10s...")
#                 time.sleep(10)
#                 continue
            
#             # Process batch with shared iterationid
#             logger.info(f"Processing {assigned_stores} stores ({assigned_files} images)...")
#             success = execute_models(pod_id, iterationid)
            
#             if not success:
#                 logger.warning("Batch failed. Waiting 10s...")
#                 time.sleep(10)
#             else:
#                 logger.info("Batch complete. Checking for next batch...")
#                 time.sleep(5)
            
#         except KeyboardInterrupt:
#             logger.info("Pipeline interrupted by user")
#             break
#         except Exception as e:
#             logger.error(f"Error in main loop: {e}")
#             logger.error(traceback.format_exc())
#             time.sleep(10)
    
#     logger.info(f"Pipeline execution completed for {pod_id}")


# if __name__ == "__main__":
#     main()


import matplotlib
matplotlib.use('Agg')
import traceback
import logging
import os
import sys
import tempfile
import time
from app.config_loader import load_config
from app.s3_handler import S3Handler
from app.ollama_analyzer import run_ollama_analysis
from app.file_uploader import FileUploader
from app.db_handler import initialize_db_connection, close_db_connection
from app.visicooler import run_visicooler_analysis, check_visibilitydetails_schema


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('outputs/pipeline.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Reset stale assignments after 60 minutes
STALE_TIMEOUT_MINUTES = 60


def get_unprocessed_store_count(conn):
    """Count distinct unprocessed stores."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(DISTINCT storeid) 
            FROM orgi.fileupload 
            WHERE (processed_flag IN ('N', '0.0') OR processed_flag IS NULL)
              AND storeid IS NOT NULL
        """)
        count = cur.fetchone()[0]
        cur.close()
        return count
    except Exception as e:
        logger.error(f"Failed to get unprocessed store count: {e}")
        return 0


def reset_stale_batches(conn, stale_timeout_minutes):
    """
    Reset stores stuck in 'I' status beyond timeout period.
    Handles crashed pods or interrupted processing.
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE orgi.fileupload
            SET processed_flag = 'N', podid = NULL
            WHERE processed_flag = 'I' 
              AND uploadtimestamp < NOW() - INTERVAL '%s minutes'
        """ % stale_timeout_minutes)
        
        reset_count = cur.rowcount
        conn.commit()
        cur.close()
        
        if reset_count > 0:
            logger.warning(f"Reset {reset_count} stale files (stuck over {stale_timeout_minutes} minutes)")
        
        return reset_count
    except Exception as e:
        logger.error(f"Failed to reset stale batches: {e}")
        conn.rollback()
        return 0


def assign_stores_to_pod(conn, store_count, pod_id):
    """
    Updates processed_flag from 'N' to 'I' and sets podid.
    Fixed: Removed DISTINCT from FOR UPDATE query.
    """
    try:
        cur = conn.cursor()
        
        # First, get the distinct store IDs without FOR UPDATE
        cur.execute("""
            SELECT DISTINCT storeid
            FROM orgi.fileupload
            WHERE (processed_flag IN ('N', '0.0') OR processed_flag IS NULL)
              AND storeid IS NOT NULL
            ORDER BY storeid
            LIMIT %s
        """, (store_count,))
        
        selected_stores = [row[0] for row in cur.fetchall()]
        
        if not selected_stores:
            cur.close()
            return 0, 0
        
        # Then update all images for those stores with row-level locking
        cur.execute("""
            UPDATE orgi.fileupload
            SET processed_flag = 'I', podid = %s
            WHERE storeid = ANY(%s)
              AND (processed_flag IN ('N', '0.0') OR processed_flag IS NULL)
        """, (pod_id, selected_stores))
        
        assigned_files = cur.rowcount
        assigned_stores = len(selected_stores)
        
        conn.commit()
        cur.close()
        
        logger.info(f"Assigned {assigned_stores} stores with {assigned_files} images to {pod_id}")
        return assigned_stores, assigned_files
        
    except Exception as e:
        logger.error(f"Failed to assign stores to pod: {e}")
        conn.rollback()
        return 0, 0


def get_or_create_iterationid(conn):
    try:
        cur = conn.cursor()
        
        # Get max iterationid from coolermetricsmaster
        cur.execute("SELECT COALESCE(MAX(iteration_id), 0) FROM temp.cap_prediction_temp")
        max_iteration = cur.fetchone()[0]
        iterationid = max_iteration + 1
        
        cur.close()
        logger.info(f"Using iterationid: {iterationid} for this pipeline run")
        return iterationid
        
    except Exception as e:
        logger.error(f"Failed to get iterationid: {e}")
        return 1


def execute_models(pod_id, iterationid):
    # Run the processing pipeline for stores assigned to this pod
    conn = None
    cur = None
    try:
        config = load_config('config.json')
        ollama_config = config['ollama_config']
        s3_config = config['s3_config']
        db_config = config['db_config']
        visicooler_config = config['visicooler_config']

        conn, cur = initialize_db_connection(db_config)

        if not check_visibilitydetails_schema(cur):
            logger.error("Schema validation failed for orgi.visibilitydetails")
            return False

        s3_handler = S3Handler(s3_config, db_config)

        with tempfile.TemporaryDirectory() as temp_dir:
            logger.info(f"Created temp directory: {temp_dir}")

            # Download images for stores assigned to this pod
            logger.info(f"Starting image download for {pod_id}")
            image_paths, failed_files = s3_handler.download_images_from_s3(temp_dir, pod_id)

            if not image_paths:
                logger.warning(f"No images downloaded for {pod_id}")
                return False
            
            # Count unique stores being processed
            unique_stores = len(set(img[5] for img in image_paths if img[5]))
            logger.info(f"Processing {unique_stores} stores with {len(image_paths)} total images")

            if failed_files:
                logger.warning(f"Failed downloads: {len(failed_files)} files")

            # Get cyclecountid with retry on connection errors
            cyclecountid = 1
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    cur.execute("""
                        SELECT GREATEST(
                            COALESCE((SELECT MAX(cyclecountid) FROM orgi.visibilitydetails), 0),
                            COALESCE((SELECT MAX(stagingid) FROM orgi.visibilityitemsstaging), 0)
                        ) AS max_cycle
                    """)
                    row = cur.fetchone()
                    max_cycle = int(row[0]) if row and row[0] is not None else 0
                    cyclecountid = max_cycle + 1
                    logger.info(f"Using cyclecountid: {cyclecountid}")
                    break
                except Exception as e:
                    logger.warning(f"Failed to get cyclecountid (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        # Reconnect and retry
                        try:
                            close_db_connection(conn, cur)
                        except:
                            pass
                        
                        import time
                        time.sleep(2)
                        conn, cur = initialize_db_connection(db_config)
                    else:
                        logger.error(f"Failed to compute cyclecountid after {max_retries} attempts")
                        cyclecountid = 1

            # Run visicooler analysis (subcategory 605)
            logger.info(f"Starting visicooler analysis (iterationid: {iterationid})")
            try:
                visicooler_records = run_visicooler_analysis(
                    image_paths=image_paths,
                    config=config,
                    s3_handler=s3_handler,
                    conn=conn,
                    cur=cur,
                    output_folder_path=visicooler_config['output_folder_path'],
                    cyclecountid=cyclecountid,
                    iterationid=iterationid
                )
                logger.info(f"Visicooler analysis complete: {len(visicooler_records)} records generated")
            except Exception as e:
                logger.error(f"Visicooler analysis failed: {e}")
                visicooler_records = []

            # Connection is already closed by visicooler analysis, set to None
            conn = None
            cur = None

            # Run Ollama analysis (visibility items)
            logger.info("Starting Ollama analysis")
            try:
                ollama_results, ollama_csv = run_ollama_analysis(
                    image_paths=image_paths,
                    image_folder=temp_dir,
                    output_csv=ollama_config['output_csv'],
                    config_path='config.json',
                    class_ids_path=ollama_config['class_ids_path'],
                    ollama_host=ollama_config['ollama_host'],
                    s3_handler=s3_handler,
                    s3_annotated_folder=f"{ollama_config['output_s3_folder']}VisibleItem_{cyclecountid}",
                    db_config=db_config,
                    cyclecountid=cyclecountid
                )
                logger.info(f"Ollama analysis complete: {len(ollama_results)} records generated")
            except Exception as e:
                logger.error(f"Ollama analysis failed: {e}")
                logger.error(traceback.format_exc())
                ollama_results, ollama_csv = [], None

            # Upload Ollama CSV to S3
            if ollama_csv and os.path.exists(ollama_csv):
                logger.info("Uploading Ollama CSV to S3")
                try:
                    s3_handler.upload_file_to_s3(
                        ollama_csv,
                        f"{ollama_config['output_s3_folder']}VisibleItem_{cyclecountid}/analysis_results.csv"
                    )
                    logger.info("Ollama CSV uploaded successfully")
                except Exception as e:
                    logger.error(f"CSV upload failed: {e}")
            else:
                logger.warning("No Ollama CSV to upload")

            # Update processed_flag to 'Y'
            logger.info("Updating processed_flag in database")
            try:
                conn, cur = initialize_db_connection(db_config)
                file_uploader = FileUploader(None)
                failed_updates = file_uploader.update_processed_flag(conn, image_paths)
                if failed_updates:
                    logger.warning(f"Failed to update {len(failed_updates)} files")
                else:
                    logger.info(f"Successfully updated {len(image_paths)} files to processed")
            except Exception as e:
                logger.error(f"Update processed_flag failed: {e}")

            logger.info("=" * 60)
            logger.info(f"BATCH COMPLETE - Pod: {pod_id} (Iteration: {iterationid})")
            logger.info(f"  Stores processed: {unique_stores}")
            logger.info(f"  Images processed: {len(image_paths)}")
            logger.info(f"  Visicooler records: {len(visicooler_records)}")
            logger.info(f"  Ollama records: {len(ollama_results) if ollama_results else 0}")
            logger.info("=" * 60)

        return True

    except Exception as e:
        logger.error(f"Error in execute_models: {e}")
        logger.error(traceback.format_exc())
        if conn and 'conn' in locals():
            try:
                conn.rollback()
            except:
                pass
        return False
    finally:
        if conn is not None:
            try:
                close_db_connection(conn, cur)
            except:
                pass


def main():
    if len(sys.argv) < 2:
        logger.error("Usage: python main.py <pod-id>")
        logger.error("Example: python main.py pod-1")
        sys.exit(1)
    
    pod_id = sys.argv[1]
    logger.info(f"Starting pipeline for {pod_id}")
    
    config = load_config('config.json')
    db_config = config['db_config']
    
    # Generate iterationid once for the entire pipeline run
    conn, cur = initialize_db_connection(db_config)
    iterationid = get_or_create_iterationid(conn)
    
    # CRITICAL FIX: Clear temp tables ONCE before batch loop
    logger.info("=" * 60)
    logger.info(f"CLEARING TEMP TABLES (iteration {iterationid})")
    logger.info("=" * 60)
    try:
        cur.execute("DELETE FROM temp.sku_prediction_temp WHERE iteration_id = %s", (iterationid,))
        deleted_sku = cur.rowcount
        cur.execute("DELETE FROM temp.cap_prediction_temp WHERE iteration_id = %s", (iterationid,))
        deleted_cap = cur.rowcount
        conn.commit()
        logger.info(f"Cleared {deleted_sku} SKU records, {deleted_cap} cap records")
        logger.info("Temp tables ready - batches will APPEND data")
    except Exception as e:
        logger.error(f"Failed to clear temp tables: {e}")
        conn.rollback()
    
    close_db_connection(conn, cur)
    
    logger.info("=" * 60)
    logger.info(f"Pipeline Run - Iteration ID: {iterationid}")
    logger.info(f"All batches will use this iteration ID")
    logger.info(f"Batch data will ACCUMULATE in temp tables")
    logger.info("=" * 60)
    
    batch_size = None
    batch_number = 0
    
    while True:
        try:
            conn, cur = initialize_db_connection(db_config)
            
            # Reset stale assignments
            reset_count = reset_stale_batches(conn, STALE_TIMEOUT_MINUTES)
            
            # Count unprocessed stores
            unprocessed_stores = get_unprocessed_store_count(conn)
            
            if unprocessed_stores == 0:
                logger.info("=" * 60)
                logger.info("All stores processed successfully")
                logger.info(f"Pipeline Run Complete - Iteration ID: {iterationid}")
                logger.info(f"Total batches processed: {batch_number}")
                logger.info("=" * 60)
                close_db_connection(conn, cur)
                break
            
            logger.info("=" * 60)
            logger.info(f"Unprocessed stores remaining: {unprocessed_stores}")
            logger.info("=" * 60)
            
            # Ask for batch size (first time only)
            if batch_size is None:
                while True:
                    try:
                        batch_input = input(f"Enter batch size (stores) for {pod_id} (1-{unprocessed_stores}): ").strip()
                        batch_size = int(batch_input)
                        if 1 <= batch_size <= unprocessed_stores:
                            break
                        else:
                            print(f"Enter a number between 1 and {unprocessed_stores}")
                    except ValueError:
                        print("Enter a valid number")
                
                logger.info(f"Batch size set to: {batch_size} stores")
            
            # Assign stores to pod
            assigned_stores, assigned_files = assign_stores_to_pod(conn, batch_size, pod_id)
            close_db_connection(conn, cur)
            
            if assigned_stores == 0:
                logger.warning("No stores assigned. Retrying in 10 seconds")
                time.sleep(10)
                continue
            
            batch_number += 1
            logger.info(f"Starting batch {batch_number}: {assigned_stores} stores, {assigned_files} images")
            
            # Process batch with shared iterationid
            success = execute_models(pod_id, iterationid)
            
            if not success:
                logger.warning(f"Batch {batch_number} failed. Waiting 10 seconds before retry")
                time.sleep(10)
            else:
                logger.info(f"Batch {batch_number} completed successfully. Checking for next batch")
                time.sleep(5)
            
        except KeyboardInterrupt:
            logger.info("Pipeline interrupted by user")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            logger.error(traceback.format_exc())
            time.sleep(10)
    
    logger.info(f"Pipeline execution completed for {pod_id}")


if __name__ == "__main__":
    main()