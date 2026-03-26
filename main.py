# # import matplotlib
# # matplotlib.use('Agg')
# # import traceback
# # import logging
# # import os
# # import sys
# # import tempfile
# # import time
# # from app.config_loader import load_config
# # from app.s3_handler import S3Handler
# # from app.ollama_analyzer import run_ollama_analysis
# # from app.file_uploader import FileUploader
# # from app.db_handler import initialize_db_connection, close_db_connection
# # from app.visicooler import run_visicooler_analysis, check_visibilitydetails_schema


# # logging.basicConfig(
# #     level=logging.INFO,
# #     format='%(asctime)s - %(levelname)s - %(message)s',
# #     handlers=[
# #         logging.FileHandler('outputs/pipeline.log'),
# #         logging.StreamHandler()
# #     ]
# # )
# # logger = logging.getLogger(__name__)

# # # Reset stale assignments after 60 minutes
# # STALE_TIMEOUT_MINUTES = 60


# # def get_unprocessed_store_count(conn):
# #     """Count distinct unprocessed stores."""
# #     try:
# #         cur = conn.cursor()
# #         cur.execute("""
# #             SELECT COUNT(DISTINCT storeid) 
# #             FROM orgi.fileupload 
# #             WHERE (processed_flag IN ('P', '0.0') OR processed_flag IS NULL)
# #               AND storeid IS NOT NULL
# #         """)
# #         count = cur.fetchone()[0]
# #         cur.close()
# #         return count
# #     except Exception as e:
# #         logger.error(f"Failed to get unprocessed store count: {e}")
# #         return 0


# # def reset_stale_batches(conn, stale_timeout_minutes):
# #     """
# #     Reset stores stuck in 'I' status beyond timeout period.
# #     Handles crashed pods or interrupted processing.
# #     """
# #     try:
# #         cur = conn.cursor()
# #         cur.execute("""
# #             UPDATE orgi.fileupload
# #             SET processed_flag = 'P', podid = NULL
# #             WHERE processed_flag = 'I' 
# #               AND uploadtimestamp < NOW() - INTERVAL '%s minutes'
# #         """ % stale_timeout_minutes)
        
# #         reset_count = cur.rowcount
# #         conn.commit()
# #         cur.close()
        
# #         if reset_count > 0:
# #             logger.warning(f"Reset {reset_count} stale files (stuck >{stale_timeout_minutes}m)")
        
# #         return reset_count
# #     except Exception as e:
# #         logger.error(f"Failed to reset stale batches: {e}")
# #         conn.rollback()
# #         return 0


# # def assign_stores_to_pod(conn, store_count, pod_id):
# #     """
# #     Updates processed_flag from 'N' to 'I' and sets podid.
# #     """
# #     try:
# #         cur = conn.cursor()
        
# #         # Get distinct store IDs
# #         cur.execute("""
# #             SELECT DISTINCT storeid
# #             FROM orgi.fileupload
# #             WHERE (processed_flag IN ('P', '0.0') OR processed_flag IS NULL)
# #               AND storeid IS NOT NULL
# #             ORDER BY storeid
# #             LIMIT %s
# #         """, (store_count,))
        
# #         selected_stores = [row[0] for row in cur.fetchall()]
        
# #         if not selected_stores:
# #             cur.close()
# #             return 0, 0
        
# #         # Update all images for those stores
# #         cur.execute("""
# #             UPDATE orgi.fileupload
# #             SET processed_flag = 'I', podid = %s
# #             WHERE storeid = ANY(%s)
# #               AND (processed_flag IN ('P', '0.0') OR processed_flag IS NULL)
# #         """, (pod_id, selected_stores))
        
# #         assigned_files = cur.rowcount
# #         assigned_stores = len(selected_stores)
        
# #         conn.commit()
# #         cur.close()
        
# #         logger.info(f"Assigned {assigned_stores} stores ({assigned_files} images) to {pod_id}")
# #         return assigned_stores, assigned_files
        
# #     except Exception as e:
# #         logger.error(f"Failed to assign stores to pod: {e}")
# #         conn.rollback()
# #         return 0, 0


# # def get_or_create_iterationid(conn):
# #     try:
# #         cur = conn.cursor()
        
# #         # Get max iterationid from temp table
# #         cur.execute("SELECT COALESCE(MAX(iteration_id), 0) FROM temp.cap_prediction_temp")
# #         max_iteration = cur.fetchone()[0]
# #         iterationid = max_iteration + 1
        
# #         cur.close()
# #         logger.info(f"Using iterationid: {iterationid} for this pipeline run")
# #         return iterationid
        
# #     except Exception as e:
# #         logger.error(f"Failed to get iterationid: {e}")
# #         return 1


# # def execute_models(pod_id, iterationid, stagingid):
# #     """
# #     Run the processing pipeline for stores assigned to this pod.
# #     stagingid is now shared across all batches in this run.
# #     """
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

