"""
DC 자비스 - ETF 구성종목 조회 테스트 (스마트발굴 1단계)
KODEX 반도체 하나만 테스트로 조회해서, 실제 데이터 구조(컬럼명)를 확인하는 용도
결과는 data/test_etf_holdings.json 에 저장
"""
import json
import os
from datetime import datetime, timedelta, timezone

from pykrx import stock

TEST_TICKER = "091160"  # KODEX 반도체
TEST_NAME = "KODEX 반도체"

TODAY = datetime.now()


def find_recent_date():
    """최근 10일 내 데이터가 있는 날짜를 찾는다."""
    for i in range(10):
        candidate = (TODAY - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = stock.get_etf_portfolio_deposit_file(TEST_TICKER, candidate)
            if not df.empty:
                return candidate, df
        except Exception as e:
            print(f"[디버그] {candidate} 조회 실패: {e}")
            continue
    return None, None


def main():
    date_used, df = find_recent_date()

    if df is None:
        print("[오류] 최근 10일 내 구성종목 데이터를 찾지 못했습니다.")
        result = {"error": "데이터 없음"}
    else:
        print(f"[디버그] 기준일: {date_used}")
        print(f"[디버그] 컬럼: {list(df.columns)}")
        print(f"[디버그] 인덱스 이름: {df.index.name}")
        print(f"[디버그] 행 개수: {len(df)}")
        print(f"[디버그] 상위 5개 미리보기:\n{df.head(5)}")

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": TEST_TICKER,
            "name": TEST_NAME,
            "date_used": date_used,
            "columns": list(df.columns),
            "index_name": df.index.name,
            "row_count": len(df),
            "preview_top5": df.head(5).reset_index().to_dict(orient="records"),
        }

    os.makedirs("data", exist_ok=True)
    with open("data/test_etf_holdings.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print("[디버그] 저장 완료")


if __name__ == "__main__":
    main()
