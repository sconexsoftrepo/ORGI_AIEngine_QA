import requests
import base64
import copy
import csv
import json
import logging
import os
import tempfile
import time
from collections import defaultdict
from datetime import datetime

import requests
from ultralytics import YOLO
from app.config_loader import load_config, load_json_classes
from app.db_handler import (
    close_db_connection,
    get_classtext,
    insert_ollama_results,
)

# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_VISICOOLER_SUBCATS = {601, 602, 603, 604, 605}

# ---------------------------------------------------------------------------
# Activation YOLO — singleton, lazy-loaded once per process
# ---------------------------------------------------------------------------
_ACTIVATION_YOLO = None
_GPT_QUOTA_EXHAUSTED = False


def get_activation_yolo(model_path):
    global _ACTIVATION_YOLO
    if _ACTIVATION_YOLO is None:
        logger.info(f"Loading activation YOLO: {model_path}")
        _ACTIVATION_YOLO = YOLO(model_path)
    return _ACTIVATION_YOLO


# ---------------------------------------------------------------------------
# ACTIVATION_MAPPINGS — YOLO class names → Class IDs
# ---------------------------------------------------------------------------
ACTIVATION_MAPPINGS = {
    "3_tier_rack"                               : 1078,
    "assp_countertop"                           : 1079,
    "aerial_hanger"                             : 1043,
    "box_display"                               : 1080,
    "ceiling_pillar_branding"                   : 1081,
    "combo_board"                               : 1022,
    "counter_front"                             : 1082,
    "countertop_filled_bottle"                  : 1061,
    "crate_cover"                               : 1054,
    "dps"                                       : 1053,
    "dangler"                                   : 1083,
    "flange"                                    : 1057,
    "foam_banner"                               : 1084,
    "front_window_branding"                     : 1085,
    "led_wall_or_shelf_mount_element"           : 1086,
    "mt_rack_display"                           : 1087,
    "menu_board"                                : 1023,
    "neck_ringer"                               : 1018,
    "neon_signage"                              : 1034,
    "offer_ribbon_sticker"                      : 1088,
    "one_pager_combo_menu"                      : 1089,
    "pet_floor_stacking"                        : 1075,
    "pet_rack"                                  : 1076,
    "pillar_branding"                           : 1040,
    "poster"                                    : 1019,
    "rgb_countertop"                            : 1074,
    "rgb_crate_stacking"                        : 1056,
    "shelf_display"                             : 1064,
    "shelf_display_mt"                          : 1091,
    "shopper_gate"                              : 1092,
    "standee"                                   : 1059,
    "steamer"                                   : 1020,
    "table_sticker"                             : 1027,
    "umbrella"                                  : 1093,
    "waiter_apron"                              : 1036,
    "wall_branding"                             : 1094,
    "warm_display_of_3_bottles_at_visible_place": 1095,
    "window_display"                            : 1055,
    "wobbler"                                   : 1063,
    "cooler_strips"                             : 1096,
    "flane"                                     : 1057,   # typo duplicate of flange
    "shelf_branding"                            : 1097,
    "well_branding"                             : 1094,   # typo duplicate of wall_branding
}

# ---------------------------------------------------------------------------
# UNMAPPED_YOLO_NAMES — trigger GPT fallback; NOT inserted as YOLO results
# ---------------------------------------------------------------------------
UNMAPPED_YOLO_NAMES = {
    "others",   # generic catch-all → triggers GPT fallback
}

# ---------------------------------------------------------------------------
# SILENTLY_IGNORED — discard silently, no GPT fallback
# ---------------------------------------------------------------------------
SILENTLY_IGNORED = {
    "offe",     # truncated typo class → discard completely
}