# #             # Run visicooler analysis
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
# #                 logger.info(f"Visicooler analysis complete: {len(visicooler_records)} records generated")
# #             except Exception as e:
# #                 logger.error(f"Visicooler analysis failed: {e}")
# #                 visicooler_records = []

# #             # Connection closed by visicooler analysis
# #             conn = None
# #             cur = None

# #             # Run Ollama analysis with shared stagingid
# #             logger.info("Starting Ollama analysis")
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
# #                     cyclecountid=cyclecountid,
# #                     stagingid=stagingid
# #                 )
# #                 logger.info(f"Ollama analysis complete: {len(ollama_results)} records generated")
# #             except Exception as e:
# #                 logger.error(f"Ollama analysis failed: {e}")
# #                 logger.error(traceback.format_exc())
# #                 ollama_results, ollama_csv = [], None

# #             # Upload Ollama CSV to S3
# #             if ollama_csv and os.path.exists(ollama_csv):
# #                 logger.info("Uploading Ollama CSV to S3")
# #                 try:
# #                     s3_handler.upload_file_to_s3(
# #                         ollama_csv,
# #                         f"{ollama_config['output_s3_folder']}VisibleItem_{cyclecountid}/analysis_results.csv"
# #                     )
# #                     logger.info("Ollama CSV uploaded successfully")
# #                 except Exception as e:
# #                     logger.error(f"CSV upload failed: {e}")
# #             else:
# #                 logger.warning("No Ollama CSV to upload")

# #             # Update processed_flag to 'Y'
# #             logger.info("Updating processed_flag in database")
# #             try:
# #                 conn, cur = initialize_db_connection(db_config)
# #                 file_uploader = FileUploader(None)
# #                 failed_updates = file_uploader.update_processed_flag(conn, image_paths)
# #                 if failed_updates:
# #                     logger.warning(f"Failed to update {len(failed_updates)} files")
# #                 else:
# #                     logger.info(f"Successfully updated {len(image_paths)} files to processed")
# #             except Exception as e:
# #                 logger.error(f"Update processed_flag failed: {e}")

# #             logger.info("=" * 60)
# #             logger.info(f"BATCH COMPLETE - Pod: {pod_id} (Iteration: {iterationid}, Staging: {stagingid})")
# #             logger.info(f"  Stores processed: {unique_stores}")
# #             logger.info(f"  Images processed: {len(image_paths)}")
# #             logger.info(f"  Visicooler records: {len(visicooler_records)}")
# #             logger.info(f"  Ollama records: {len(ollama_results) if ollama_results else 0}")
# #             logger.info("=" * 60)

# #         return True

# #     except Exception as e:
# #         logger.error(f"Error in execute_models: {e}")
# #         logger.error(traceback.format_exc())
# #         if conn and 'conn' in locals():
# #             try:
# #                 conn.rollback()
# #             except:
# #                 pass
# #         return False
# #     finally:
# #         if conn is not None:
# #             try:
# #                 close_db_connection(conn, cur)
# #             except:
# #                 pass


# # def main():
# #     if len(sys.argv) < 2:
# #         logger.error("Usage: python main.py <pod-id>")
# #         logger.error("Example: python main.py pod-1")
# #         sys.exit(1)
    
# #     pod_id = sys.argv[1]
# #     logger.info(f"Starting pipeline for {pod_id}")
    
# #     config = load_config('config.json')
# #     db_config = config['db_config']
    
# #     # Generate unique IDs once for the entire pipeline run
# #     conn, cur = initialize_db_connection(db_config)
# #     iterationid = get_or_create_iterationid(conn)
    
# #     # Get stagingid once for entire run (all batches will share this)
# #     cur.execute("SELECT MAX(stagingid) FROM orgi.visibilityitemsstaging")
# #     result = cur.fetchone()
# #     stagingid = (result[0] if result[0] is not None else 0) + 1
# #     logger.info(f"Using stagingid: {stagingid} for this entire run")
    
# #     # Clear temp tables once before batch loop
# #     logger.info("=" * 60)
# #     logger.info(f"CLEARING TEMP TABLES (iteration {iterationid})")
# #     logger.info("=" * 60)
# #     try:
# #         cur.execute("DELETE FROM temp.sku_prediction_temp WHERE iteration_id = %s", (iterationid,))
# #         deleted_sku = cur.rowcount
# #         cur.execute("DELETE FROM temp.cap_prediction_temp WHERE iteration_id = %s", (iterationid,))
# #         deleted_cap = cur.rowcount
# #         conn.commit()
# #         logger.info(f"Cleared {deleted_sku} SKU records, {deleted_cap} cap records")
# #         logger.info("Temp tables ready - batches will APPEND data")
# #     except Exception as e:
# #         logger.error(f"Failed to clear temp tables: {e}")
# #         conn.rollback()
    
# #     close_db_connection(conn, cur)
    
