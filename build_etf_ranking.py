"""
DC 자비스 - ETF 랭킹 수집 (v1.5 - 레이트리밋 방지: 요청 간격 + 재시도)
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

from pykrx import stock

EXCLUDE_KEYWORDS = [
    "레버리지", "인버스", "곱버스",
    "국고채", "회사채", "단기채", "머니마켓", "금리",
    "(H)",
]

TODAY = datetime.now()
FROM_5D = (TODAY - timedelta(days=10)).strftime("%Y%m%d")
TO = TODAY.strftime("%Y%m%d")

REQUEST_DELAY_SEC = 0.3   # 요청 사이 대기시간 (KRX 차단 방지)
RETRY_DELAY_SEC = 3.0     # 실패 시 재시도 전 대기시간


def load_master_list():
    with open("data/etf_master_list.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("etfs", [])


def get_latest_metrics(ticker, debug_columns_shown, retry=True):
    try:
        ohlcv = stock.get_etf_ohlcv_by_date(FROM_5D, TO, ticker)
        if ohlcv.empty:
            return None, None, debug_columns_shown

        if not debug_columns_shown:
            print(f"[디버그] ETF OHLCV 컬럼 예시({ticker}): {list(ohlcv.columns)}")
            debug_columns_shown = True

        last_row = ohlcv.iloc[-1]

        trading_value = None
        for col in ["거래대금"]:
            if col in ohlcv.columns:
                trading_value = float(last_row[col])
                break

        market_cap = None
        for col in ["시가총액", "순자산총액", "NAV"]:
            if col in ohlcv.columns:
                market_cap = float(last_row[col])
                break

        return trading_value, market_cap, debug_columns_shown

    except Exception as e:
        if retry:
            print(f"[경고] {ticker} 조회 실패, {RETRY_DELAY_SEC}초 대기 후 1회 재시도: {e}")
            time.sleep(RETRY_DELAY_SEC)
            return get_latest_metrics(ticker, debug_columns_shown, retry=False)
        print(f"[경고] {ticker} 재시도도 실패, 최종 스킵: {e}")
        return None, None, debug_columns_shown


def main():
    etfs = load_master_list()
    print(f"[디버그] 전체목록 {len(etfs)}개 로드, 랭킹 수집 시작 (요청간격 {REQUEST_DELAY_SEC}초)")

    ranked = []
    debug_shown = False
    fail_count = 0

    for i, item in enumerate(etfs):
        ticker, name = item["ticker"], item["name"]

        if any(kw in name for kw in EXCLUDE_KEYWORDS):
            continue

        trading_value, market_cap, debug_shown = get_latest_metrics(ticker, debug_shown)
        time.sleep(REQUEST_DELAY_SEC)

        if trading_value is None:
            fail_count += 1
            continue

        ranked.append(
            {
                "ticker": ticker,
                "name": name,
                "trading_value": trading_value,
                "market_cap": market_cap,
            }
        )

        if (i + 1) % 100 == 0:
            print(f"[디버그] {i + 1}/{len(etfs)} 처리 완료, 현재 {len(ranked)}개 확보, 실패 {fail_count}건")

    print(f"[디버그] 전체 처리 완료. 성공 {len(ranked)}개, 최종 실패 {fail_count}개")

    ranked.sort(key=lambda x: x["trading_value"], reverse=True)
    top30 = ranked[:30]

    output_full = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_as_of": TO,
        "ranking_basis": "최근 거래대금 상위 (레버리지/인버스/순수채권형/금리연동/환헤지(H) 제외, 주식+채권 혼합형과 커버드콜은 포함)",
        "total_ranked": len(ranked),
        "failed_count": fail_count,
        "ranking": ranked,
    }
    output_top30 = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_as_of": TO,
        "ranking_basis": "최근 거래대금 상위 30개 (레버리지/인버스/순수채권형/금리연동/환헤지(H) 제외, 주식+채권 혼합형과 커버드콜은 포함)",
        "top30": top30,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/etf_ranking.json", "w", encoding="utf-8") as f:
        json.dump(output_full, f, ensure_ascii=False, indent=2)
    with open("data/etf_top30.json", "w", encoding="utf-8") as f:
        json.dump(output_top30, f, ensure_ascii=False, indent=2)

    print(f"[디버그] 총 {len(ranked)}개 순위 산정 완료, 상위 30개 저장")
    print(json.dumps(top30[:10], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
