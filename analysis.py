"""1인 가구 식품 소비행태 분석 및 발표용 그래프 생성 스크립트."""

from io import BytesIO
from pathlib import Path
import re
from zipfile import ZipFile

import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "datas"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


def set_korean_font() -> None:
    """Windows/macOS/Linux에서 가능한 한 한글 폰트를 자동 설정한다."""
    windows_font = Path(r"C:\Windows\Fonts\malgun.ttf")
    if windows_font.exists():
        font_manager.fontManager.addfont(windows_font)
        rcParams["font.family"] = font_manager.FontProperties(fname=windows_font).get_name()
        rcParams["axes.unicode_minus"] = False
        return
    preferred = ["Malgun Gothic", "AppleGothic", "NanumGothic"]
    available = {font.name for font in font_manager.fontManager.ttflist}
    for font in preferred:
        if font in available:
            rcParams["font.family"] = font
            break
    rcParams["axes.unicode_minus"] = False


def weighted_distribution(data: pd.DataFrame, column: str, weight: str = "HHFWT") -> pd.Series:
    """결측치를 제외하고 표본 가중치 기준의 백분율 분포를 계산한다."""
    temp = data[[column, weight]].dropna()
    return temp.groupby(column)[weight].sum().div(temp[weight].sum()).mul(100)


def load_household_trend(zip_path: Path) -> pd.DataFrame:
    """KOSIS 다중 ZIP에서 전국·계 연도의 1인 가구 수를 읽는다.

    원본 CSV의 첫 행이 전국·계이므로 지역명 문자 인코딩 문제를 피하기 위해
    해당 행과 '1인가구' 열을 사용한다.
    """
    rows = []
    with ZipFile(zip_path) as outer:
        for file_name in outer.namelist():
            if not file_name.lower().endswith(".zip"):
                continue
            year_match = re.search(r"(20\d{2})\.zip$", file_name)
            if not year_match:
                continue
            with ZipFile(BytesIO(outer.read(file_name))) as inner:
                csv_name = next(name for name in inner.namelist() if name.lower().endswith(".csv"))
                raw = pd.read_csv(inner.open(csv_name), encoding="cp949", skiprows=2)
                household_col = next(col for col in raw.columns if col == "1인가구")
                rows.append({"year": int(year_match.group(1)), "households": float(raw.iloc[0][household_col])})
    return pd.DataFrame(rows).sort_values("year").reset_index(drop=True)


def main() -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    set_korean_font()

    xlsx_path = next(DATA_DIR.glob("*.xlsx"))
    zip_path = next(DATA_DIR.glob("*.zip"))
    df = pd.read_excel(xlsx_path, sheet_name="Numeric")
    required = {"SQ3N", "A2_1", "HHFWT", "A22", "F22_1"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"필수 변수가 없습니다: {sorted(missing)}")

    # 1. 1인 가구 증가 추이
    trend_df = load_household_trend(zip_path)
    growth_rate = (trend_df.loc[trend_df.index[-1], "households"] / trend_df.loc[0, "households"] - 1) * 100
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(trend_df["year"], trend_df["households"] / 1_000_000, marker="o", linewidth=2.5, color="#2563eb")
    ax.set(title="국내 1인 가구 증가 추이", xlabel="연도", ylabel="1인 가구 수 (백만 가구)")
    ax.set_xticks(trend_df["year"])
    for year, value in zip(trend_df["year"], trend_df["households"] / 1_000_000):
        ax.annotate(f"{value:.2f}", (year, value), xytext=(0, 8), textcoords="offset points", ha="center")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "01_single_household_trend.png", dpi=180)
    plt.close(fig)

    # 2. 1인 가구의 주 식품 구매처 (가중치 적용)
    place_map = {
        1: "동네 슈퍼/식자재마트", 2: "기업형 슈퍼마켓", 3: "대형마트", 4: "전통시장",
        5: "백화점", 6: "친환경 식품 전문점", 7: "온라인 쇼핑몰", 8: "TV 홈쇼핑",
        9: "편의점", 10: "로컬푸드 마켓", 11: "반찬가게", 12: "기타",
    }
    single_df = df.loc[df["SQ3N"] == 1].copy()
    place_ratio = weighted_distribution(single_df, "A2_1").rename(index=place_map).sort_values(ascending=False)
    top_places = place_ratio.head(5).sort_values()
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(top_places.index, top_places.values, color="#14b8a6")
    ax.set(title="1인 가구의 주요 식품 구매처", xlabel="가중 비율 (%)", ylabel="")
    for i, value in enumerate(top_places.values):
        ax.text(value + 0.4, i, f"{value:.1f}%", va="center")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "02_food_purchase_places.png", dpi=180)
    plt.close(fig)

    # 3. 장바구니 물가 부담 인식 (전체 가구, 가중치 적용)
    price_df = df.loc[df["A22"].notna(), ["A22", "HHFWT"]].copy()
    increased = price_df.loc[price_df["A22"] > 100, "HHFWT"].sum() / price_df["HHFWT"].sum() * 100
    price_result = pd.Series({"물가 상승 체감": increased, "동일/하락 체감": 100 - increased})
    fig, ax = plt.subplots(figsize=(6, 5))
    bars = ax.bar(price_result.index, price_result.values, color=["#f97316", "#94a3b8"])
    ax.set(title="전년 대비 식품 장바구니 물가 체감", ylabel="응답 비율 (%)", ylim=(0, 100))
    for bar, value in zip(bars, price_result.values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 2, f"{value:.1f}%", ha="center", fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "03_price_burden.png", dpi=180)
    plt.close(fig)

    # 4. 1인 가구의 HMR 선택 이유 (가중치 적용)
    def hmr_group(code: float) -> str:
        if code in [3, 4, 5, 8]:
            return "편리함"
        if code == 1:
            return "비용 절감"
        if code in [2, 6]:
            return "맛·다양성"
        if code == 7:
            return "외식비 감소"
        if code == 9:
            return "영양"
        return "기타"

    single_hmr = single_df.loc[single_df["F22_1"].notna(), ["F22_1", "HHFWT"]].copy()
    single_hmr["hmr_reason"] = single_hmr["F22_1"].map(hmr_group)
    hmr_ratio = weighted_distribution(single_hmr, "hmr_reason").sort_values(ascending=False)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(hmr_ratio.sort_values().index, hmr_ratio.sort_values().values, color="#8b5cf6")
    ax.set(title="1인 가구의 간편식 선택 이유", xlabel="가중 비율 (%)", ylabel="")
    for i, value in enumerate(hmr_ratio.sort_values().values):
        ax.text(value + 0.4, i, f"{value:.1f}%", va="center")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "04_hmr_reasons.png", dpi=180)
    plt.close(fig)

    print("[핵심 결과]")
    print(f"1인 가구: {trend_df.iloc[0]['households']:,.0f} → {trend_df.iloc[-1]['households']:,.0f} ({growth_rate:.1f}% 증가)")
    print("주요 식품 구매처:")
    print(place_ratio.head(5).round(2).to_string())
    print(f"장바구니 물가 상승 체감: {increased:.1f}%")
    print("간편식 선택 이유:")
    print(hmr_ratio.head(3).round(2).to_string())


if __name__ == "__main__":
    main()