# #     logger.info("=" * 60)
# #     logger.info(f"Pipeline Run Configuration:")
# #     logger.info(f"  Iteration ID: {iterationid} (shared across all batches)")
# #     logger.info(f"  Staging ID: {stagingid} (shared across all batches)")
# #     logger.info(f"  Batch data will ACCUMULATE in temp tables")
# #     logger.info("=" * 60)
    
# #     batch_size = None
# #     batch_number = 0
    
# #     while True:
# #         try:
# #             conn, cur = initialize_db_connection(db_config)
            
# #             # Reset stale assignments
# #             reset_count = reset_stale_batches(conn, STALE_TIMEOUT_MINUTES)
            
# #             # Count unprocessed stores
# #             unprocessed_stores = get_unprocessed_store_count(conn)
            
# #             if unprocessed_stores == 0:
# #                 logger.info("=" * 60)
# #                 logger.info("All stores processed successfully")
# #                 logger.info(f"Pipeline Run Complete:")
# #                 logger.info(f"  Iteration ID: {iterationid}")
# #                 logger.info(f"  Staging ID: {stagingid}")
# #                 logger.info(f"  Total batches: {batch_number}")
# #                 logger.info("=" * 60)
# #                 close_db_connection(conn, cur)
# #                 break
            
# #             logger.info("=" * 60)
# #             logger.info(f"Unprocessed stores remaining: {unprocessed_stores}")
# #             logger.info("=" * 60)
            
# #             # Ask for batch size on first iteration
# #             if batch_size is None:
# #                 while True:
# #                     try:
# #                         batch_input = input(f"Enter batch size (stores) for {pod_id} (1-{unprocessed_stores}): ").strip()
# #                         batch_size = int(batch_input)
# #                         if 1 <= batch_size <= unprocessed_stores:
# #                             break
# #                         else:
# #                             print(f"Enter a number between 1 and {unprocessed_stores}")
# #                     except ValueError:
# #                         print("Enter a valid number")
                
# #                 logger.info(f"Batch size set to: {batch_size} stores")
            
# #             # Assign stores to pod
# #             assigned_stores, assigned_files = assign_stores_to_pod(conn, batch_size, pod_id)
# #             close_db_connection(conn, cur)
            
# #             if assigned_stores == 0:
# #                 logger.warning("No stores assigned. Retrying in 10 seconds")
# #                 time.sleep(10)
# #                 continue
            
# #             batch_number += 1
# #             logger.info(f"Starting batch {batch_number}: {assigned_stores} stores, {assigned_files} images")
            
# #             # Process batch with shared IDs
# #             success = execute_models(pod_id, iterationid, stagingid)
            
# #             if not success:
# #                 logger.warning(f"Batch {batch_number} failed. Waiting 10 seconds before retry")
# #                 time.sleep(10)
# #             else:
# #                 logger.info(f"Batch {batch_number} completed successfully. Checking for next batch")
# #                 time.sleep(5)
            
# #         except KeyboardInterrupt:
# #             logger.info("Pipeline interrupted by user")
# #             break
# #         except Exception as e:
# #             logger.error(f"Error in main loop: {e}")
# #             logger.error(traceback.format_exc())
# #             time.sleep(10)
    
# #     logger.info(f"Pipeline execution completed for {pod_id}")


# # if __name__ == "__main__":
# #     main()

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
# from cap_pipeline_runner import run_cap_pipeline


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
#             WHERE (processed_flag IN ('P', '0.0') OR processed_flag IS NULL)
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
#             SET processed_flag = 'P', podid = NULL
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
#     """
#     try:
#         cur = conn.cursor()
        
#         # Get distinct store IDs
#         cur.execute("""
#             SELECT DISTINCT storeid
#             FROM orgi.fileupload
#             WHERE (processed_flag IN ('P', '0.0') OR processed_flag IS NULL)
#               AND storeid IS NOT NULL
#             ORDER BY storeid
#             LIMIT %s
#         """, (store_count,))
        
#         selected_stores = [row[0] for row in cur.fetchall()]
        
#         if not selected_stores:
#             cur.close()
#             return 0, 0
        
#         # Update all images for those stores
#         cur.execute("""
#             UPDATE orgi.fileupload
#             SET processed_flag = 'I', podid = %s
#             WHERE storeid = ANY(%s)
#               AND (processed_flag IN ('P', '0.0') OR processed_flag IS NULL)
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
        
#         # Get max iterationid from temp table
#         cur.execute("SELECT COALESCE(MAX(iteration_id), 0) FROM temp.cap_prediction_temp")
#         max_iteration = cur.fetchone()[0]
#         iterationid = max_iteration + 1
        
#         cur.close()
#         logger.info(f"Using iterationid: {iterationid} for this pipeline run")
#         return iterationid
        
#     except Exception as e:
#         logger.error(f"Failed to get iterationid: {e}")
#         return 1


# def execute_models(pod_id, iterationid, stagingid):
#     """
#     Run the processing pipeline for stores assigned to this pod.
#     stagingid is now shared across all batches in this run.
#     """
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

