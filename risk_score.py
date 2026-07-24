"""
DC 자비스 - 위험도 스코어링 스크립트 (1단계 MVP)
FRED(거시지표) + yfinance(VIX/환율/코스피)를 조합해 0~100점 위험도 산출
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
    """FRED에서 특정 지표의 가장 최근 값을 가져온다."""
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
        return spread_10y2y, 80  # 장단기 역전 = 경기침체 경고
    if spread_10y2y < 0.5:
        return spread_10y2y, 40
    return spread_10y2y, 10


def score_kospi_drawdown():
    kospi = yf.Ticker("^KS11").history(period="1mo")
    if kospi.empty:
        return 0, 0
    high20 = kospi["Close"].tail(20).max()
    last = kospi["Close"].iloc[-1]
    drawdown = (last / high20 - 1) * 100
    if drawdown > -2:
        return drawdown, 10
    if drawdown > -5:
        return drawdown, 40
    if drawdown > -10:
        return drawdown, 70
    return drawdown, 100


def main():
    vix_val = get_fred_latest("VIXCLS")
    hy_val = get_fred_latest("BAMLH0A0HYM2")
    curve_val = get_fred_latest("T10Y2Y")

    vix_raw, vix_score = score_vix(vix_val)
    hy_raw, hy_score = score_hy_spread(hy_val)
    curve_raw, curve_score = score_yield_curve(curve_val)
    dd_raw, dd_score = score_kospi_drawdown()

    # 가중합산: VIX 30%, 하이일드스프레드 30%, 장단기금리차 20%, 코스피낙폭 20%
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
            "vix": {"raw": round(vix_raw, 2), "score": vix_score},
            "high_yield_spread": {"raw": round(hy_raw, 2), "score": hy_score},
            "yield_curve_10y2y": {"raw": round(curve_raw, 2), "score": curve_score},
            "kospi_drawdown_pct": {"raw": round(dd_raw, 2), "score": dd_score},
        },
    }

    os.makedirs("data", exist_ok=True)
    with open("data/risk_score.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
