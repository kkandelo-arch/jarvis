"""
DC 자비스 - ETF 전체목록 수집 (v1.2 - 이름 데이터 타입 오류 수정)
KRX에 상장된 전체 ETF의 티커+이름을 수집해서 data/etf_master_list.json 에 저장
"""
import json
import os
from datetime import datetime, timedelta, timezone

from pykrx import stock


def find_recent_trading_date():
    for i in range(7):
        candidate = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            tickers = stock.get_etf_ticker_list(candidate)
        except Exception as e:
            print(f"[경고] {candidate} 조회 실패: {e}")
            continue
        print(f"[디버그] {candidate} 기준 티커 {len(tickers)}개 확인")
        if tickers:
            return candidate, tickers
    return None, []


def safe_name(raw_name):
    """get_etf_ticker_name 결과가 문자열이 아닌 경우(Series 등) 안전하게 문자열로 변환"""
    if hasattr(raw_name, "iloc"):
        raw_name = raw_name.iloc[0]
    return str(raw_name)


def main():
    date_used, tickers = find_recent_trading_date()

    if not tickers:
        print("[오류] 최근 7일 내 유효한 ETF 티커 목록을 찾지 못했습니다. 빈 파일로 저장합니다.")

    print(f"[디버그] 사용 기준일: {date_used}, 전체 ETF 티커 {len(tickers)}개")
    print("[디버그] 이름 조회 시작 (다소 시간 걸릴 수 있음)")

    etfs = []
    for i, ticker in enumerate(tickers):
        try:
            name = safe_name(stock.get_etf_ticker_name(ticker))
            etfs.append({"ticker": ticker, "name": name})
        except Exception as e:
            print(f"[경고] {ticker} 이름 조회 실패, 스킵: {e}")
            continue

        if (i + 1) % 100 == 0:
            print(f"[디버그] {i + 1}/{len(tickers)} 처리 완료")

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "date_used": date_used,
        "count": len(etfs),
        "etfs": etfs,
    }

    os.makedirs("data", exist_ok=True)
    filepath = "data/etf_master_list.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[디버그] 파일 존재 확인: {os.path.exists(filepath)}")
    print(f"[디버그] 총 {len(etfs)}개 ETF 목록 저장 완료")


if __name__ == "__main__":
    main()
