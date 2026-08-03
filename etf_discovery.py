"""
DC 자비스 - ETF 발굴 엔진 (v1.3 - 채권ETF 제외, 백테스트 신뢰도 라벨 부착)
모멘텀 + 52주밴드 + 거시 3지표로 ETF 점수화
발굴 결과마다 backtest_result.json 기반 신뢰도 라벨을 붙여서 "믿을 만한 신호인지"를 함께 표시
결과는 data/etf_discovery.json 에 저장됨
"""
import json
import os
from datetime import datetime, timedelta, timezone

from pykrx import stock

UNIVERSE = [
    ("069500", "KODEX 200"),
    ("229200", "KODEX 코스닥150"),
    ("091160", "KODEX 반도체"),
    ("305720", "KODEX 2차전지산업"),
    ("143850", "TIGER 미국S&P500"),
    ("133690", "TIGER 미국나스닥100"),
    ("132030", "KODEX 골드선물(H)"),
    ("091170", "KODEX 은행"),
    ("117460", "KODEX 에너지화학"),
    ("091180", "KODEX 자동차"),
    ("244620", "KODEX 바이오"),
    # KOSEF 국고채10년(148070) - 백테스트에서 신호력이 유의미하게 낮아 제외
]

EXCLUDE_KEYWORDS = ["레버리지", "인버스", "곱버스"]

TODAY = datetime.now()
FROM_1Y = (TODAY - timedelta(days=380)).strftime("%Y%m%d")
TO = TODAY.strftime("%Y%m%d")


def load_macro_risk_level():
    try:
        with open("data/risk_score.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("composite_score", 50)
    except Exception as e:
        print(f"[경고] 위험도 데이터 로드 실패, 기본값(50) 사용: {e}")
        return 50


def load_backtest_confidence():
    """백테스트 결과를 읽어서 종목별 신뢰도 라벨을 만든다.
    아직 백테스트를 안 돌렸거나 파일이 없으면 전부 '검증전'으로 처리."""
    try:
        with open("data/backtest_result.json", "r", encoding="utf-8") as f:
            bt = json.load(f)
    except Exception as e:
        print(f"[경고] 백테스트 결과 로드 실패, 신뢰도 라벨 '검증전' 처리: {e}")
        return {}

    confidence_map = {}
    for etf in bt.get("per_etf", []):
        buy_group = etf.get("buy_signal_group", {})
        win_rate = buy_group.get("win_rate_pct")
        count = buy_group.get("count", 0)

        if win_rate is None or count < 15:
            label = "표본부족"
        elif win_rate >= 65:
            label = "높음"
        elif win_rate >= 50:
            label = "보통"
        else:
            label = "낮음"

        confidence_map[etf["ticker"]] = {
            "label": label,
            "backtest_win_rate_pct": win_rate,
            "backtest_sample_count": count,
        }
    return confidence_map


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


def main():
    macro_composite = load_macro_risk_level()
    macro_penalty = max(0, (macro_composite - 50)) * 0.5
    macro_score = round(max(0, 100 - macro_penalty))
    print(f"[디버그] 거시 위험도 {macro_composite}점 -> 발굴 거시점수 {macro_score}점 적용")

    confidence_map = load_backtest_confidence()
    print(f"[디버그] 백테스트 신뢰도 매핑 {len(confidence_map)}개 종목 로드")

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

            total = round(mom_score * 0.45 + band_score * 0.25 + macro_score * 0.30)

            confidence = confidence_map.get(
                ticker,
                {"label": "검증전", "backtest_win_rate_pct": None, "backtest_sample_count": 0},
            )

            results.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "total_score": total,
                    "backtest_confidence": confidence,
                    "components": {
                        "momentum_20d_pct": mom_raw,
                        "momentum_score": mom_score,
                        "band_position_pct": band_raw,
                        "band_score": band_score,
                        "macro_score": macro_score,
                        "supply_score": "추후 추가 예정",
                    },
                }
            )
            print(f"[디버그] {name}({ticker}) 총점 {total} 신뢰도 {confidence['label']}")

        except Exception as e:
            print(f"[경고] {name}({ticker}) 처리 중 오류 발생, 스킵: {e}")
            continue

    results.sort(key=lambda x: x["total_score"], reverse=True)
    top5 = results[:5]

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "macro_composite_score": macro_composite,
        "scanned_count": len(results),
        "note": "수급(외국인·기관 순매수) 지표는 ETF 전용 API 검증 후 추가 예정. 채권ETF는 백테스트 신호력 낮아 제외.",
        "top5": top5,
        "all_results": results,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/etf_discovery.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(json.dumps(top5, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
