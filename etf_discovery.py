"""
DC 자비스 - ETF 발굴 엔진 (v1.7 - 모바일 친화 라벨 추가: 주도주체/거래량평가/별점)
30개 기본목록 + 사용자 임의추가 병합, 모멘텀+52주밴드+거시+수급 4지표 + 신뢰도 가중
결과는 data/etf_discovery.json 에 저장됨
"""
import json
import os
from datetime import datetime, timedelta, timezone

from pykrx import stock

BASE_UNIVERSE = [
    ("069500", "KODEX 200"),
    ("102110", "TIGER 200"),
    ("229200", "KODEX 코스닥150"),
    ("091160", "KODEX 반도체"),
    ("279530", "KODEX 미국반도체MV"),
    ("305720", "KODEX 2차전지산업"),
    ("143850", "TIGER 미국S&P500"),
    ("133690", "TIGER 미국나스닥100"),
    ("381170", "TIGER 미국테크TOP10 INDXX"),
    ("381180", "TIGER 미국필라델피아반도체나스닥"),
    ("371460", "TIGER 차이나전기차SOLACTIVE"),
    ("132030", "KODEX 골드선물(H)"),
    ("130680", "TIGER 원유선물Enhanced(H)"),
    ("091170", "KODEX 은행"),
    ("091220", "TIGER 은행"),
    ("117460", "KODEX 에너지화학"),
    ("091180", "KODEX 자동차"),
    ("244620", "KODEX 바이오"),
    ("227540", "TIGER 200헬스케어"),
    ("117680", "KODEX 건설"),
    ("069660", "KODEX 철강"),
    ("133680", "TIGER 리츠부동산인프라"),
    ("117690", "TIGER 필수소비재"),
    ("227550", "TIGER 200산업재"),
    ("139220", "TIGER 200경기소비재"),
    ("244660", "KODEX 배당가치"),
    ("148020", "KODEX 삼성그룹주"),
    ("379800", "KODEX 미국S&P500"),
    ("379810", "KODEX 미국나스닥100"),
    # KOSEF 국고채10년(148070) - 백테스트에서 신호력이 유의미하게 낮아 제외
]

EXCLUDE_KEYWORDS = ["레버리지", "인버스", "곱버스"]

CONFIDENCE_MULTIPLIER = {
    "높음": 1.10,
    "보통": 1.00,
    "낮음": 0.70,
    "표본부족": 0.85,
    "검증전": 0.85,
}

TODAY = datetime.now()
FROM_1Y = (TODAY - timedelta(days=380)).strftime("%Y%m%d")
FROM_20D = (TODAY - timedelta(days=40)).strftime("%Y%m%d")
TO = TODAY.strftime("%Y%m%d")


def load_universe():
    universe = [(t, n, "기본") for t, n in BASE_UNIVERSE]
    existing_tickers = {t for t, n in BASE_UNIVERSE}
    try:
        with open("data/custom_universe.json", "r", encoding="utf-8") as f:
            custom = json.load(f)
        for item in custom:
            ticker = item.get("ticker")
            name = item.get("name", ticker)
            if not ticker or ticker in existing_tickers:
                continue
            universe.append((ticker, name, "사용자추가"))
            existing_tickers.add(ticker)
        print(f"[디버그] 사용자 임의추가 종목 {len(custom)}개 확인, 병합 완료")
    except Exception as e:
        print(f"[경고] custom_universe.json 로드 실패(없어도 정상 동작): {e}")
    return universe


