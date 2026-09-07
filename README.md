# 1인 가구 식품 소비행태 분석

`datas`의 KOSIS 1인 가구 자료와 KREI 2025 식품소비행태조사 마이크로데이터를 사용해 발표용 분석을 재현합니다. 모든 KREI 비율에는 표본 가중치 `HHFWT`를 적용합니다.

## 실행

```powershell
uv run python analysis.py
```

생성되는 발표용 그래프는 `outputs`에 저장됩니다.

## Roboflow 모델 PR Curve

`.env`의 Roboflow API 키로 OZM 버전 4 테스트 세트를 내려받고 Hosted Inference 결과를 IoU 0.5 기준으로 평가합니다.

```powershell
uv run python evaluate_pr_curve.py
```

그래프는 `outputs/roboflow_pr_curve.png`에 저장됩니다.

## 검증된 핵심 결과

| 질문 | 결과 | 사용 변수/자료 |
|---|---:|---|
| 1인 가구가 늘고 있는가? | 2020년 664.3만 → 2025년 824.4만 가구, **24.1% 증가** | KOSIS 2020~2025 |
| 1인 가구의 주 식품 구매처는? | 동네 슈퍼/식자재마트 **36.6%** | `SQ3N == 1`, `A2_1`, `HHFWT` |
| 식품 가격 부담이 있는가? | 장바구니 물가 상승 체감 **94.1%** | `A22 > 100`, `HHFWT` |
| 간편식을 고르는 핵심 이유는? | 편리함 **42.3%**, 비용 절감 **33.9%**, 맛·다양성 **23.0%** | `SQ3N == 1`, `F22_1`, `HHFWT` |

## 발표 결론

증가하는 1인 가구는 오프라인 동네 슈퍼/식자재마트를 주요 식품 구매처로 사용하고, 높은 식품 가격 부담을 체감한다. 동시에 간편식에서는 편리함과 비용을 중요하게 고려한다. 따라서 카메라 기반 식품 인식(YOLO), 실시간 장바구니 합계, 상품 가격 DB 조회, 보유 재료 기반 레시피 추천 기능을 연결하는 근거가 된다.

`analysis.py`는 네 개의 그래프를 생성한다.

1. `01_single_household_trend.png` — 1인 가구 증가 추이
2. `02_food_purchase_places.png` — 주요 식품 구매처
3. `03_price_burden.png` — 장바구니 물가 체감
4. `04_hmr_reasons.png` — 간편식 선택 이유