#             # Get cyclecountid
#             try:
#                 cur.execute("""
#                     SELECT GREATEST(
#                         COALESCE((SELECT MAX(cyclecountid) FROM orgi.visibilitydetails), 0),
#                         COALESCE((SELECT MAX(stagingid) FROM orgi.visibilityitemsstaging), 0)
#                     ) AS max_cycle
#                 """)
#                 row = cur.fetchone()
#                 max_cycle = int(row[0]) if row and row[0] is not None else 0
#                 cyclecountid = max_cycle + 1
#                 logger.info(f"Using cyclecountid: {cyclecountid}")
#             except Exception as e:
#                 logger.error(f"Failed to compute cyclecountid: {e}")
#                 cyclecountid = 1

#             # Run visicooler analysis
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
#                 logger.info(f"Visicooler analysis complete: {len(visicooler_records)} records generated")
#             except Exception as e:
#                 logger.error(f"Visicooler analysis failed: {e}")
#                 visicooler_records = []

#             # Connection closed by visicooler analysis
#             conn = None
#             cur = None

#             # Run Ollama analysis with shared stagingid
#             logger.info("Starting Ollama analysis")
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
#                     cyclecountid=cyclecountid,
#                     stagingid=stagingid
#                 )
#                 logger.info(f"Ollama analysis complete: {len(ollama_results)} records generated")
#             except Exception as e:
#                 logger.error(f"Ollama analysis failed: {e}")
#                 logger.error(traceback.format_exc())
#                 ollama_results, ollama_csv = [], None

#             # Upload Ollama CSV to S3
#             if ollama_csv and os.path.exists(ollama_csv):
#                 logger.info("Uploading Ollama CSV to S3")
#                 try:
#                     s3_handler.upload_file_to_s3(
#                         ollama_csv,
#                         f"{ollama_config['output_s3_folder']}VisibleItem_{cyclecountid}/analysis_results.csv"
#                     )
#                     logger.info("Ollama CSV uploaded successfully")
#                 except Exception as e:
#                     logger.error(f"CSV upload failed: {e}")
#             else:
#                 logger.warning("No Ollama CSV to upload")

#             # Update processed_flag to 'Y'
#             logger.info("Updating processed_flag in database")
#             try:
#                 conn, cur = initialize_db_connection(db_config)
#                 file_uploader = FileUploader(None)
#                 failed_updates = file_uploader.update_processed_flag(conn, image_paths)
#                 if failed_updates:
#                     logger.warning(f"Failed to update {len(failed_updates)} files")
#                 else:
#                     logger.info(f"Successfully updated {len(image_paths)} files to processed")
#             except Exception as e:
#                 logger.error(f"Update processed_flag failed: {e}")

#             logger.info("=" * 60)
#             logger.info(f"BATCH COMPLETE - Pod: {pod_id} (Iteration: {iterationid}, Staging: {stagingid})")
#             logger.info(f"  Stores processed: {unique_stores}")
#             logger.info(f"  Images processed: {len(image_paths)}")
#             logger.info(f"  Visicooler records: {len(visicooler_records)}")
#             logger.info(f"  Ollama records: {len(ollama_results) if ollama_results else 0}")
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
    
#     # Generate unique IDs once for the entire pipeline run
#     conn, cur = initialize_db_connection(db_config)
#     iterationid = get_or_create_iterationid(conn)
    
#     # Get stagingid once for entire run (all batches will share this)
#     cur.execute("SELECT MAX(stagingid) FROM orgi.visibilityitemsstaging")
#     result = cur.fetchone()
#     stagingid = (result[0] if result[0] is not None else 0) + 1
#     logger.info(f"Using stagingid: {stagingid} for this entire run")
    
#     # Clear temp tables once before batch loop
#     logger.info("=" * 60)
#     logger.info(f"CLEARING TEMP TABLES (iteration {iterationid})")
#     logger.info("=" * 60)
#     try:
#         cur.execute("DELETE FROM temp.sku_prediction_temp WHERE iteration_id = %s", (iterationid,))
#         deleted_sku = cur.rowcount
#         cur.execute("DELETE FROM temp.cap_prediction_temp WHERE iteration_id = %s", (iterationid,))
#         deleted_cap = cur.rowcount
#         conn.commit()
#         logger.info(f"Cleared {deleted_sku} SKU records, {deleted_cap} cap records")
#         logger.info("Temp tables ready - batches will APPEND data")
#     except Exception as e:
#         logger.error(f"Failed to clear temp tables: {e}")
#         conn.rollback()
    
#     close_db_connection(conn, cur)
    
#     logger.info("=" * 60)
#     logger.info(f"Pipeline Run Configuration:")
#     logger.info(f"  Iteration ID: {iterationid} (shared across all batches)")
#     logger.info(f"  Staging ID: {stagingid} (shared across all batches)")
#     logger.info(f"  Batch data will ACCUMULATE in temp tables")
#     logger.info("=" * 60)
    