# ---------------------------------------------------------------------------
# GPT_CLASS_MAP — GPT returns class_name strings → class IDs
# ---------------------------------------------------------------------------
GPT_CLASS_MAP = {
    "POSTER"                                    : 1019,
    "STREAMER"                                  : 1020,
    "DANGLER"                                   : 1083,
    "WOBBLER"                                   : 1063,
    "WALL_BRANDING"                             : 1094,
    "TABLE_STICKER"                             : 1027,
    "DPS"                                       : 1053,
    "RGB_CRATE_STACKING"                        : 1056,
    "FRONT_WINDOW_BRANDING"                     : 1085,
    "CEILING_PILLAR_BRANDING"                   : 1081,
    "PILLAR_BRANDING"                           : 1040,
    "COUNTER_FRONT"                             : 1082,
    "SHELF_RACK_BRANDING"                       : 1097,
    "OFFER_RIBBON_STICKER"                      : 1088,
    "MT_RACK_DISPLAY"                           : 1087,
    "SHOPPER_GATE"                              : 1092,
    "LED_ELEMENT"                               : 1086,
    "SHELF_DISPLAY_MT"                          : 1091,
    "NECK_RINGER"                               : 1018,
    "BOX_DISPLAY"                               : 1080,
    "COOLER_STRIPS"                             : 1096,
    "FOAM_BANNER"                               : 1084,
    "COMBO_BOARD"                               : 1022,
    "MENU_BOARD"                                : 1023,
    "NEON_SIGNAGE"                              : 1034,
    "WAITER_APRON"                              : 1036,
    "AERIAL_HANGER"                             : 1043,
    "CRATE_COVER"                               : 1054,
    "WINDOW_DISPLAY"                            : 1055,
    "FLANGE"                                    : 1057,
    "STANDEE"                                   : 1059,
    "COUNTERTOP_FILLED_BOTTLE"                  : 1061,
    "RGB_COUNTERTOP"                            : 1074,
    "PET_FLOOR_STACKING"                        : 1075,
    "PET_RACK"                                  : 1076,
    "COUNTERTOP_DISPLAY"                        : 1077,
    "3_TIER_RACK"                               : 1078,
    "ASSP_COUNTERTOP"                           : 1079,
    "ONE_PAGER_COMBO_MENU"                      : 1089,
    "SHELF_DISPLAY"                             : 1064,
    "UMBRELLA"                                  : 1093,
    "WARM_DISPLAY_OF_3_BOTTLES_AT_VISIBLE_PLACE": 1095,
    "SHELF_BRANDING"                            : 1097,
}


# ---------------------------------------------------------------------------
# run_activation_yolo
# ---------------------------------------------------------------------------
def run_activation_yolo(image_path, model_path, conf_threshold=0.3, unmapped_names=None):
    """
    Run the activation YOLO model on one image.

    Returns
    -------
    detected        : set[str]
        All detected lowercase+underscored class names (including unmapped).
    annot_bgr       : np.ndarray | None
        BGR annotated frame with only *mapped* boxes drawn.
    others_detected : bool
        True if any unmapped class (others, etc.) appeared in detections.
    """
    if unmapped_names is None:
        unmapped_names = UNMAPPED_YOLO_NAMES

    all_excluded = unmapped_names | SILENTLY_IGNORED

    model     = get_activation_yolo(model_path)
    results   = model(image_path, conf=conf_threshold, verbose=False)
    detected  = set()
    annot_bgr = None

    for r in results:
        for cls in r.boxes.cls:
            raw_name   = model.names[int(cls)]
            class_name = raw_name.lower().replace(" ", "_")
            detected.add(class_name)
            logger.info(
                f"  [YOLO] detected '{class_name}' (raw='{raw_name}') "
                f"in {os.path.basename(image_path)}"
            )

        # Build annotated image with unmapped/ignored boxes removed
        try:
            r_clean  = copy.deepcopy(r)
            keep_idx = [
                i for i, c in enumerate(r_clean.boxes.cls)
                if model.names[int(c)].lower().replace(" ", "_") not in all_excluded
            ]

            if keep_idx:
                import torch
                r_clean.boxes = r_clean.boxes[torch.tensor(keep_idx, dtype=torch.long)]
                annot_bgr     = r_clean.plot()
            else:
                try:
                    import cv2 as _cv2
                    annot_bgr = _cv2.imread(image_path)
                except Exception:
                    annot_bgr = None
        except Exception as plot_err:
            logger.debug(f"  YOLO .plot() failed: {plot_err}")
            annot_bgr = None

    others_detected = bool(detected & unmapped_names)
    return detected, annot_bgr, others_detected


