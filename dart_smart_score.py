"""
DC 자비스 - DART 스마트발굴 (재무데이터 기반)
각 ETF의 구성종목 상위 5개(금액 비중 기준)를 뽑아 DART 재무데이터로
순이익 증가율을 조회하고, 비중 가중평균해서 ETF 단위 "재무건전성 점수"를 산출
결과는 data/dart_smart_scores.json 에 저장
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from pykrx import stock

DART_API_KEY = os.environ["DART_API_KEY"]
DART_FINANCIAL_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

TOP_N_HOLDINGS = 5
REQUEST_DELAY_SEC = 0.3

REPORT_ATTEMPTS = [
    (datetime.now().year, "11013"),
    (datetime.now().year, "11012"),
    (datetime.now().year - 1, "11011"),
]


def load_universe():
    universe = []
    try:
        with open("data/etf_top30.json", "r", encoding="utf-8") as f:
            ranking = json.load(f)
        for item in ranking.get("top30", []):
            universe.append((item["ticker"], item["name"]))
    except Exception as e:
        print(f"[경고] etf_top30.json 로드 실패: {e}")
    return universe


def load_corp_map():
    with open("data/dart_corp_map.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("mapping", {})


def find_holdings_date(ticker):
    for i in range(10):
        candidate = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = stock.get_etf_portfolio_deposit_file(ticker, candidate)
            if not df.empty:
                return df
        except Exception:
            continue
    return None


def get_top_holdings(etf_ticker):
    df = find_holdings_date(etf_ticker)
    if df is None or df.empty:
        return []

    df = df.copy()
    df["금액"] = df["금액"].astype(float)
    total = df["금액"].sum()
    if total <= 0:
        return []

    df["계산비중"] = df["금액"] / total
    df = df.sort_values("계산비중", ascending=False).head(TOP_N_HOLDINGS)

    return [(idx, round(row["계산비중"], 4)) for idx, row in df.iterrows()]


def parse_amount(raw):
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw).replace(",", ""))
    except ValueError:
        return None


def get_net_income_growth(corp_code, debug_shown):
    for year, reprt_code in REPORT_ATTEMPTS:
        try:
            params = {
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": reprt_code,
            }
            resp = requests.get(DART_FINANCIAL_URL, params=params, timeout=15)
            data = resp.json()

            if not debug_shown[0]:
                print(f"[디버그] DART 응답 예시(연도{year}, 보고서{reprt_code}): status={data.get('status')}")
                if data.get("list"):
                    print(f"[디버그] 첫 항목 키: {list(data['list'][0].keys())}")
                debug_shown[0] = True

            if data.get("status") != "000":
                continue

            rows = [r for r in data.get("list", []) if r.get("account_nm") == "당기순이익"]
            if not rows:
                rows = [r for r in data.get("list", []) if "당기순이익" in (r.get("account_nm") or "")]
            if not rows:
                continue

            row = next((r for r in rows if r.get("fs_div") == "CFS"), rows[0])

            this_term = parse_amount(row.get("thstrm_amount"))
            prev_term = parse_amount(row.get("frmtrm_amount"))

            if this_term is None or prev_term is None or prev_term == 0:
                continue

            growth_pct = (this_term - prev_term) / abs(prev_term) * 100
            return round(growth_pct, 2), f"{year}년 보고서코드{reprt_code}"

        except Exception as e:
            print(f"[경고] {corp_code} DART 조회 실패({year}/{reprt_code}): {e}")
            continue

    return None, None


def score_growth(growth_pct):
    if growth_pct is None:
        return None
    clipped = max(-30, min(30, growth_pct))
    return round((clipped + 30) * 100 / 60)


def main():
    universe = load_universe()
    corp_map = load_corp_map()
    print(f"[디버그] 스캔 대상 {len(universe)}개 ETF, DART 매핑 {len(corp_map)}개 종목")

    debug_shown = [False]
    results = []

    for etf_ticker, etf_name in universe:
        try:
            holdings = get_top_holdings(etf_ticker)
            if not holdings:
                print(f"[경고] {etf_name}({etf_ticker}) 구성종목 조회 실패, 스킵")
                continue

            holding_scores = []
            for stock_code, weight in holdings:
                corp_info = corp_map.get(stock_code)
                if not corp_info:
                    print(f"[정보] {etf_name} 구성종목 {stock_code} DART 매핑 없음(상장사 아닐 수 있음), 스킵")
                    continue

                growth_pct, source = get_net_income_growth(corp_info["corp_code"], debug_shown)
                time.sleep(REQUEST_DELAY_SEC)

                if growth_pct is None:
                    print(f"[정보] {corp_info['corp_name']}({stock_code}) 순이익 데이터 조회 실패, 스킵")
                    continue

                holding_scores.append(
                    {
                        "stock_code": stock_code,
                        "corp_name": corp_info["corp_name"],
                        "weight": weight,
                        "net_income_growth_pct": growth_pct,
                        "source": source,
                    }
                )

            if not holding_scores:
                print(f"[경고] {etf_name}({etf_ticker}) 유효한 재무데이터 없음, 스킵")
                continue

            total_weight = sum(h["weight"] for h in holding_scores)
            weighted_growth = sum(
                h["net_income_growth_pct"] * (h["weight"] / total_weight) for h in holding_scores
            )
            smart_score = score_growth(weighted_growth)

            results.append(
                {
                    "ticker": etf_ticker,
                    "name": etf_name,
                    "smart_score": smart_score,
                    "weighted_avg_growth_pct": round(weighted_growth, 2),
                    "scored_holdings_count": len(holding_scores),
                    "holdings": holding_scores,
                }
            )
            print(f"[디버그] {etf_name}({etf_ticker}) 스마트점수 {smart_score} (가중평균 증가율 {round(weighted_growth,2)}%)")

        except Exception as e:
            print(f"[경고] {etf_name}({etf_ticker}) 처리 중 오류, 스킵: {e}")
            continue

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scored_count": len(results),
        "results": results,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/dart_smart_scores.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[디버그] 총 {len(results)}개 ETF 스마트점수 산출 완료")


if __name__ == "__main__":
    main()
