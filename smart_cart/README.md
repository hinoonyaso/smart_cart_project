# SMART CART 실행 안내

노트북 카메라, Roboflow Hosted Inference, SQLite, PySide6 GUI를 연결한 데모 앱입니다.

## 1. Roboflow 설정

PowerShell에서 API 키와 모델 ID를 설정합니다. 키는 코드나 Git에 넣지 않습니다.

~~~powershell
$env:ROBOFLOW_API_KEY = "발급받은_API_키"
$env:ROBOFLOW_MODEL_ID = "프로젝트ID/버전"
~~~

모델 ID는 Roboflow의 배포 화면에서 확인합니다. 예를 들어 food-cart/1 형식입니다.

## 2. 실행

프로젝트 최상위 폴더에서 실행합니다.

~~~powershell
uv run python -m smart_cart.main
~~~

API 키와 모델 ID가 없으면 카메라 화면은 열리지만 Roboflow 추론은 실행하지 않습니다.

## 동작 방식

1. 노트북 카메라 영상을 표시합니다.
2. 약 5프레임마다 최신 카메라 프레임을 Roboflow 추론 스레드에 보냅니다. HTTP 응답을 기다리는 동안에도 영상은 계속 표시하며, 대기 중인 오래된 프레임은 버립니다.
3. 신뢰도 70% 이상인 Bounding Box와 최근 인식 상품만 표시합니다.
4. 같은 상품이 2초 이상 연속 인식되면 장바구니에 자동으로 한 번 추가합니다.
5. SQLite의 데모 가격으로 총액을 계산합니다.
6. 장바구니 재료 충족률(%)이 높은 순으로 레시피를 추천합니다.

가격과 레시피 구성은 데모용입니다. SQLite 파일 smart_cart.db는 첫 실행 때 자동으로 생성됩니다.