# ---------------------------------------------------------------------------
# call_gpt_vision
# ---------------------------------------------------------------------------
def call_gpt_vision(image_path, prompt_text, chatgpt_config, max_retries=5, base_delay=2.0):
    """
    Send one image to GPT-4o vision API with exponential backoff on 429.

    Returns
    -------
    list of dicts: [{"class_name": str, "class_id": int, "confidence": int, "value": str}, ...]
    Only entries with confidence >= 40.  Empty list on any error.
    """
    global _GPT_QUOTA_EXHAUSTED
    if _GPT_QUOTA_EXHAUSTED:
        logger.warning(f"  GPT skipped (quota exhausted): {os.path.basename(image_path)}")
        return []

    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        ext = os.path.splitext(image_path)[1].lower().lstrip(".")
        media_type_map = {
            "jpg" : "image/jpeg",
            "jpeg": "image/jpeg",
            "png" : "image/png",
            "webp": "image/webp",
            "gif" : "image/gif",
        }
        media_type = media_type_map.get(ext, "image/jpeg")

        payload = {
            "model"      : chatgpt_config["model"],
            "max_tokens" : chatgpt_config["max_tokens"],
            "temperature": chatgpt_config["temperature"],
            "messages"   : [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url"   : f"data:{media_type};base64,{b64_image}",
                                "detail": chatgpt_config.get("image_detail", "auto"),
                            },
                        },
                    ],
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {chatgpt_config['api_key']}",
            "Content-Type" : "application/json",
        }

        response = None
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )

                if response.status_code == 429:
                    logger.warning(f"  GPT 429 response body: {response.text}")
                    try:
                        err_code = response.json().get("error", {}).get("code", "")
                        if err_code == "insufficient_quota":
                            _GPT_QUOTA_EXHAUSTED = True
                            logger.error(
                                "  GPT: OpenAI quota exhausted — skipping all further GPT calls."
                            )
                            return []
                    except Exception:
                        pass

                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        wait = float(retry_after)
                    else:
                        wait = base_delay * (2 ** (attempt - 1))

                    logger.warning(
                        f"  GPT 429 (attempt {attempt}/{max_retries}) — "
                        f"backing off {wait:.1f}s for {os.path.basename(image_path)}"
                    )

                    if attempt == max_retries:
                        logger.error(f"  GPT: max retries exhausted for {os.path.basename(image_path)}")
                        return []

                    time.sleep(wait)
                    continue

                response.raise_for_status()
                break

            except requests.exceptions.Timeout:
                logger.warning(
                    f"  GPT timeout (attempt {attempt}/{max_retries}) for "
                    f"{os.path.basename(image_path)}"
                )
                if attempt == max_retries:
                    logger.error("  GPT: max retries exhausted after timeouts.")
                    return []
                time.sleep(base_delay * (2 ** (attempt - 1)))

        if response is None:
            logger.error(f"  GPT: no response obtained for {os.path.basename(image_path)}")
            return []

        response_text = response.json()["choices"][0]["message"]["content"]

        if response_text is None:
            logger.warning(f"  GPT returned null content for {os.path.basename(image_path)} — skipping.")
            return []

        clean_text = response_text.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("```")[1]
            if clean_text.startswith("json"):
                clean_text = clean_text[4:]

        detections_json = json.loads(clean_text.strip())
        raw_detections  = detections_json["detections"]

        results = []
        for d in raw_detections:
            class_name = d.get("class_name", "")
            result_val = d.get("result", "N")
            confidence = d.get("confidence", 0)

            if class_name not in GPT_CLASS_MAP:
                logger.debug(f"  GPT unknown class '{class_name}' — skipped")
                continue

            if result_val == "Y" and confidence < 40:
                logger.debug(f"  GPT '{class_name}' is Y but confidence {confidence} < 40 — skipped")
                continue

            results.append({
                "class_name": class_name,
                "class_id"  : GPT_CLASS_MAP[class_name],
                "confidence": int(confidence),
                "value"     : result_val,
            })

        y_count = sum(1 for r in results if r["value"] == "Y")
        n_count = sum(1 for r in results if r["value"] == "N")
        logger.info(
            f"  GPT vision: {len(raw_detections)} raw → "
            f"{y_count} Y, {n_count} N for {os.path.basename(image_path)}"
        )
        return results

    except Exception as e:
        logger.error(
            f"  call_gpt_vision failed for {os.path.basename(image_path)}: {e}",
            exc_info=True,
        )
        return []


