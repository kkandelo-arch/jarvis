"""
DC 자비스 - ETF 발굴 엔진 (2단계 MVP, v1.1 - 레버리지/인버스 제외 필터 추가)
모멘텀 + 52주밴드 + 거시 + 수급 4지표로 ETF 점수화
결과는 data/etf_discovery.json 에 저장됨
"""
import json
import os
from datetime import datetime, timedelta, timezone

from pykrx import stock

# 우선 커버할 주요 ETF 목록 (필요 시 여기에 계속 추가하면 됨)
UNIVERSE = [
    ("069500", "KODEX 200"),
    ("229200", "KODEX 코스닥150"),
    ("091160", "KODEX 반도체"),
    ("305720", "KODEX 2차전지산업"),
    ("143850", "TIGER 미국S&P500"),
    ("133690", "TIGER 미국나스닥100"),
    ("132030", "KODEX 골드선물(H)"),
    ("148070", "KOSEF 국고채10년"),
    ("091170", "KODEX 은행"),
    ("117460", "KODEX 에너지화학"),
    ("091180", "KODEX 자동차"),
    ("244620", "KODEX 바이오"),
]

# 안전장치: 이름에 이 키워드가 포함된 종목은 목록에 실수로 들어와도 자동 제외
EXCLUDE_KEYWORDS = ["레버리지", "인버스", "곱버스"]

TODAY = datetime.now()
FROM_1Y = (TODAY - timedelta(days=380)).strftime("%Y%m%d")
FROM_20D = (TODAY - timedelta(days=40)).strftime("%Y%m%d")
TO = TODAY.strftime("%Y%m%d")


def load_macro_risk_level():
    """1단계에서 만든 위험도 점수를 읽어와 발굴 가중치에 반영"""
    try:
        with open("data/risk_score.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("composite_score", 50)
    except Exception as e:
        print(f"[경고] 위험도 데이터 로드 실패, 기본값(50) 사용: {e}")
        return 50


def score_momentum(ohlcv):
    closes = ohlcv["종가"].dropna()
    if len(closes) < 20:
        return None, 0
    ret_20d = (closes.iloc[-1] / closes.iloc[-20] - 1) * 100
    score = max(0, min(100, (ret_20d + 10) * 5))
    return round(ret_20d, 2), round(score)


def score_52w_band(ohlcv):
    closes = ohlcv["종가"].dropna()
    if closes.empty:
        return None, 0
    high52 = closes.max()
    low52 = closes.min()
    last = closes.iloc[-1]
    if high52 == low52:
        return 50.0, 50
    position = (last - low52) / (high52 - low52) * 100
    score = 100 - abs(position - 60) * 1.5
    score = max(0, min(100, score))
    return round(position, 1), round(score)


def score_supply(ticker):
    try:
        df = stock.get_market_trading_value_by_date(FROM_20D, TO, ticker)
        if df.empty:
            return None, 0
        net_foreign = df["외국인합계"].sum() if "외국인합계" in df.columns else 0
        net_inst = df["기관합계"].sum() if "기관합계" in df.columns else 0
        net_total = net_foreign + net_inst
        eok = net_total / 1e8
        score = max(0, min(100, 50 + eok / 2))
        return round(eok, 1), round(score)
    except Exception as e:
        print(f"[경고] {ticker} 수급 데이터 조회 실패, 0점 처리: {e}")
        return None, 0


def main():
    macro_composite = load_macro_risk_level()
    macro_penalty = max(0, (macro_composite - 50)) * 0.5
    macro_score = round(max(0, 100 - macro_penalty))
    print(f"[디버그] 거시 위험도 {macro_composite}점 -> 발굴 거시점수 {macro_score}점 적용")

    results = []
    for ticker, name in UNIVERSE:
        if any(kw in name for kw in EXCLUDE_KEYWORDS):
            print(f"[제외] {name}({ticker}) - 레버리지/인버스 상품이라 스캔 대상에서 제외")
            continue

        try:
            ohlcv = stock.get_etf_ohlcv_by_date(FROM_1Y, TO, ticker)
            if ohlcv.empty:
                print(f"[경고] {name}({ticker}) 시세 데이터 없음, 스킵")
                continue

            mom_raw, mom_score = score_momentum(ohlcv)
            band_raw, band_score = score_52w_band(ohlcv)
            supply_raw, supply_score = score_supply(ticker)

            total = round(
                mom_score * 0.35
                + band_score * 0.20
                + macro_score * 0.15
                + supply_score * 0.30
            )

            results.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "total_score": total,
                    "components": {
                        "momentum_20d_pct": mom_raw,
                        "momentum_score": mom_score,
                        "band_position_pct": band_raw,
                        "band_score": band_score,
                        "macro_score": macro_score,
                        "supply_net_eok": supply_raw,
                        "supply_score": supply_score,
                    },
                }
            )
            print(f"[디버그] {name}({ticker}) 총점 {total}")

        except Exception as e:
            print(f"[경고] {name}({ticker}) 처리 중 오류 발생, 스킵: {e}")
            continue

    results.sort(key=lambda x: x["total_score"], reverse=True)
    top5 = results[:5]

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "macro_composite_score": macro_composite,
        "scanned_count": len(results),
        "top5": top5,
        "all_results": results,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/etf_discovery.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(json.dumps(top5, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
