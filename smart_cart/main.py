"""카메라, Roboflow, SQLite를 연결한 SMART CART GUI."""

import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QMainWindow, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from smart_cart.database import SmartCartDatabase
from smart_cart.roboflow_detector import MIN_CONFIDENCE, CameraWorker, RoboflowDetector


class RecipeDialog(QDialog):
    def __init__(self, recipes: list[dict], available_classes: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("추천 레시피")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        if not recipes:
            layout.addWidget(QLabel("장바구니 재료로 추천할 레시피가 없습니다."))
        for recipe in recipes:
            title = QLabel(recipe["name"])
            title.setStyleSheet("font-size: 20px; font-weight: bold;")
            layout.addWidget(title)
            layout.addWidget(QLabel(recipe["description"]))
            layout.addWidget(QLabel("레시피 주요 재료: " + " / ".join(recipe["ingredients"])))
            layout.addWidget(QLabel(f"재료 충족률: {recipe['match_rate']:.0f}%"))
            missing = [name for class_name, name in zip(recipe["classes"], recipe["ingredients"]) if class_name not in available_classes]
            layout.addWidget(QLabel("추가로 필요한 재료: " + " / ".join(missing) if missing else "모든 주요 재료가 있습니다."))
        button = QPushButton("장바구니로 돌아가기")
        button.clicked.connect(self.accept)
        layout.addWidget(button)


class SmartCartWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SMART CART")
        self.resize(1100, 720)
        self.db, self.cart = SmartCartDatabase(), {}
        self.current_detection = self.detected_since = self.auto_added_class = None
        self.create_ui()
        self.start_camera()

    def create_ui(self):
        root = QWidget(); self.setCentralWidget(root); page = QVBoxLayout(root)
        title = QLabel("SMART CART"); title.setAlignment(Qt.AlignCenter); title.setStyleSheet("font-size: 28px; font-weight: bold; padding: 8px;"); page.addWidget(title)
        content = QHBoxLayout(); page.addLayout(content, 1)
        left = QVBoxLayout()
        self.camera_label = QLabel("카메라를 여는 중입니다..."); self.camera_label.setAlignment(Qt.AlignCenter); self.camera_label.setMinimumSize(560, 420); self.camera_label.setStyleSheet("background: #1f2937; color: white;"); left.addWidget(self.camera_label)
        self.detection_label, self.status_label = QLabel("최근 인식: 대기 중"), QLabel("상태: 카메라 준비 중"); left.addWidget(self.detection_label); left.addWidget(self.status_label)
        auto_add = QLabel("자동 추가: 같은 상품을 2초 이상 인식하면 장바구니에 담깁니다."); auto_add.setStyleSheet("font-weight: bold; color: #047857;"); left.addWidget(auto_add); content.addLayout(left, 1)
        right = QVBoxLayout(); cart_title = QLabel("장바구니"); cart_title.setStyleSheet("font-size: 20px; font-weight: bold;"); right.addWidget(cart_title)
        self.cart_table = QTableWidget(0, 4); self.cart_table.setHorizontalHeaderLabels(["상품", "가격", "수량", "합계"]); self.cart_table.setEditTriggers(QTableWidget.NoEditTriggers); self.cart_table.horizontalHeader().setStretchLastSection(True); right.addWidget(self.cart_table, 1)
        self.total_label = QLabel("총 금액: 0원"); self.total_label.setStyleSheet("font-size: 24px; font-weight: bold; padding: 12px;"); self.total_label.setAlignment(Qt.AlignRight); right.addWidget(self.total_label)
        delete = QPushButton("선택 상품 삭제"); delete.clicked.connect(self.delete_selected_product); right.addWidget(delete); content.addLayout(right, 1)
        bottom = QHBoxLayout(); clear = QPushButton("장바구니 초기화"); clear.clicked.connect(self.clear_cart); recipe = QPushButton("레시피 추천"); recipe.clicked.connect(self.show_recipes); bottom.addWidget(clear); bottom.addWidget(recipe); page.addLayout(bottom)

    def start_camera(self):
        self.worker = CameraWorker(RoboflowDetector()); self.worker.frame_ready.connect(self.show_camera_frame); self.worker.detections_ready.connect(self.update_detection); self.worker.status_changed.connect(self.status_label.setText); self.worker.start()

    def show_camera_frame(self, image):
        self.camera_label.setPixmap(QPixmap.fromImage(image).scaled(self.camera_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def update_detection(self, predictions):
        predictions = [item for item in predictions if item.get("confidence", 0) >= MIN_CONFIDENCE]
        if not predictions:
            self.current_detection = self.detected_since = self.auto_added_class = None; self.detection_label.setText("최근 인식: 찾지 못했습니다."); return
        previous = self.db.normalize_class_name(self.current_detection.get("class", "")) if self.current_detection else None
        self.current_detection = max(predictions, key=lambda item: item.get("confidence", 0)); detected_class_name = self.current_detection.get("class", ""); class_name = self.db.normalize_class_name(detected_class_name); product = self.db.get_product(class_name)
        if not product:
            self.detected_since = self.auto_added_class = None; self.detection_label.setText(f"최근 인식: {detected_class_name} — DB에 없는 클래스"); return
        self.update_auto_add(class_name, product, previous); self.detection_label.setText(f"최근 인식: {product[1]} (정확도 {self.current_detection.get('confidence', 0) * 100:.0f}%)")

    def update_auto_add(self, class_name, product, previous):
        now = time.monotonic()
        if previous != class_name: self.detected_since, self.auto_added_class = now, None
        if self.auto_added_class == class_name: return
        if now - self.detected_since >= 2:
            self.add_product(class_name, product); self.auto_added_class = class_name; self.status_label.setText(f"{product[1]} 자동 추가 완료")

    def add_product(self, class_name, product):
        _, name, price = product; self.cart.setdefault(class_name, {"name": name, "price": price, "quantity": 0})["quantity"] += 1; self.refresh_cart()

    def refresh_cart(self):
        self.cart_table.setRowCount(len(self.cart)); total = 0
        for row, (class_name, item) in enumerate(self.cart.items()):
            subtotal = item["price"] * item["quantity"]; total += subtotal; name = QTableWidgetItem(item["name"]); name.setData(Qt.UserRole, class_name); self.cart_table.setItem(row, 0, name); self.cart_table.setItem(row, 1, QTableWidgetItem(f"{item['price']:,}원")); self.cart_table.setItem(row, 2, QTableWidgetItem(str(item["quantity"]))); self.cart_table.setItem(row, 3, QTableWidgetItem(f"{subtotal:,}원"))
        self.total_label.setText(f"총 금액: {total:,}원")

    def delete_selected_product(self):
        row = self.cart_table.currentRow()
        if row >= 0: del self.cart[self.cart_table.item(row, 0).data(Qt.UserRole)]; self.refresh_cart()

    def clear_cart(self): self.cart.clear(); self.refresh_cart()
    def show_recipes(self): RecipeDialog(self.db.get_recipes(set(self.cart)), set(self.cart), self).exec()
    def closeEvent(self, event): self.worker.stop(); self.db.close(); event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv); window = SmartCartWindow(); window.show(); sys.exit(app.exec())
