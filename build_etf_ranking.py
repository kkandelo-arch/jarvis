"""
DC 자비스 - ETF 랭킹 수집 (거래대금·시가총액 기반 객관적 30개 선정)
data/etf_master_list.json(이름 목록)을 기반으로 각 ETF의 최근 거래대금·시가총액을 조회해
객관적 기준(거래대금 상위)으로 순위를 매김. 레버리지/인버스/채권류는 자동 제외.
전체 순위는 data/etf_ranking.json, 상위 30개는 data/etf_top30.json 에 저장
"""
import json
import os
from datetime import datetime, timedelta, timezone

from pykrx import stock

EXCLUDE_KEYWORDS = ["레버리지", "인버스", "곱버스", "국고채", "회사채", "단기채", "머니마켓"]

TODAY = datetime.now()
FROM_5D = (TODAY - timedelta(days=10)).strftime("%Y%m%d")  # 최근 영업일 확보용 여유
TO = TODAY.strftime("%Y%m%d")


def load_master_list():
    with open("data/etf_master_list.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("etfs", [])


def get_latest_metrics(ticker, debug_columns_shown):
    """최근 거래일의 거래대금·시가총액을 조회. 컬럼명은 버전별로 다를 수 있어 최초 1회만 로그로 확인."""
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
        print(f"[경고] {ticker} 지표 조회 실패, 스킵: {e}")
        return None, None, debug_columns_shown


def main():
    etfs = load_master_list()
    print(f"[디버그] 전체목록 {len(etfs)}개 로드, 랭킹 수집 시작")

    ranked = []
    debug_shown = False

    for i, item in enumerate(etfs):
        ticker, name = item["ticker"], item["name"]

        if any(kw in name for kw in EXCLUDE_KEYWORDS):
            continue

        trading_value, market_cap, debug_shown = get_latest_metrics(ticker, debug_shown)
        if trading_value is None:
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
            print(f"[디버그] {i + 1}/{len(etfs)} 처리 완료, 현재 {len(ranked)}개 확보")

    ranked.sort(key=lambda x: x["trading_value"], reverse=True)
    top30 = ranked[:30]

    output_full = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_as_of": TO,
        "ranking_basis": "최근 거래대금 상위 (레버리지/인버스/채권류 자동 제외)",
        "total_ranked": len(ranked),
        "ranking": ranked,
    }
    output_top30 = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_as_of": TO,
        "ranking_basis": "최근 거래대금 상위 30개 (레버리지/인버스/채권류 자동 제외)",
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
