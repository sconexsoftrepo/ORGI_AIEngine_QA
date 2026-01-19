import os
import boto3
import re
import mimetypes
from botocore.exceptions import ClientError, NoCredentialsError
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class S3Handler:
    def __init__(self, s3_config, db_config):
        self.bucket_name = s3_config['bucket_name']
        self.image_folder_s3 = s3_config['image_folder_s3']
        self.db_config = db_config
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=s3_config['access_key'],
                aws_secret_access_key=s3_config['secret_key'],
                region_name=s3_config['region']
            )
            logger.info(f"Initialized S3 client for bucket: {self.bucket_name}")
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            raise

    def sanitize_filename(self, filename):
        base_filename = os.path.basename(filename)
        base_filename = re.sub(r'\.rf\.[0-9a-fA-F]+$', '', base_filename)
        base_filename = re.sub(r'[\\:*?"<>|]', '', base_filename)
        return base_filename

    def download_images_from_s3(self, temp_dir, pod_id):
        """
        Download all images for stores assigned to this pod.
        Only fetches files where processed_flag = 'I' and podid matches.
        """
        try:
            from app.db_handler import initialize_db_connection, close_db_connection
            conn, cur = initialize_db_connection(self.db_config)

            # Get all images for stores assigned to this pod
            cur.execute(
                """
                SELECT filesequenceid,
                       storename,
                       filename,
                       storeid,
                       subcategory_id,
                       uploadtimestamp AS upload_time
                FROM orgi.fileupload
                WHERE processed_flag = 'I' 
                  AND podid = %s
                ORDER BY storeid, uploadtimestamp ASC
                """,
                (pod_id,)
            )

            image_data = cur.fetchall()
            close_db_connection(conn, cur)

            # Count unique stores
            unique_stores = len(set(row[3] for row in image_data if row[3]))
            logger.info(f"Fetched {len(image_data)} images from {unique_stores} stores for {pod_id}")

            if len(image_data) == 0:
                logger.warning(f"No images found for {pod_id}. Check if batch assignment completed.")

            image_paths = []
            failed_files = []

            for filesequenceid, storename, filename, storeid, subcategory_id, upload_time in image_data:
                try:
                    clean_filename = self.sanitize_filename(filename)
                    local_path = os.path.join(temp_dir, clean_filename)
                    base_filename = os.path.basename(filename)
                    clean_storename = re.sub(
                        r'[\\:*?"<>|]',
                        '',
                        storename.replace(":", ".").strip()
                    )

                    possible_s3_keys = [
                        f"{self.image_folder_s3}{clean_storename}/{base_filename}",
                        f"{self.image_folder_s3}{base_filename}",
                        base_filename,
                    ]

                    downloaded = False

                    for s3_key in possible_s3_keys:
                        try:
                            self.s3_client.download_file(
                                self.bucket_name,
                                s3_key,
                                local_path
                            )
                            logger.debug(f"Downloaded {s3_key} → {local_path}")
                            image_paths.append(
                                (
                                    filesequenceid,
                                    storename,
                                    clean_filename,
                                    local_path,
                                    s3_key,
                                    storeid,
                                    subcategory_id
                                )
                            )
                            downloaded = True
                            break
                        except ClientError as e:
                            if e.response['Error']['Code'] == '404':
                                continue
                            else:
                                logger.error(f"Failed to download {s3_key}: {e}")
                                failed_files.append(
                                    (filesequenceid, storename, filename)
                                )
                                break

                    if not downloaded:
                        logger.warning(
                            f"File not found in S3: {filename}"
                        )
                        failed_files.append(
                            (filesequenceid, storename, filename)
                        )

                except Exception as e:
                    logger.error(f"Error downloading {filename}: {e}")
                    failed_files.append(
                        (filesequenceid, storename, filename)
                    )

            if failed_files:
                logger.warning(f"Failed to download {len(failed_files)} files")

            return image_paths, failed_files

        except Exception as e:
            logger.error(f"Failed to fetch image paths: {e}")
            raise

    def upload_file_to_s3(self, file_path, s3_key):
        """Upload file to S3 with appropriate content type."""
        try:
            content_type, _ = mimetypes.guess_type(file_path)
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type

            self.s3_client.upload_file(
                file_path,
                self.bucket_name,
                s3_key,
                ExtraArgs=extra_args
            )

            logger.debug(f"Uploaded {file_path} to S3: {s3_key}")

        except NoCredentialsError:
            logger.error("Invalid AWS credentials")
            raise
        except ClientError as e:
            logger.error(f"Failed to upload {file_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during S3 upload: {e}")
            raise