#     batch_size = None
#     batch_number = 0
    
#     while True:
#         try:
#             conn, cur = initialize_db_connection(db_config)
            
#             # Reset stale assignments
#             reset_count = reset_stale_batches(conn, STALE_TIMEOUT_MINUTES)
            
#             # Count unprocessed stores
#             unprocessed_stores = get_unprocessed_store_count(conn)
            
#             if unprocessed_stores == 0:
#                 logger.info("=" * 60)
#                 logger.info("All stores processed successfully")
#                 logger.info(f"Pipeline Run Complete:")
#                 logger.info(f"  Iteration ID: {iterationid}")
#                 logger.info(f"  Staging ID: {stagingid}")
#                 logger.info(f"  Total batches: {batch_number}")
#                 logger.info("=" * 60)
#                 close_db_connection(conn, cur)

#                 # ── CAP Post-Processing Pipeline ──────────────────────────────
#                 logger.info("=" * 60)
#                 logger.info("Starting CAP prediction post-processing pipeline ...")
#                 logger.info("=" * 60)
#                 try:
#                     cap_result = run_cap_pipeline(
#                         db_config=db_config,
#                         iteration_id=iterationid,
#                     )
#                     if cap_result.overall_status != "success":
#                         logger.error(
#                             "CAP pipeline finished with errors – "
#                             "check the summary above for details."
#                         )
#                     else:
#                         logger.info(
#                             f"CAP pipeline completed successfully "
#                             f"in {cap_result.total_duration_ms:.0f} ms."
#                         )
#                 except Exception as e:
#                     logger.error(f"CAP pipeline raised an unexpected exception: {e}")
#                     logger.error(traceback.format_exc())
#                 # ─────────────────────────────────────────────────────────────
#                 break
            
#             logger.info("=" * 60)
#             logger.info(f"Unprocessed stores remaining: {unprocessed_stores}")
#             logger.info("=" * 60)
            
#             # Ask for batch size on first iteration
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
                
#                 logger.info(f"Batch size set to: {batch_size} stores")
            
#             # Assign stores to pod
#             assigned_stores, assigned_files = assign_stores_to_pod(conn, batch_size, pod_id)
#             close_db_connection(conn, cur)
            
#             if assigned_stores == 0:
#                 logger.warning("No stores assigned. Retrying in 10 seconds")
#                 time.sleep(10)
#                 continue
            
#             batch_number += 1
#             logger.info(f"Starting batch {batch_number}: {assigned_stores} stores, {assigned_files} images")
            
#             # Process batch with shared IDs
#             success = execute_models(pod_id, iterationid, stagingid)
            
