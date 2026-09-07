"""Roboflow Hosted 모델의 테스트 세트로 PR Curve를 생성한다.

실행: uv run python evaluate_pr_curve.py
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from inference_sdk import InferenceConfiguration, InferenceHTTPClient
from roboflow import Roboflow


ROOT = Path(__file__).resolve().parent
DATASET_DIR = ROOT / "model_evaluation" / "ozm-4-yolov8"
OUTPUT_DIR = ROOT / "outputs"
IOU_THRESHOLD = 0.5


def box_iou(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    if intersection == 0:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / (first_area + second_area - intersection)


def yolo_box_to_xyxy(values: list[float], image_width: int, image_height: int) -> tuple[float, float, float, float]:
    if len(values) > 5:
        # Roboflow의 YOLO 세그멘테이션 라벨은 ``class x1 y1 x2 y2 ...`` 형식이다.
        points = values[1:]
        x_values = points[0::2]
        y_values = points[1::2]
        return (
            min(x_values) * image_width,
            min(y_values) * image_height,
            max(x_values) * image_width,
            max(y_values) * image_height,
        )

    _, center_x, center_y, width, height = values
    center_x *= image_width
    center_y *= image_height
    width *= image_width
    height *= image_height
    return (
        center_x - width / 2,
        center_y - height / 2,
        center_x + width / 2,
        center_y + height / 2,
    )


def prediction_to_xyxy(prediction: dict) -> tuple[float, float, float, float]:
    center_x = float(prediction["x"])
    center_y = float(prediction["y"])
    width = float(prediction["width"])
    height = float(prediction["height"])
    return (
        center_x - width / 2,
        center_y - height / 2,
        center_x + width / 2,
        center_y + height / 2,
    )


def average_precision(recall: list[float], precision: list[float]) -> float:
    """COCO 방식의 101개 recall 지점 평균 precision을 계산한다."""
    if not recall:
        return 0.0
    return sum(
        max((value for r, value in zip(recall, precision) if r >= point), default=0.0)
        for point in (index / 100 for index in range(101))
    ) / 101


def load_dataset(api_key: str, workspace_name: str, project_name: str, version_number: int) -> Path:
    if (DATASET_DIR / "test" / "images").exists():
        return DATASET_DIR

    print("Roboflow 테스트 세트를 내려받는 중...")
    project = Roboflow(api_key=api_key).workspace(workspace_name).project(project_name)
    project.version(version_number).download("yolov8", location=str(DATASET_DIR))
    return DATASET_DIR


def main() -> None:
    load_dotenv(ROOT / ".env", override=True)
    api_key = os.getenv("RF_API_KEY") or os.getenv("ROBOFLOW_API_KEY")
    if not api_key:
        raise RuntimeError(".env에 RF_API_KEY 또는 ROBOFLOW_API_KEY를 설정하세요.")

    workspace_name = os.getenv("ROBOFLOW_WORKSPACE", "sang-rqj4u")
    project_name = os.getenv("ROBOFLOW_PROJECT", "ozm")
    version_number = int(os.getenv("ROBOFLOW_VERSION", "4"))
    model_id = os.getenv("ROBOFLOW_MODEL_ID", f"{workspace_name}/{project_name}-{version_number}-yolov8n-t1")
    dataset_dir = load_dataset(api_key, workspace_name, project_name, version_number)

    client = InferenceHTTPClient(api_url="https://detect.roboflow.com", api_key=api_key)
    client.configure(InferenceConfiguration(api_key_transport="header"))
    image_dir = dataset_dir / "test" / "images"
    label_dir = dataset_dir / "test" / "labels"
    image_paths = sorted(path for path in image_dir.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not image_paths:
        raise RuntimeError(f"테스트 이미지를 찾지 못했습니다: {image_dir}")

    ground_truths: dict[str, list[tuple[int, tuple[float, float, float, float]]]] = {}
    predictions: list[tuple[float, int, str, tuple[float, float, float, float]]] = []
    for index, image_path in enumerate(image_paths, start=1):
        image = cv2.imread(str(image_path))
        if image is None:
            continue
        height, width = image.shape[:2]
        label_path = label_dir / f"{image_path.stem}.txt"
        labels = []
        if label_path.exists():
            for line in label_path.read_text(encoding="utf-8").splitlines():
                values = [float(value) for value in line.split()]
                labels.append((int(values[0]), yolo_box_to_xyxy(values, width, height)))
        ground_truths[image_path.name] = labels

        result = client.infer(image, model_id=model_id)
        for prediction in result.get("predictions", []):
            try:
                class_id = int(prediction.get("class_id", prediction["class"]))
            except (KeyError, TypeError, ValueError):
                continue
            predictions.append((float(prediction["confidence"]), class_id, image_path.name, prediction_to_xyxy(prediction)))
        print(f"추론 완료: {index}/{len(image_paths)}", end="\r")
    print()

    total_by_class: dict[int, int] = defaultdict(int)
    for labels in ground_truths.values():
        for class_id, _ in labels:
            total_by_class[class_id] += 1

    classes = sorted(total_by_class)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(11, 8))
    ap_scores = []
    for class_id in classes:
        class_predictions = sorted((item for item in predictions if item[1] == class_id), reverse=True)
        matched: dict[str, set[int]] = defaultdict(set)
        true_positives: list[int] = []
        false_positives: list[int] = []
        for _, _, image_name, predicted_box in class_predictions:
            candidates = [
                (box_iou(predicted_box, box), label_index)
                for label_index, (label_class, box) in enumerate(ground_truths[image_name])
                if label_class == class_id and label_index not in matched[image_name]
            ]
            best_iou, label_index = max(candidates, default=(0.0, -1))
            if best_iou >= IOU_THRESHOLD:
                matched[image_name].add(label_index)
                true_positives.append(1)
                false_positives.append(0)
            else:
                true_positives.append(0)
                false_positives.append(1)

        cumulative_tp = 0
        cumulative_fp = 0
        recall: list[float] = []
        precision: list[float] = []
        for tp, fp in zip(true_positives, false_positives):
            cumulative_tp += tp
            cumulative_fp += fp
            recall.append(cumulative_tp / total_by_class[class_id])
            precision.append(cumulative_tp / (cumulative_tp + cumulative_fp))
        ap = average_precision(recall, precision)
        ap_scores.append(ap)
        axis.plot(recall, precision, linewidth=1.5, label=f"class {class_id}: AP {ap:.3f}")

    mean_ap = sum(ap_scores) / len(ap_scores) if ap_scores else 0.0
    axis.set(title=f"Precision-Recall Curve (mAP@0.5: {mean_ap:.3f})", xlabel="Recall", ylabel="Precision")
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1.05)
    axis.grid(alpha=0.25)
    axis.legend(loc="center left", bbox_to_anchor=(1, 0.5))
    figure.tight_layout()
    output_path = OUTPUT_DIR / "roboflow_pr_curve.png"
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    print(f"PR Curve 저장 완료: {output_path}")


if __name__ == "__main__":
    main()
