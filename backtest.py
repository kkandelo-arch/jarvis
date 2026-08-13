"""
DC 자비스 - 백테스팅 모듈 (v2.0 - etf_top30.json 기준 동적 목록으로 전환)
발굴엔진의 점수(모멘텀+52주밴드)가 과거에 실제로 유효했는지 검증
매일 갱신되는 거래대금 상위 30개(+임의추가 종목) 전체를 대상으로 검증하도록 변경
과거 각 시점의 점수 vs 이후 20일 수익률을 비교해 승률·평균수익률 산출
결과는 data/backtest_result.json 에 저장됨

주의: 거시점수는 과거 이력이 없어 중립값(50점 고정)으로 처리, 모멘텀+52주밴드 위주 검증
"""
import json
import os
from datetime import datetime, timedelta, timezone

from pykrx import stock

MACRO_SCORE_NEUTRAL = 50
LOOKBACK = 60
FORWARD = 20
STEP = 5
BUY_THRESHOLD = 60

TODAY = datetime.now()
FROM_DATE = (TODAY - timedelta(days=730)).strftime("%Y%m%d")
TO_DATE = TODAY.strftime("%Y%m%d")


def load_universe():
    universe = []
    existing = set()

    try:
        with open("data/etf_top30.json", "r", encoding="utf-8") as f:
            ranking = json.load(f)
        for item in ranking.get("top30", []):
            universe.append((item["ticker"], item["name"]))
            existing.add(item["ticker"])
        print(f"[디버그] 랭킹 기반 목록 {len(universe)}개 로드 (기준일: {ranking.get('data_as_of')})")
    except Exception as e:
        print(f"[경고] etf_top30.json 로드 실패: {e}")

    try:
        with open("data/custom_universe.json", "r", encoding="utf-8") as f:
            custom = json.load(f)
        added = 0
        for item in custom:
            ticker = item.get("ticker")
            name = item.get("name", ticker)
            if ticker and ticker not in existing:
                universe.append((ticker, name))
                existing.add(ticker)
                added += 1
        print(f"[디버그] 사용자 임의추가 종목 {added}개 병합")
    except Exception as e:
        print(f"[경고] custom_universe.json 로드 실패(없어도 정상 동작): {e}")

    return universe


def score_momentum(closes, i):
    if i < 20:
        return 0
    ret_20d = (closes[i] / closes[i - 20] - 1) * 100
    return max(0, min(100, (ret_20d + 10) * 5))


def score_52w_band(closes, i):
    window = closes[max(0, i - 250):i + 1]
    if len(window) < 2:
        return 50
    high52 = max(window)
    low52 = min(window)
    if high52 == low52:
        return 50
    position = (closes[i] - low52) / (high52 - low52) * 100
    score = 100 - abs(position - 60) * 1.5
    return max(0, min(100, score))


def backtest_ticker(ticker, name):
    try:
        ohlcv = stock.get_etf_ohlcv_by_date(FROM_DATE, TO_DATE, ticker)
        closes = ohlcv["종가"].dropna().tolist()
    except Exception as e:
        print(f"[경고] {name}({ticker}) 데이터 조회 실패, 스킵: {e}")
        return None

    if len(closes) < LOOKBACK + FORWARD + 10:
        print(f"[경고] {name}({ticker}) 데이터 기간 부족, 스킵")
        return None

    records = []
    for i in range(LOOKBACK, len(closes) - FORWARD, STEP):
        mom_score = score_momentum(closes, i)
        band_score = score_52w_band(closes, i)
        total = round(mom_score * 0.45 + band_score * 0.25 + MACRO_SCORE_NEUTRAL * 0.30)
        forward_return = (closes[i + FORWARD] / closes[i] - 1) * 100
        records.append({"score": total, "forward_return_pct": round(forward_return, 2)})

    if not records:
        return None

    buy_signals = [r for r in records if r["score"] >= BUY_THRESHOLD]
    other_signals = [r for r in records if r["score"] < BUY_THRESHOLD]

    def summarize(group):
        if not group:
            return {"count": 0, "win_rate_pct": None, "avg_return_pct": None}
        wins = sum(1 for r in group if r["forward_return_pct"] > 0)
        avg_ret = sum(r["forward_return_pct"] for r in group) / len(group)
        return {
            "count": len(group),
            "win_rate_pct": round(wins / len(group) * 100, 1),
            "avg_return_pct": round(avg_ret, 2),
        }

    result = {
        "ticker": ticker,
        "name": name,
        "total_test_points": len(records),
        "buy_signal_group": summarize(buy_signals),
        "other_group": summarize(other_signals),
    }
    print(
        f"[디버그] {name}({ticker}) 매수신호({len(buy_signals)}건) "
        f"승률 {result['buy_signal_group']['win_rate_pct']}% "
        f"평균수익 {result['buy_signal_group']['avg_return_pct']}%"
    )
    return result


def main():
    universe = load_universe()
    print(f"[디버그] 총 백테스트 대상 {len(universe)}개")

    per_etf_results = []
    for ticker, name in universe:
        r = backtest_ticker(ticker, name)
        if r:
            per_etf_results.append(r)

    total_buy_count = sum(r["buy_signal_group"]["count"] for r in per_etf_results)
    total_buy_wins_weighted = sum(
        (r["buy_signal_group"]["win_rate_pct"] or 0) * r["buy_signal_group"]["count"]
        for r in per_etf_results
    )
    overall_win_rate = (
        round(total_buy_wins_weighted / total_buy_count, 1) if total_buy_count > 0 else None
    )

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": "과거 시점별 모멘텀+52주밴드 점수(거시점수는 중립 50점 고정) vs 이후 20일 수익률 비교",
        "universe_source": "etf_top30.json(거래대금 상위, 매일 자동 갱신) + custom_universe.json",
        "buy_threshold": BUY_THRESHOLD,
        "overall_buy_signal_win_rate_pct": overall_win_rate,
        "overall_buy_signal_count": total_buy_count,
        "per_etf": per_etf_results,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/backtest_result.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