#             if not success:
#                 logger.warning(f"Batch {batch_number} failed. Waiting 10 seconds before retry")
#                 time.sleep(10)
#             else:
#                 logger.info(f"Batch {batch_number} completed successfully. Checking for next batch")
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
from app.sovi_model import run_sovi_analysis          # NEW
from cap_pipeline_runner import run_cap_pipeline


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
            WHERE (processed_flag IN ('P', '0.0') OR processed_flag IS NULL)
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
            SET processed_flag = 'P', podid = NULL
            WHERE processed_flag = 'I' 
              AND uploadtimestamp < NOW() - INTERVAL '%s minutes'
        """ % stale_timeout_minutes)

        reset_count = cur.rowcount
        conn.commit()
        cur.close()

        if reset_count > 0:
            logger.warning(f"Reset {reset_count} stale files (stuck >{stale_timeout_minutes}m)")

        return reset_count
    except Exception as e:
        logger.error(f"Failed to reset stale batches: {e}")
        conn.rollback()
        return 0


def assign_stores_to_pod(conn, store_count, pod_id):
    """
    Updates processed_flag from 'N' to 'I' and sets podid.
    """
    try:
        cur = conn.cursor()

        # Get distinct store IDs
        cur.execute("""
            SELECT DISTINCT storeid
            FROM orgi.fileupload
            WHERE (processed_flag IN ('P', '0.0') OR processed_flag IS NULL)
              AND storeid IS NOT NULL
            ORDER BY storeid
            LIMIT %s
        """, (store_count,))

        selected_stores = [row[0] for row in cur.fetchall()]

        if not selected_stores:
            cur.close()
            return 0, 0

        # Update all images for those stores
        cur.execute("""
            UPDATE orgi.fileupload
            SET processed_flag = 'I', podid = %s
            WHERE storeid = ANY(%s)
              AND (processed_flag IN ('P', '0.0') OR processed_flag IS NULL)
        """, (pod_id, selected_stores))

        assigned_files  = cur.rowcount
        assigned_stores = len(selected_stores)

        conn.commit()
        cur.close()

        logger.info(f"Assigned {assigned_stores} stores ({assigned_files} images) to {pod_id}")
        return assigned_stores, assigned_files

    except Exception as e:
        logger.error(f"Failed to assign stores to pod: {e}")
        conn.rollback()
        return 0, 0


def get_or_create_iterationid(conn):
    try:
        cur = conn.cursor()

        # Get max iterationid from temp table
        cur.execute("SELECT COALESCE(MAX(iteration_id), 0) FROM temp.cap_prediction_temp")
        max_iteration = cur.fetchone()[0]
        iterationid   = max_iteration + 1

        cur.close()
        logger.info(f"Using iterationid: {iterationid} for this pipeline run")
        return iterationid

    except Exception as e:
        logger.error(f"Failed to get iterationid: {e}")
        return 1


def execute_models(pod_id, iterationid, stagingid):
    """
    Run the full processing pipeline for all stores assigned to this pod.

    Execution order
    ---------------
    1. Download images from S3
    2. run_visicooler_analysis  — category 6, subcategory 605
                                  writes → temp.sku_prediction_temp
                                           temp.cap_prediction_temp
                                  closes DB on exit
    3. run_sovi_analysis        — categories 2/3/4 + category 6 subcat 605
                                  writes → temp.sku_prediction_temp_sovi
                                           temp.cap_prediction_temp_sovi
                                  closes DB on exit
    4. run_ollama_analysis      — extended visibility (categories 605 prompts)
    5. Upload Ollama CSV to S3
    6. Update processed_flag → 'Y'

    stagingid and iterationid are shared across all batches in one run.
    """
    conn = None
    cur  = None

    try:
        config            = load_config('config.json')
        ollama_config     = config['ollama_config']
        s3_config         = config['s3_config']
        db_config         = config['db_config']
        visicooler_config = config['visicooler_config']

        conn, cur = initialize_db_connection(db_config)

        if not check_visibilitydetails_schema(cur):
            logger.error("Schema validation failed for orgi.visibilitydetails")
            return False

        s3_handler = S3Handler(s3_config, db_config)

        with tempfile.TemporaryDirectory() as temp_dir:
            logger.info(f"Created temp directory: {temp_dir}")

            # ------------------------------------------------------------------
            # Step 1 — Download images for stores assigned to this pod
            # ------------------------------------------------------------------
            logger.info(f"Downloading images for {pod_id}...")
            image_paths, failed_files = s3_handler.download_images_from_s3(
                temp_dir, pod_id
            )

            if not image_paths:
                logger.warning(f"No images downloaded for {pod_id}")
                return False

            unique_stores = len(set(img[5] for img in image_paths if img[5]))
            logger.info(
                f"Processing {unique_stores} stores ({len(image_paths)} images)"
            )

            if failed_files:
                logger.warning(f"Failed downloads: {len(failed_files)}")

            # ------------------------------------------------------------------
            # Step 2 — Compute cyclecountid (needs live DB connection)
            # ------------------------------------------------------------------
            try:
                cur.execute("""
                    SELECT GREATEST(
                        COALESCE((SELECT MAX(cyclecountid) FROM orgi.visibilitydetails), 0),
                        COALESCE((SELECT MAX(stagingid)    FROM orgi.visibilityitemsstaging), 0)
                    ) AS max_cycle
                """)
                row        = cur.fetchone()
                max_cycle  = int(row[0]) if row and row[0] is not None else 0
                cyclecountid = max_cycle + 1
                logger.info(f"Using cyclecountid: {cyclecountid}")
            except Exception as e:
                logger.error(f"Failed to compute cyclecountid: {e}")
                cyclecountid = 1

            # ------------------------------------------------------------------
            # Step 3 — Visicooler analysis
            #   • processes subcategory 605 only
            #   • writes to temp.sku_prediction_temp / temp.cap_prediction_temp
            #   • closes the DB connection before returning
            # ------------------------------------------------------------------
            logger.info("=" * 60)
            logger.info(f"STEP 1/3 — Visicooler analysis (iterationid: {iterationid})")
            logger.info("=" * 60)
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
                logger.info(
                    f"Visicooler analysis complete: "
                    f"{len(visicooler_records)} records generated"
                )
            except Exception as e:
                logger.error(f"Visicooler analysis failed: {e}")
                logger.error(traceback.format_exc())
                visicooler_records = []

            # visicooler closes the DB — reflect that here so later steps
            # that check conn/cur see None and reconnect if needed
            conn = None
            cur  = None

            # ------------------------------------------------------------------
            # Step 4 — SOVI analysis
            #   • processes categories 2/3/4 + category 6 subcat 605
            #   • uses same cap model (capmodelnew.pt) as visicooler
            #   • uses new SKU model (dipto.pt) for SKU detection + annotation
            #   • writes to temp.sku_prediction_temp_sovi
            #               temp.cap_prediction_temp_sovi
            #   • closes the DB connection before returning
            # ------------------------------------------------------------------
            logger.info("=" * 60)
            logger.info(f"STEP 2/3 — SOVI analysis (iterationid: {iterationid})")
            logger.info("=" * 60)
            try:
                run_sovi_analysis(
                    image_paths=image_paths,
                    config=config,
                    s3_handler=s3_handler,
                    conn=conn,       # None — sovi_model reconnects internally
                    cur=cur,         # None — sovi_model reconnects internally
                    output_folder_path=visicooler_config['output_folder_path'],
                    cyclecountid=cyclecountid,
                    iterationid=iterationid
                )
                logger.info("SOVI analysis complete")
            except Exception as e:
                logger.error(f"SOVI analysis failed: {e}")
                logger.error(traceback.format_exc())
                # Non-fatal — log and continue to Ollama

            # sovi_model also closes the DB on exit
            conn = None
            cur  = None

            # ------------------------------------------------------------------
            # Step 5 — Ollama analysis
            #   • processes extended-visibility prompts (group1 / group2)
            #   • writes to orgi.visibilityitemsstaging using shared stagingid
            # ------------------------------------------------------------------
            logger.info("=" * 60)
            logger.info("STEP 3/3 — Ollama analysis")
            logger.info("=" * 60)
            try:
                ollama_results, ollama_csv = run_ollama_analysis(
                    image_paths=image_paths,
                    image_folder=temp_dir,
                    output_csv=ollama_config['output_csv'],
                    config_path='config.json',
                    class_ids_path=ollama_config['class_ids_path'],
                    ollama_host=ollama_config['ollama_host'],
                    s3_handler=s3_handler,
                    s3_annotated_folder=(
                        f"{ollama_config['output_s3_folder']}"
                        f"VisibleItem_{cyclecountid}"
                    ),
                    db_config=db_config,
                    cyclecountid=cyclecountid,
                    stagingid=stagingid
                )
                logger.info(
                    f"Ollama analysis complete: "
                    f"{len(ollama_results)} records generated"
                )
            except Exception as e:
                logger.error(f"Ollama analysis failed: {e}")
                logger.error(traceback.format_exc())
                ollama_results, ollama_csv = [], None

            # ------------------------------------------------------------------
            # Step 6 — Upload Ollama CSV to S3
            # ------------------------------------------------------------------
            if ollama_csv and os.path.exists(ollama_csv):
                logger.info("Uploading Ollama CSV to S3")
                try:
                    s3_handler.upload_file_to_s3(
                        ollama_csv,
                        f"{ollama_config['output_s3_folder']}"
                        f"VisibleItem_{cyclecountid}/analysis_results.csv"
                    )
                    logger.info("Ollama CSV uploaded successfully")
                except Exception as e:
                    logger.error(f"CSV upload failed: {e}")
            else:
                logger.warning("No Ollama CSV to upload")

            # ------------------------------------------------------------------
            # Step 7 — Mark images as processed (processed_flag → 'Y')
            # ------------------------------------------------------------------
            logger.info("Updating processed_flag in database")
            try:
                conn, cur = initialize_db_connection(db_config)
                file_uploader  = FileUploader(None)
                failed_updates = file_uploader.update_processed_flag(
                    conn, image_paths
                )
                if failed_updates:
                    logger.warning(
                        f"Failed to update processed_flag for "
                        f"{len(failed_updates)} files"
                    )
                else:
                    logger.info(
                        f"Successfully updated {len(image_paths)} files to processed"
                    )
            except Exception as e:
                logger.error(f"Update processed_flag failed: {e}")

            # ------------------------------------------------------------------
            # Batch summary
            # ------------------------------------------------------------------
            logger.info("=" * 60)
            logger.info(
                f"BATCH COMPLETE — Pod: {pod_id} "
                f"(Iteration: {iterationid}, Staging: {stagingid})"
            )
            logger.info(f"  Stores processed  : {unique_stores}")
            logger.info(f"  Images processed  : {len(image_paths)}")
            logger.info(f"  Visicooler records: {len(visicooler_records)}")
            logger.info(
                f"  Ollama records    : "
                f"{len(ollama_results) if ollama_results else 0}"
            )
            logger.info("=" * 60)

        return True

    except Exception as e:
        logger.error(f"Error in execute_models: {e}")
        logger.error(traceback.format_exc())
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return False

    finally:
        if conn is not None:
            try:
                close_db_connection(conn, cur)
            except Exception:
                pass


def main():
    if len(sys.argv) < 2:
        logger.error("Usage: python main.py <pod-id>")
        logger.error("Example: python main.py pod-1")
        sys.exit(1)

    pod_id = sys.argv[1]
    logger.info(f"Starting pipeline for {pod_id}")

    config    = load_config('config.json')
    db_config = config['db_config']

    # Generate unique IDs once for the entire pipeline run
    conn, cur   = initialize_db_connection(db_config)
    iterationid = get_or_create_iterationid(conn)

    # Get stagingid once for entire run (all batches share this)
    cur.execute("SELECT MAX(stagingid) FROM orgi.visibilityitemsstaging")
    result    = cur.fetchone()
    stagingid = (result[0] if result[0] is not None else 0) + 1
    logger.info(f"Using stagingid: {stagingid} for this entire run")

    # Clear temp tables once before batch loop
    logger.info("=" * 60)
    logger.info(f"CLEARING TEMP TABLES (iteration {iterationid})")
    logger.info("=" * 60)
    try:
        cur.execute(
            "DELETE FROM temp.sku_prediction_temp WHERE iteration_id = %s",
            (iterationid,)
        )
        deleted_sku = cur.rowcount
        cur.execute(
            "DELETE FROM temp.cap_prediction_temp WHERE iteration_id = %s",
            (iterationid,)
        )
        deleted_cap = cur.rowcount

        # Also clear SOVI temp tables for this iteration
        cur.execute(
            "DELETE FROM temp.sku_prediction_temp_sovi WHERE iteration_id = %s",
            (iterationid,)
        )
        deleted_sovi_sku = cur.rowcount
        cur.execute(
            "DELETE FROM temp.cap_prediction_temp_sovi WHERE iteration_id = %s",
            (iterationid,)
        )
        deleted_sovi_cap = cur.rowcount

        conn.commit()
        logger.info(
            f"Cleared {deleted_sku} SKU records, {deleted_cap} cap records "
            f"(visicooler)"
        )
        logger.info(
            f"Cleared {deleted_sovi_sku} SOVI SKU records, "
            f"{deleted_sovi_cap} SOVI cap records"
        )
        logger.info("Temp tables ready — batches will APPEND data")
    except Exception as e:
        logger.error(f"Failed to clear temp tables: {e}")
        conn.rollback()

    close_db_connection(conn, cur)

    logger.info("=" * 60)
    logger.info("Pipeline Run Configuration:")
    logger.info(f"  Iteration ID : {iterationid}  (shared across all batches)")
    logger.info(f"  Staging ID   : {stagingid}  (shared across all batches)")
    logger.info("  Batch data will ACCUMULATE in temp tables")
    logger.info("=" * 60)

    batch_size   = None
    batch_number = 0

    while True:
        try:
            conn, cur = initialize_db_connection(db_config)

            # Reset stale assignments
            reset_stale_batches(conn, STALE_TIMEOUT_MINUTES)

            # Count unprocessed stores
            unprocessed_stores = get_unprocessed_store_count(conn)

            if unprocessed_stores == 0:
                logger.info("=" * 60)
                logger.info("All stores processed successfully")
                logger.info("Pipeline Run Complete:")
                logger.info(f"  Iteration ID  : {iterationid}")
                logger.info(f"  Staging ID    : {stagingid}")
                logger.info(f"  Total batches : {batch_number}")
                logger.info("=" * 60)
                close_db_connection(conn, cur)

                # CAP post-processing pipeline
                logger.info("=" * 60)
                logger.info("Starting CAP prediction post-processing pipeline ...")
                logger.info("=" * 60)
                try:
                    cap_result = run_cap_pipeline(
                        db_config=db_config,
                        iteration_id=iterationid,
                    )
                    if cap_result.overall_status != "success":
                        logger.error(
                            "CAP pipeline finished with errors — "
                            "check the summary above for details."
                        )
                    else:
                        logger.info(
                            f"CAP pipeline completed successfully "
                            f"in {cap_result.total_duration_ms:.0f} ms."
                        )
                except Exception as e:
                    logger.error(
                        f"CAP pipeline raised an unexpected exception: {e}"
                    )
                    logger.error(traceback.format_exc())

                break

            logger.info("=" * 60)
            logger.info(f"Unprocessed stores remaining: {unprocessed_stores}")
            logger.info("=" * 60)

            # Ask for batch size on first iteration
            if batch_size is None:
                while True:
                    try:
                        batch_input = input(
                            f"Enter batch size (stores) for {pod_id} "
                            f"(1-{unprocessed_stores}): "
                        ).strip()
                        batch_size = int(batch_input)
                        if 1 <= batch_size <= unprocessed_stores:
                            break
                        else:
                            print(
                                f"Enter a number between 1 and {unprocessed_stores}"
                            )
                    except ValueError:
                        print("Enter a valid number")

                logger.info(f"Batch size set to: {batch_size} stores")

            # Assign stores to pod
            assigned_stores, assigned_files = assign_stores_to_pod(
                conn, batch_size, pod_id
            )
            close_db_connection(conn, cur)

            if assigned_stores == 0:
                logger.warning("No stores assigned. Retrying in 10 seconds")
                time.sleep(10)
                continue

            batch_number += 1
            logger.info(
                f"Starting batch {batch_number}: "
                f"{assigned_stores} stores, {assigned_files} images"
            )

            # Process batch with shared IDs
            success = execute_models(pod_id, iterationid, stagingid)

            if not success:
                logger.warning(
                    f"Batch {batch_number} failed. Waiting 10 seconds before retry"
                )
                time.sleep(10)
            else:
                logger.info(
                    f"Batch {batch_number} completed successfully. "
                    "Checking for next batch"
                )
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