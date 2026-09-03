"""
DC 자비스 - 위험도 스코어링 스크립트 (v1.3 - 주요 지수/환율 조회 + 지표별 기준시점 명시 추가)
FRED(거시지표) + yfinance(VIX/환율/코스피/코스닥/S&P500/나스닥/다우)를 조합해 0~100점 위험도 산출
결과는 data/risk_score.json 에 저장됨
"""
import json
import os
from datetime import datetime, timezone

import requests
import yfinance as yf

FRED_API_KEY = os.environ["FRED_API_KEY"]
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def get_fred_latest(series_id):
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1,
    }
    r = requests.get(FRED_BASE, params=params, timeout=15)
    r.raise_for_status()
    obs = r.json()["observations"][0]
    return float(obs["value"]) if obs["value"] != "." else None


def score_vix(vix):
    if vix is None:
        return 0, 0
    if vix < 15:
        return vix, 10
    if vix < 25:
        return vix, 35
    if vix < 35:
        return vix, 70
    return vix, 100


def score_hy_spread(spread):
    if spread is None:
        return 0, 0
    if spread < 3.5:
        return spread, 10
    if spread < 5:
        return spread, 40
    if spread < 7:
        return spread, 70
    return spread, 100


def score_yield_curve(spread_10y2y):
    if spread_10y2y is None:
        return 0, 0
    if spread_10y2y < 0:
        return spread_10y2y, 80
    if spread_10y2y < 0.5:
        return spread_10y2y, 40
    return spread_10y2y, 10


def score_kospi_drawdown():
    kospi = yf.Ticker("^KS11").history(period="2mo")
    closes = kospi["Close"].dropna()

    if len(closes) < 5:
        print("[경고] 코스피 데이터 부족, 낙폭 계산 스킵")
        return 0, 0

    window = closes.tail(20)
    median = window.median()

    # 중앙값 대비 ±20% 벗어나는 값은 데이터 오류(이상치)로 간주해 제외
    cleaned = window[(window >= median * 0.8) & (window <= median * 1.2)]

    print(f"[디버그] 20일 종가: {window.round(2).tolist()}")
    if len(cleaned) < len(window):
        removed = window[~window.index.isin(cleaned.index)]
        print(f"[경고] 이상치로 제외됨: {removed.round(2).tolist()}")

    if cleaned.empty:
        return 0, 0

    high20 = cleaned.max()
    last = closes.iloc[-1]  # 가장 최근 종가는 이상치 필터와 무관하게 그대로 사용
    drawdown = (last / high20 - 1) * 100

    if drawdown > -2:
        return drawdown, 10
    if drawdown > -5:
        return drawdown, 40
    if drawdown > -10:
        return drawdown, 70
    return drawdown, 100


MARKET_INDEX_TICKERS = {
    "kospi": ("^KS11", "코스피"),
    "kosdaq": ("^KQ11", "코스닥"),
    "sp500": ("^GSPC", "S&P500"),
    "nasdaq": ("^IXIC", "나스닥"),
    "dow": ("^DJI", "다우"),
    "usdkrw": ("KRW=X", "원달러환율"),
}


def get_daily_change(ticker_symbol):
    try:
        hist = yf.Ticker(ticker_symbol).history(period="5d")
        closes = hist["Close"].dropna()
        if len(closes) < 2:
            return None
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2])
        change_pct = round((last / prev - 1) * 100, 2)
        return {"value": round(last, 2), "change_pct": change_pct}
    except Exception as e:
        print(f"[경고] {ticker_symbol} 조회 실패: {e}")
        return None


def get_market_indices():
    indices = {}
    for key, (symbol, label) in MARKET_INDEX_TICKERS.items():
        result = get_daily_change(symbol)
        indices[key] = {"label": label, **result} if result else {"label": label, "value": None, "change_pct": None}
        print(f"[디버그] {label}: {indices[key]}")
    return indices


def main():
    vix_val = get_fred_latest("VIXCLS")
    hy_val = get_fred_latest("BAMLH0A0HYM2")
    curve_val = get_fred_latest("T10Y2Y")

    vix_raw, vix_score = score_vix(vix_val)
    hy_raw, hy_score = score_hy_spread(hy_val)
    curve_raw, curve_score = score_yield_curve(curve_val)
    dd_raw, dd_score = score_kospi_drawdown()
    market_indices = get_market_indices()

    composite = round(
        vix_score * 0.30 + hy_score * 0.30 + curve_score * 0.20 + dd_score * 0.20
    )

    if composite < 30:
        level = "안정"
    elif composite < 55:
        level = "주의"
    elif composite < 80:
        level = "경고"
    else:
        level = "위험"

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "composite_score": composite,
        "level": level,
        "components": {
            "vix": {"raw": round(vix_raw, 2), "score": vix_score, "as_of": "미국 전일 기준(FRED)"},
            "high_yield_spread": {"raw": round(hy_raw, 2), "score": hy_score, "as_of": "미국 전일 기준(FRED)"},
            "yield_curve_10y2y": {"raw": round(curve_raw, 2), "score": curve_score, "as_of": "미국 전일 기준(FRED)"},
            "kospi_drawdown_pct": {"raw": round(dd_raw, 2), "score": dd_score, "as_of": "한국 당일 기준"},
        },
        "market_indices": market_indices,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/risk_score.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