# ---------------------------------------------------------------------------
# process_single_image
# ---------------------------------------------------------------------------
def process_single_image(
    image_info,
    activation_yolo_model,
    activation_conf_threshold,
    class_ids,
    s3_handler,
    s3_annotated_folder,
    classtext_cache,
    modelname="yolo_activation",
):
    """
    Run YOLO on one image and build result rows.

    Returns
    -------
    results        : list[dict]   — result rows for DB/CSV
    mapped_ids     : set[int]     — mapped class IDs detected
    others_detected: bool         — True if 'others' (unmapped) class appeared
    zero_detection : bool         — True if no mapped classes were found
    annot_bgr      : ndarray|None
    """
    fileseqid, storename, filename, local_path, s3_key, storeid, subcategory_id = image_info

    if subcategory_id in _VISICOOLER_SUBCATS:
        logger.debug(f"  Skipping visicooler subcategory {subcategory_id}: {filename}")
        return [], set(), False, True, None

    if not os.path.exists(local_path):
        logger.warning(f"  Local file missing, skipping: {local_path}")
        return [], set(), False, True, None

    results         = []
    mapped_ids      = set()
    others_detected = False
    annot_bgr       = None

    try:
        logger.info(f"Processing: {filename}")

        yolo_output = {}

        if activation_yolo_model:
            activation_detected, annot_bgr, others_detected = run_activation_yolo(
                local_path, activation_yolo_model, activation_conf_threshold
            )

            for detected_name in activation_detected:
                if detected_name in ACTIVATION_MAPPINGS:
                    cid = str(ACTIVATION_MAPPINGS[detected_name])
                    yolo_output[cid] = "Y"
                    logger.info(f"  → YOLO mapped '{detected_name}' → class {cid} = Y")
                elif detected_name in UNMAPPED_YOLO_NAMES:
                    logger.info(f"  → YOLO '{detected_name}' is unmapped — GPT fallback eligible")
                elif detected_name in SILENTLY_IGNORED:
                    logger.info(f"  → YOLO '{detected_name}' silently ignored")
                else:
                    logger.warning(
                        f"  → YOLO '{detected_name}' has NO mapping — "
                        f"treating as unmapped. Add to ACTIVATION_MAPPINGS if needed."
                    )
        else:
            logger.warning(f"  No YOLO model configured — skipping {filename}")

        # Build result rows
        now      = datetime.now()
        s3_annot = f"{s3_annotated_folder}/{filename}"
        rowid    = 1  # globally unique rowids assigned later in run_yolo_analysis

        seen_classids = set()
        for cid, val in yolo_output.items():
            # YOLO-mapped classes are always valid — ACTIVATION_MAPPINGS is the
            # authoritative source. class_ids.json may be stale and miss newer
            # class IDs (1054-1097), so we skip the filter for YOLO results.
            # (class_ids filter still applies to GPT results below.)
            int_cid = int(cid)
            if int_cid in seen_classids:
                logger.warning(f"  Duplicate classid {int_cid} for {filename} — skipping extra row")
                continue
            seen_classids.add(int_cid)
            mapped_ids.add(int_cid)
            results.append({
                "rowid"                : rowid,
                "modelname"            : modelname,
                "imagefilename"        : filename,
                "classid"              : int_cid,
                "classtext"            : classtext_cache.get(int_cid, "Unknown"),
                "value"                : val,
                "inference"            : 1.0,
                "modelrun"             : now,
                "processed_flag"       : "N",
                "storeid"              : storeid,
                "storename"            : storename,
                "s3path_actual_file"   : s3_key,
                "s3path_annotated_file": s3_annot,
            })
            rowid += 1

        zero_detection = len(mapped_ids) == 0

        # Upload annotated image to S3
        try:
            if annot_bgr is not None:
                import cv2 as _cv2
                ext = os.path.splitext(filename)[1] or ".jpg"
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp_path = tmp.name
                try:
                    encode_ok = _cv2.imwrite(tmp_path, annot_bgr)
                    if encode_ok:
                        s3_handler.upload_file_to_s3(tmp_path, s3_annot)
                        logger.info(f"  Uploaded YOLO-annotated image → {s3_annot}")
                    else:
                        logger.warning("  cv2.imwrite failed; uploading original image")
                        s3_handler.upload_file_to_s3(local_path, s3_annot)
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
            else:
                s3_handler.upload_file_to_s3(local_path, s3_annot)
                logger.info(f"  Uploaded original image as annotated → {s3_annot}")
        except Exception as upload_err:
            logger.warning(f"  S3 upload failed for {filename}: {upload_err}")

    except Exception as e:
        logger.error(f"  Error processing {filename}: {e}", exc_info=True)
        zero_detection = True

    return results, mapped_ids, others_detected, zero_detection, annot_bgr


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run_yolo_analysis(
    image_paths,
    image_folder,
    output_csv,
    config_path,
    class_ids_path,
    s3_handler,
    s3_annotated_folder,
    db_config,
    cyclecountid,
    stagingid,
):
    """
    End-to-end YOLO + GPT fallback analysis pipeline.

    GPT fallback logic (simplified):
      - Per image: if YOLO found zero mapped detections OR only 'others' class
        was detected → send that image to GPT.
      - No store-type/threshold scoring involved.
    """
    import pg8000.dbapi as pg

    # 1. Load config
    config      = load_config(config_path)
    ollama_cfg  = config.get("ollama_config", {})
    chatgpt_cfg = config.get("chatgpt_config", {})

    activation_yolo_model     = ollama_cfg.get("activation_yolo_model")
    activation_conf_threshold = float(ollama_cfg.get("activation_conf_threshold", 0.3))
    output_csv                = ollama_cfg.get("output_csv", output_csv)
    modelname                 = "yolo_activation"

    if not activation_yolo_model:
        logger.error(
            "No 'activation_yolo_model' found in ollama_config. "
            "Add the model path to config.json."
        )
        return [], None

    # Load GPT prompt
    prompt_text  = ""
    prompt_file  = chatgpt_cfg.get("prompt_file", "")
    if prompt_file and os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as pf:
            prompt_text = pf.read()
        logger.info(f"GPT prompt loaded from {prompt_file}")
    else:
        logger.warning(
            f"GPT prompt file not found at '{prompt_file}' — "
            "GPT fallback will be skipped."
        )

    gpt_available = bool(prompt_text and chatgpt_cfg.get("api_key"))

    logger.info(
        f"YOLO+GPT Analyzer | yolo_model={activation_yolo_model} "
        f"| conf={activation_conf_threshold} | stagingid={stagingid} "
        f"| gpt_available={gpt_available}"
    )

    # 2. Load class IDs
    class_ids = load_json_classes(class_ids_path)

    # 3. Pre-fetch classtext; close DB before inference
    conn = pg.connect(
        host=db_config["host"],
        port=db_config["port"],
        database=db_config["database"],
        user=db_config["user"],
        password=db_config["password"],
    )
    cur = conn.cursor()
    logger.info("DB connected (classtext pre-fetch)")

    classtext_cache = {}
    for cid in range(1018, 1098):
        classtext_cache[cid] = get_classtext(cur, cid)

    close_db_connection(conn, cur)
    logger.info("DB closed before inference")

    # 4. Filter images (skip visicooler subcategories and missing files)
    images_to_process = [
        img for img in image_paths
        if img[6] not in _VISICOOLER_SUBCATS and os.path.exists(img[3])
    ]
    total_images = len(images_to_process)
    logger.info(f"Processing {total_images} images")

    all_results          = []
    gpt_triggered_images = 0
    total_gpt_rows       = 0

    # 5. MAIN IMAGE LOOP — YOLO first, then per-image GPT decision
    for image_info in images_to_process:
        fileseqid, storename, filename, local_path, s3_key, storeid, subcategory_id = image_info

        # 5A. Run YOLO
        yolo_rows, mapped_ids, others_det, zero_det, annot_bgr = process_single_image(
            image_info,
            activation_yolo_model,
            activation_conf_threshold,
            class_ids,
            s3_handler,
            s3_annotated_folder,
            classtext_cache,
            modelname=modelname,
        )

        # Collect YOLO rows
        yolo_inserted_keys = set()
        for row in yolo_rows:
            all_results.append(row)
            yolo_inserted_keys.add((row["imagefilename"], row["classid"]))

        # 5B. GPT fallback decision — image level only
        #
        # Trigger GPT if:
        #   (a) YOLO found zero mapped detections, OR
        #   (b) YOLO found only 'others' (unmapped) class — zero_det is True
        #       because others never populates mapped_ids
        #
        # Skip GPT if YOLO found at least one mapped class.
        needs_gpt = zero_det or others_det

        if needs_gpt:
            if not gpt_available:
                logger.warning(
                    f"  GPT fallback needed for {filename} but GPT is unavailable "
                    f"(missing api_key or prompt_file) — skipping."
                )
            else:
                gpt_triggered_images += 1
                reason = "zero detections" if zero_det and not others_det else \
                         "'others' class detected" if others_det and not zero_det else \
                         "zero detections + 'others' class"
                logger.info(f"  GPT fallback triggered for {filename} — reason: {reason}")

                gpt_detections = call_gpt_vision(local_path, prompt_text, chatgpt_cfg)
                time.sleep(3)  # brief pause to avoid rate limits

                now      = datetime.now()
                s3_annot = f"{s3_annotated_folder}/{filename}"

                for detection in gpt_detections:
                    cid     = detection["class_id"]
                    conf    = detection["confidence"]
                    det_val = detection["value"]

                    # Only block if YOLO already inserted a Y for this class.
                    # N rows are never blocked — YOLO never inserts N rows.
                    if det_val == "Y" and (filename, cid) in yolo_inserted_keys:
                        logger.info(f"  GPT dedup skip: {filename} classid={cid} already Y from YOLO")
                        continue

                    gpt_row = {
                        "rowid"                : 1,   # reassigned globally below
                        "modelname"            : "gpt_activation",
                        "imagefilename"        : filename,
                        "classid"              : cid,
                        "classtext"            : classtext_cache.get(cid, "Unknown"),
                        "value"                : det_val,
                        "inference"            : conf / 100.0 if conf > 0 else 1.0,
                        "modelrun"             : now,
                        "processed_flag"       : "N",
                        "storeid"              : storeid,
                        "storename"            : storename,
                        "s3path_actual_file"   : s3_key,
                        "s3path_annotated_file": s3_annot,
                    }
                    all_results.append(gpt_row)

                    if det_val == "Y":
                        yolo_inserted_keys.add((filename, cid))

                    total_gpt_rows += 1

                # Upload original image annotated path for GPT-processed images
                try:
                    s3_handler.upload_file_to_s3(local_path, s3_annot)
                    logger.info(f"  GPT: uploaded original image → {s3_annot}")
                except Exception as upload_err:
                    logger.warning(f"  GPT S3 upload failed for {filename}: {upload_err}")
        else:
            logger.info(f"  GPT skipped for {filename} — YOLO found {len(mapped_ids)} mapped class(es)")

    # 6. Statistics
    yolo_rows_count = sum(1 for r in all_results if r.get("modelname") == "yolo_activation")
    gpt_rows_count  = sum(1 for r in all_results if r.get("modelname") == "gpt_activation")

    logger.info("=" * 60)
    logger.info("YOLO + GPT ANALYZER STATISTICS:")
    logger.info(f"  Total images processed    : {total_images}")
    logger.info(f"  Images GPT triggered      : {gpt_triggered_images}")
    logger.info(f"  YOLO result rows          : {yolo_rows_count}")
    logger.info(f"  GPT result rows           : {gpt_rows_count}")
    logger.info(f"  Total result rows         : {len(all_results)}")
    logger.info(f"  stagingid                 : {stagingid}")
    logger.info("=" * 60)

    # 7. Reopen DB; fetch max rowid + already-inserted pairs for cross-batch dedup
    conn = pg.connect(
        host=db_config["host"],
        port=db_config["port"],
        database=db_config["database"],
        user=db_config["user"],
        password=db_config["password"],
    )
    cur = conn.cursor()

    try:
        cur.execute("SELECT 1")
    except Exception as e:
        logger.warning(f"DB ping failed, reconnecting: {e}")
        close_db_connection(conn, cur)
        conn = pg.connect(
            host=db_config["host"],
            port=db_config["port"],
            database=db_config["database"],
            user=db_config["user"],
            password=db_config["password"],
        )
        cur = conn.cursor()

    cur.execute(
        "SELECT COALESCE(MAX(rowid), 0) FROM orgi.visibilityitemsstaging WHERE stagingid = %s",
        (stagingid,),
    )
    max_existing_rowid = int(cur.fetchone()[0])
    logger.info(
        f"Max existing rowid for stagingid {stagingid}: {max_existing_rowid} "
        f"— new rows start from {max_existing_rowid + 1}"
    )

    # 8. Cross-batch duplicate guard
    cur.execute(
        "SELECT imagefilename, classid, value FROM orgi.visibilityitemsstaging WHERE stagingid = %s",
        (stagingid,),
    )
    already_inserted = {
        (row[0], int(row[1])): row[2]
        for row in cur.fetchall()
    }
    if already_inserted:
        logger.info(
            f"Cross-batch dedup: {len(already_inserted)} (image, classid) pairs "
            f"already in DB for stagingid {stagingid}"
        )

    deduped_results = []
    skipped_dupes   = 0
    for r in all_results:
        key          = (r["imagefilename"], r["classid"])
        existing_val = already_inserted.get(key)

        if existing_val is None:
            deduped_results.append(r)
            already_inserted[key] = r["value"]
        elif existing_val == "Y":
            skipped_dupes += 1
            logger.debug(f"  Cross-batch skip: {key} already Y in DB")
        elif existing_val == "N" and r["value"] == "Y":
            deduped_results.append(r)
            already_inserted[key] = "Y"
            logger.info(f"  Cross-batch upgrade: {key} was N in DB, now inserting Y")
        else:
            skipped_dupes += 1
            logger.debug(f"  Cross-batch skip: {key} already N in DB, incoming also N")

    if skipped_dupes:
        logger.warning(f"Skipped {skipped_dupes} duplicate rows for stagingid {stagingid}")
    all_results = deduped_results

    # 9. Assign globally-unique rowids
    for global_idx, result in enumerate(all_results, start=max_existing_rowid + 1):
        result["rowid"] = global_idx

    # 10. Write CSV
    if all_results:
        csv_dir = os.path.dirname(output_csv)
        if csv_dir:
            os.makedirs(csv_dir, exist_ok=True)
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_results[0].keys())
            writer.writeheader()
            writer.writerows(all_results)
        logger.info(f"CSV written → {output_csv}  ({len(all_results)} rows)")
    else:
        logger.warning("No results produced — CSV not written.")
        output_csv = None

    # 11. Insert into orgi.visibilityitemsstaging (same table as ollama_analyzer.py)
    if all_results:
        insert_ollama_results(
            cur, stagingid, all_results, modelname, s3_annotated_folder, image_paths
        )

    try:
        conn.commit()
    except Exception:
        pass

    close_db_connection(conn, cur)
    logger.info("DB insert completed")

    return all_results, output_csv


# ---------------------------------------------------------------------------
# Backwards-compatibility alias
# ---------------------------------------------------------------------------
run_ollama_analysis = run_yolo_analysis