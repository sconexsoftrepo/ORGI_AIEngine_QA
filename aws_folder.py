# # import boto3
# # import os

# # # -------- CONFIG --------
# # AWS_ACCESS_KEY = "AKIA6D6JBNORLYOWHTZZ"
# # AWS_SECRET_KEY = "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"
# # REGION = "ap-south-1"

# # BUCKET_NAME = "imageinsightimagesbeverages"
# # TARGET_FOLDER = "STORE_IMAGES"
# # TEMP_FOLDER = "temp_images"

# # IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
# # # ------------------------

# # os.makedirs(TEMP_FOLDER, exist_ok=True)

# # s3 = boto3.client(
# #     "s3",
# #     aws_access_key_id=AWS_ACCESS_KEY,
# #     aws_secret_access_key=AWS_SECRET_KEY,
# #     region_name=REGION
# # )


# # def list_root_images():
# #     paginator = s3.get_paginator("list_objects_v2")

# #     images = []

# #     for page in paginator.paginate(Bucket=BUCKET_NAME):
# #         for obj in page.get("Contents", []):
# #             key = obj["Key"]

# #             # Only files in root
# #             if "/" in key:
# #                 continue

# #             if key.lower().endswith(IMAGE_EXTENSIONS):
# #                 images.append(key)

# #     return images


# # def download_image(key):
# #     local_path = os.path.join(TEMP_FOLDER, key)

# #     s3.download_file(BUCKET_NAME, key, local_path)

# #     print(f"Downloaded: {key}")
# #     return local_path


# # def upload_image(local_path, key):
# #     new_key = f"{TARGET_FOLDER}/{key}"

# #     s3.upload_file(local_path, BUCKET_NAME, new_key)

# #     print(f"Uploaded → {new_key}")


# # def run_pipeline():

# #     images = list_root_images()

# #     print(f"Total images found: {len(images)}")

# #     for key in images:
# #         local_path = download_image(key)

# #         upload_image(local_path, key)

# #         os.remove(local_path)


# # if __name__ == "__main__":
# #     run_pipeline()


# import boto3
# import mimetypes

# # -------- CONFIG --------
# # AWS_ACCESS_KEY = "AKIA6D6JBNORLYOWHTZZ"
# # AWS_SECRET_KEY = "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"
# REGION = "ap-south-1"

# BUCKET_NAME = "imageinsightimagesbeverages"

# IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
# # ------------------------

# s3 = boto3.client(
#     "s3",
#     aws_access_key_id=AWS_ACCESS_KEY,
#     aws_secret_access_key=AWS_SECRET_KEY,
#     region_name=REGION
# )


# def fix_content_type():

#     paginator = s3.get_paginator("list_objects_v2")

#     total = 0

#     for page in paginator.paginate(Bucket=BUCKET_NAME):
#         for obj in page.get("Contents", []):

#             key = obj["Key"]

#             if not key.lower().endswith(IMAGE_EXTENSIONS):
#                 continue

#             content_type = mimetypes.guess_type(key)[0]

#             if content_type is None:
#                 continue

#             print(f"Fixing: {key} -> {content_type}")

#             s3.copy_object(
#                 Bucket=BUCKET_NAME,
#                 CopySource={"Bucket": BUCKET_NAME, "Key": key},
#                 Key=key,
#                 MetadataDirective="REPLACE",
#                 ContentType=content_type
#             )

#             total += 1

#     print(f"\nFinished. Fixed {total} images.")


# if __name__ == "__main__":
#     fix_content_type()



import boto3
import mimetypes
from concurrent.futures import ThreadPoolExecutor, as_completed

# -------- CONFIG --------
AWS_ACCESS_KEY = "AKIA6D6JBNORLYOWHTZZ"
AWS_SECRET_KEY = "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"
REGION = "ap-south-1"
BUCKET_NAME = "imageinsightimagesbeverages"
STORE_FOLDER = "STORE_IMAGES"

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

MAX_WORKERS = 20
# ------------------------

s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=REGION
)


def list_root_images():
    paginator = s3.get_paginator("list_objects_v2")
    images = []

    for page in paginator.paginate(Bucket=BUCKET_NAME):
        for obj in page.get("Contents", []):

            key = obj["Key"]

            # only root files
            if "/" in key:
                continue

            if key.lower().endswith(IMAGE_EXTENSIONS):
                images.append(key)

    return images


def fix_store_image(img):

    store_key = f"{STORE_FOLDER}/{img}"
    content_type = mimetypes.guess_type(img)[0]

    if not content_type:
        return None

    try:
        s3.copy_object(
            Bucket=BUCKET_NAME,
            CopySource={"Bucket": BUCKET_NAME, "Key": store_key},
            Key=store_key,
            MetadataDirective="REPLACE",
            ContentType=content_type,
            ContentDisposition="inline"
        )

        return store_key

    except Exception:
        return None


def run_pipeline():

    root_images = list_root_images()

    print(f"\nRoot images found: {len(root_images)}\n")

    processed = 0

    with ThreadPoolExecutor(MAX_WORKERS) as executor:

        futures = [executor.submit(fix_store_image, img) for img in root_images]

        for future in as_completed(futures):

            result = future.result()

            if result:
                processed += 1
                print(f"Fixed: {result}")

    print(f"\nFinished fixing {processed} images.")


if __name__ == "__main__":
    run_pipeline()



