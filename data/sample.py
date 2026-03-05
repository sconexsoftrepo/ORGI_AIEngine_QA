# # from ultralytics import YOLO

# # MODEL_PATH = "weights.pt"
# # OUTPUT_FILE = "sample_data.yaml"

# # # Load YOLO model
# # model = YOLO(MODEL_PATH)

# # # Extract class names in correct order
# # names_dict = model.names
# # names_list = [names_dict[i] for i in range(len(names_dict))]
# # nc = len(names_list)

# # with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
# #     # ---- KEEP THIS PART EXACT ----
# #     f.write("train: ../train/images\n")
# #     f.write("val: ../valid/images\n")
# #     f.write("test: ../test/images\n\n")

# #     # ---- AUTO-GENERATED PART ----
# #     f.write(f"nc: {nc}\n")
# #     f.write("names: [\n")
# #     for name in names_list:
# #         f.write(f"'{name}',\n")
# #     f.write("]\n\n")

# #     # ---- KEEP THIS PART EXACT ----
# #     f.write("roboflow:\n")
# #     f.write("  workspace: imageinsight-wwdyd\n")
# #     f.write("  project: orgi-imageinsight\n")
# #     f.write("  version: 5\n")
# #     f.write("  license: Private\n")
# #     f.write("  url: https://app.roboflow.com/imageinsight-wwdyd/orgi-imageinsight/5\n")

# # print(f"✅ data.yaml created successfully with {nc} classes")


# from ultralytics import YOLO

# MODEL_PATH = "activation_new.pt"

# model = YOLO(MODEL_PATH)

# # Convert dict → ordered list
# class_names = [name for _, name in sorted(model.names.items())]

# print(class_names)



import base64
import requests
import json

def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

image_b64 = encode_image("2.jpeg")

payload = {
    "model": "llava:7b",
    "messages": [
        {
            "role": "user",
            "content": "Extract Manufacturing Date (MFD). Return JSON only.",
            "images": [image_b64]
        }
    ],
    "stream": False
}

response = requests.post(
    "http://127.0.0.1:11434/api/chat",
    json=payload
)

data = response.json()

# 🔍 Debug print once (VERY IMPORTANT)
print("FULL RESPONSE:\n", json.dumps(data, indent=2))

# ✅ Extract content safely
if "message" in data:
    output = data["message"]["content"]
elif "response" in data:
    output = data["response"]
else:
    raise RuntimeError("Unexpected Ollama response format")

print("\nMODEL OUTPUT:\n", output)