def load_macro_risk_level():
    try:
        with open("data/risk_score.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("composite_score", 50)
    except Exception as e:
        print(f"[경고] 위험도 데이터 로드 실패, 기본값(50) 사용: {e}")
        return 50


def load_backtest_confidence():
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
    high52, low52 = closes.max(), closes.min()
    last = closes.iloc[-1]
    if high52 == low52:
        return 50.0, 50
    position = (last - low52) / (high52 - low52) * 100
    score = max(0, min(100, 100 - abs(position - 60) * 1.5))
    return round(position, 1), round(score)


def evaluate_volume(ohlcv):
    """최근 5일 평균 거래량을 60일 평균과 비교해 부족/양호/높음으로 라벨링"""
    vol = ohlcv["거래량"].dropna()
    if len(vol) < 20:
        return "데이터부족"
    recent5 = vol.tail(5).mean()
    baseline = vol.tail(60).mean() if len(vol) >= 60 else vol.mean()
    if baseline == 0:
        return "데이터부족"
    ratio = recent5 / baseline
    if ratio >= 1.5:
        return "높음"
    if ratio >= 0.8:
        return "양호"
    return "부족"


def score_supply(ticker):
    """수급점수 + 주도주체(기관/외국인 중 순매수 규모가 더 큰 쪽) 판별"""
    try:
        df = stock.get_etf_trading_volume_and_value(FROM_20D, TO, ticker, "거래대금", "순매수")
        inst_net, foreign_net = 0, 0
        for col in ["기관합계", "기관"]:
            if col in df.columns:
                inst_net = df[col].sum()
                break
        for col in ["외국인합계", "외국인"]:
            if col in df.columns:
                foreign_net = df[col].sum()
                break
        if inst_net == 0 and foreign_net == 0:
            print(f"[경고] {ticker} 수급 컬럼 매칭 실패, 0점 처리. 컬럼: {list(df.columns)}")
            return None, 0, "정보없음"

        net_total = inst_net + foreign_net
        eok = net_total / 1e8
        score = max(0, min(100, 50 + eok / 2))
        leading = "기관" if abs(inst_net) >= abs(foreign_net) else "외국인"
        return round(eok, 1), round(score), leading
    except Exception as e:
        print(f"[경고] {ticker} 수급 데이터 조회 실패, 0점 처리: {e}")
        return None, 0, "정보없음"


def to_stars(adjusted_score):
    if adjusted_score >= 80:
        return 5
    if adjusted_score >= 65:
        return 4
    if adjusted_score >= 50:
        return 3
    if adjusted_score >= 35:
        return 2
    return 1


def main():
    macro_composite = load_macro_risk_level()
    macro_penalty = max(0, (macro_composite - 50)) * 0.5
    macro_score = round(max(0, 100 - macro_penalty))
    print(f"[디버그] 거시 위험도 {macro_composite}점 -> 발굴 거시점수 {macro_score}점 적용")

    confidence_map = load_backtest_confidence()
    universe = load_universe()
    print(f"[디버그] 총 스캔 대상 {len(universe)}개")

    results = []
    for ticker, name, origin in universe:
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
            supply_raw, supply_score, leading_actor = score_supply(ticker)
            volume_label = evaluate_volume(ohlcv)

            total_score = round(
                mom_score * 0.35
                + band_score * 0.20
                + macro_score * 0.15
                + supply_score * 0.30
            )

            confidence = confidence_map.get(
                ticker,
                {"label": "검증전", "backtest_win_rate_pct": None, "backtest_sample_count": 0},
            )
            multiplier = CONFIDENCE_MULTIPLIER.get(confidence["label"], 0.85)
            adjusted_score = round(total_score * multiplier)
            stars = to_stars(adjusted_score)

            results.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "origin": origin,
                    "total_score": total_score,
                    "adjusted_score": adjusted_score,
                    "stars": stars,
                    "confidence_multiplier": multiplier,
                    "backtest_confidence": confidence,
                    "leading_actor": leading_actor,
                    "volume_evaluation": volume_label,
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
            print(
                f"[디버그] {name}({ticker}) 조정점수 {adjusted_score} "
                f"별점 {stars} 주도주체 {leading_actor} 거래량 {volume_label}"
            )

        except Exception as e:
            print(f"[경고] {name}({ticker}) 처리 중 오류 발생, 스킵: {e}")
            continue

    results.sort(key=lambda x: x["adjusted_score"], reverse=True)
    top5 = results[:5]

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "macro_composite_score": macro_composite,
        "scanned_count": len(results),
        "ranking_basis": "adjusted_score (원점수 x 백테스트 신뢰도 가중치)",
        "note": "채권ETF는 백테스트 신호력 낮아 제외. custom_universe.json으로 종목 임의추가 가능.",
        "top5": top5,
        "all_results": results,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/etf_discovery.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(json.dumps(top5, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
