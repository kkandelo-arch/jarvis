"""
DC 자비스 - 포트폴리오 분석 모듈 (3단계)
holdings.json(보유종목)을 읽어서 현재가 기준 평가손익을 계산
결과는 data/portfolio_snapshot.json 에 저장, 이력은 data/portfolio_history.json 에 누적
"""
import json
import os
from datetime import datetime, timezone

from pykrx import stock


def load_holdings():
    try:
        with open("data/holdings.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[경고] holdings.json 로드 실패, 빈 포트폴리오로 처리: {e}")
        return []


def get_current_price(ticker):
    try:
        today = datetime.now().strftime("%Y%m%d")
        ohlcv = stock.get_etf_ohlcv_by_date(today, today, ticker)
        if ohlcv.empty:
            from datetime import timedelta
            start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
            ohlcv = stock.get_etf_ohlcv_by_date(start, today, ticker)
            if ohlcv.empty:
                return None
        return float(ohlcv["종가"].dropna().iloc[-1])
    except Exception as e:
        print(f"[경고] {ticker} 현재가 조회 실패: {e}")
        return None


def main():
    holdings = load_holdings()
    print(f"[디버그] 보유종목 {len(holdings)}개 로드")

    items = []
    total_cost = 0
    total_value = 0

    for h in holdings:
        ticker = h["ticker"]
        name = h.get("name", ticker)
        qty = h["quantity"]
        avg_price = h["avg_price"]

        current_price = get_current_price(ticker)
        if current_price is None:
            print(f"[경고] {name}({ticker}) 현재가 조회 실패, 평가 제외")
            continue

        cost = qty * avg_price
        value = qty * current_price
        pnl = value - cost
        pnl_pct = round((pnl / cost) * 100, 2) if cost > 0 else 0

        total_cost += cost
        total_value += value

        items.append(
            {
                "ticker": ticker,
                "name": name,
                "quantity": qty,
                "avg_price": avg_price,
                "current_price": current_price,
                "purchase_date": h.get("purchase_date"),
                "eval_amount": round(value),
                "pnl_amount": round(pnl),
                "pnl_pct": pnl_pct,
            }
        )
        print(f"[디버그] {name}({ticker}) 평가손익 {pnl_pct}%")

    total_pnl = total_value - total_cost
    total_pnl_pct = round((total_pnl / total_cost) * 100, 2) if total_cost > 0 else 0

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "holdings_count": len(items),
        "total_cost": round(total_cost),
        "total_eval_amount": round(total_value),
        "total_pnl_amount": round(total_pnl),
        "total_pnl_pct": total_pnl_pct,
        "items": items,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/portfolio_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    history_path = "data/portfolio_history.json"
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            raw_history = json.load(f)
    except Exception:
        raw_history = []

    # 하루 3회 실행되면서 같은 날짜가 중복 기록되던 문제 정리:
    # 날짜별로 마지막 값만 남기고, 오늘자는 이번 실행 값으로 덮어씀(upsert)
    by_date = {}
    for entry in raw_history:
        if entry.get("date"):
            by_date[entry["date"]] = entry

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by_date[today_str] = {
        "date": today_str,
        "total_eval_amount": round(total_value),
        "total_pnl_pct": total_pnl_pct,
    }

    history = [by_date[d] for d in sorted(by_date.keys())][-365:]

    dedup_count = len(raw_history) - len({e.get("date") for e in raw_history})
    if dedup_count > 0:
        print(f"[디버그] 기존 중복 기록 {dedup_count}건 정리됨 (날짜별 1건으로 통합)")

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(json.dumps(snapshot, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
