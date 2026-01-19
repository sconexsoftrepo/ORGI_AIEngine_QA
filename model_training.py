from ultralytics import YOLO
import torch

def train_yolov8():
    print("Torch CUDA available:", torch.cuda.is_available())

    model = YOLO("yolov8l.pt")  # safer than yolov8l on T4

    model.train(
        data="other_visible_items-2/data.yaml",
        epochs=50,
        batch=12,
        imgsz=640,
        device=0,
        workers=2,

        optimizer="AdamW",
        lr0=1e-3,
        lrf=0.01,
        weight_decay=5e-4,

        hsv_h=0.015,
        hsv_s=0.25,
        hsv_v=0.10,
        degrees=5.0,
        translate=0.1,
        scale=0.5,
        shear=2.0,
        perspective=0.0005,

        mosaic=1.0,
        mixup=0.15,
        copy_paste=0.1,

        amp=True,
        cache=True,

        val=True,
        save=True,
        save_period=10,
        patience=30,

        project="runs/train",
        name="yolov8_augmented_3x",
        exist_ok=True,
        verbose=True
    )

if __name__ == "__main__":
    train_yolov8()
