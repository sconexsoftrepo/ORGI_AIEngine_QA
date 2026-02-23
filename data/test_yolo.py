# from ultralytics import YOLO
# import easyocr
# import cv2
# import pandas as pd
# import os

# # -----------------------------
# # Config
# # -----------------------------
# MODEL_PATH = "activation_best.pt"
# IMAGE_SOURCE = "test_images"

# CONF_THRESHOLD = 0.25
# IOU_THRESHOLD = 0.5

# # Your actual Coca-Cola related classes
# COCO_COLA_CLASSES = ["dps"]

# TARGET_BRAND_TEXT = "coca cola"

# # -----------------------------
# # Load YOLO
# # -----------------------------
# model = YOLO(MODEL_PATH)

# # -----------------------------
# # Run YOLO
# # -----------------------------
# results = model.predict(
#     source=IMAGE_SOURCE,
#     conf=CONF_THRESHOLD,
#     iou=IOU_THRESHOLD,
#     save=True,
#     device="cpu"
# )

# print("YOLO prediction completed")

# # -----------------------------
# # Init OCR
# # -----------------------------
# reader = easyocr.Reader(['en'], gpu=False)

# # -----------------------------
# # CSV rows
# # -----------------------------
# rows = []

# # -----------------------------
# # Process each image
# # -----------------------------
# for r in results:
#     predicted_class = ""
#     brand = ""
#     image_name = os.path.basename(r.path)   # ✅ NEW

#     if r.boxes is not None and len(r.boxes.cls) > 0:
#         cls_id = int(r.boxes.cls[0])
#         predicted_class = r.names[cls_id]

#         # If YOLO says DPS → Coca-Cola product
#         if predicted_class.lower() in COCO_COLA_CLASSES:
#             brand = "coco cola"

#             # OCR (optional, just for confirmation/logging)
#             image = cv2.imread(r.path)
#             if image is not None:
#                 ocr_results = reader.readtext(image, detail=0)
#                 ocr_text = " ".join(ocr_results).lower()

#                 if TARGET_BRAND_TEXT in ocr_text:
#                     print(f"Brand text found in {image_name}")

#     rows.append({
#         "image_name": image_name,      # ✅ NEW
#         "predicted_class": predicted_class,
#         "brand": brand
#     })

# # -----------------------------
# # Save CSV
# # -----------------------------
# df = pd.DataFrame(rows, columns=["image_name", "predicted_class", "brand"])
# df.to_csv("prediction_results.csv", index=False)

# print("\nCSV saved: prediction_results.csv")
# print(df)

import easyocr
import cv2
import pandas as pd
import os
import glob
import re
from rapidfuzz import fuzz

# -----------------------------
# Config
# -----------------------------
IMAGE_FOLDER = "test_images"
OUTPUT_CSV = "ocr_results_with_brand.csv"

TARGET_BRAND = "coca cola"
FUZZY_THRESHOLD = 70   # 0–100, higher = stricter

# -----------------------------
# Init EasyOCR
# -----------------------------
reader = easyocr.Reader(['en'], gpu=False)

# -----------------------------
# Helpers
# -----------------------------
def normalize_text(text):
    text = text.lower()
    text = re.sub(r"[^a-z\s]", " ", text)  # remove junk chars
    text = re.sub(r"\s+", " ", text).strip()
    return text

def is_probable_coca_cola(ocr_text):
    normalized = normalize_text(ocr_text)

    # Compare against sliding windows of words
    words = normalized.split()

    for i in range(len(words)):
        for j in range(i + 1, min(i + 4, len(words)) + 1):
            phrase = " ".join(words[i:j])
            score = fuzz.ratio(phrase, TARGET_BRAND)
            if score >= FUZZY_THRESHOLD:
                return True, score

    return False, 0

# -----------------------------
# OCR + NLP
# -----------------------------
rows = []

for img_path in glob.glob(os.path.join(IMAGE_FOLDER, "*")):
    image_name = os.path.basename(img_path)
    print(f"Running OCR on: {image_name}")

    image = cv2.imread(img_path)
    if image is None:
        continue

    ocr_results = reader.readtext(image, detail=0)
    ocr_text = " ".join(ocr_results)

    matched, score = is_probable_coca_cola(ocr_text)

    rows.append({
        "image_name": image_name,
        "ocr_text": ocr_text,
        "matched_brand": "coco cola" if matched else "",
        "match_score": score if matched else ""
    })

# -----------------------------
# Save CSV
# -----------------------------
df = pd.DataFrame(
    rows,
    columns=["image_name", "ocr_text", "matched_brand", "match_score"]
)

df.to_csv(OUTPUT_CSV, index=False)

print(f"\nOCR + NLP matching completed. CSV saved as: {OUTPUT_CSV}")
print(df)
