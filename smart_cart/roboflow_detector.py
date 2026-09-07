"""카메라 영상과 Roboflow Hosted Inference를 연결한다."""

import os
import threading

import cv2
from dotenv import load_dotenv
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage


# 낮은 신뢰도의 오탐이 장바구니 후보 또는 Bounding Box가 되지 않게 한다.
MIN_CONFIDENCE = 0.7
# 추론 요청이 진행 중일 때는 가장 최근 카메라 프레임만 보관한다.
INFERENCE_INTERVAL_FRAMES = 5


class RoboflowDetector:
    def __init__(self):
        load_dotenv(override=True)
        self.api_key = os.getenv("RF_API_KEY") or os.getenv("ROBOFLOW_API_KEY")
        self.model_id = os.getenv("ROBOFLOW_MODEL_ID", "sang-rqj4u/ozm-4-yolov8n-t1")
        self.client = None

        if self.api_key and self.model_id:
            from inference_sdk import InferenceConfiguration, InferenceHTTPClient

            self.client = InferenceHTTPClient(
                api_url=os.getenv("ROBOFLOW_API_URL", "https://detect.roboflow.com"),
                api_key=self.api_key,
            )
            self.client.configure(InferenceConfiguration(api_key_transport="header"))

    @property
    def ready(self) -> bool:
        return self.client is not None

    def infer(self, frame) -> list[dict]:
        if not self.ready:
            return []

        result = self.client.infer(frame, model_id=self.model_id)
        return [
            prediction
            for prediction in result.get("predictions", [])
            if prediction.get("confidence", 0) >= MIN_CONFIDENCE
        ]


class InferenceWorker(QThread):
    """HTTP 응답을 기다리는 동안에도 카메라가 계속 읽히도록 추론만 담당한다."""

    detections_ready = Signal(list)
    status_changed = Signal(str)

    def __init__(self, detector: RoboflowDetector):
        super().__init__()
        self.detector = detector
        self._condition = threading.Condition()
        self._pending_frame = None
        self._latest_predictions: list[dict] = []
        self._running = True

    def submit_frame(self, frame) -> None:
        """대기 중인 이전 프레임은 버리고 가장 최신 프레임으로 교체한다."""
        with self._condition:
            self._pending_frame = frame.copy()
            self._condition.notify()

    def latest_predictions(self) -> list[dict]:
        with self._condition:
            return list(self._latest_predictions)

    def stop(self) -> None:
        with self._condition:
            self._running = False
            self._pending_frame = None
            self._condition.notify_all()
        self.wait()

    def run(self) -> None:
        while True:
            with self._condition:
                while self._running and self._pending_frame is None:
                    self._condition.wait()
                if not self._running:
                    return
                frame = self._pending_frame
                self._pending_frame = None

            try:
                predictions = self.detector.infer(frame)
            except Exception as error:
                self.status_changed.emit(f"Roboflow 오류: {error}")
                predictions = []

            with self._condition:
                self._latest_predictions = predictions
            self.detections_ready.emit(predictions)


class CameraWorker(QThread):
    frame_ready = Signal(QImage)
    detections_ready = Signal(list)
    status_changed = Signal(str)

    def __init__(self, detector: RoboflowDetector):
        super().__init__()
        self.detector = detector
        self.running = True
        self.inference_worker = InferenceWorker(detector)
        self.inference_worker.detections_ready.connect(self.detections_ready)
        self.inference_worker.status_changed.connect(self.status_changed)

    def stop(self) -> None:
        self.running = False
        self.inference_worker.stop()
        self.wait()

    def run(self) -> None:
        camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not camera.isOpened():
            self.status_changed.emit("노트북 카메라를 찾을 수 없습니다.")
            return

        if self.detector.ready:
            self.status_changed.emit("Roboflow 추론 연결 완료")
            self.inference_worker.start()
        else:
            self.status_changed.emit("카메라만 실행 중 — Roboflow 환경변수를 설정하세요.")

        frame_count = 0
        while self.running:
            success, frame = camera.read()
            if not success:
                break

            frame_count += 1
            if self.detector.ready and frame_count % INFERENCE_INTERVAL_FRAMES == 0:
                self.inference_worker.submit_frame(frame)

            # 추론 결과가 늦더라도 카메라는 매 프레임 계속 표시한다.
            shown_frame = self.draw_boxes(frame.copy(), self.inference_worker.latest_predictions())
            rgb_frame = cv2.cvtColor(shown_frame, cv2.COLOR_BGR2RGB)
            height, width, channel = rgb_frame.shape
            image = QImage(rgb_frame.data, width, height, width * channel, QImage.Format_RGB888).copy()
            self.frame_ready.emit(image)

        camera.release()

    @staticmethod
    def draw_boxes(frame, predictions: list[dict]):
        for prediction in predictions:
            x = int(prediction.get("x", 0))
            y = int(prediction.get("y", 0))
            width = int(prediction.get("width", 0))
            height = int(prediction.get("height", 0))
            left = x - width // 2
            top = y - height // 2
            right = x + width // 2
            bottom = y + height // 2
            class_name = prediction.get("class", "unknown")
            confidence = prediction.get("confidence", 0) * 100

            cv2.rectangle(frame, (left, top), (right, bottom), (0, 220, 0), 2)
            cv2.putText(
                frame,
                f"{class_name} {confidence:.0f}%",
                (left, max(top - 8, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 220, 0),
                2,
            )
        return frame
