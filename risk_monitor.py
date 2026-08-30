"""
DC 자비스 - 강화 모니터링 모듈 (v1.2 - 보유종목 최우선 감시 편입)
holdings.json(보유종목, 최우선) + etf_top30.json(거래대금 상위) + custom_universe.json(임의추가)을
합쳐서 1일 급등락 + 52주 밴드 과열/과매도 신호를 점검
결과는 data/risk_alerts.json 에 저장됨
"""
import json
import os
from datetime import datetime, timedelta, timezone

from pykrx import stock

from send_push import send_notification

EXCLUDE_KEYWORDS = [
    "레버리지", "인버스", "곱버스",
    "국고채", "회사채", "단기채", "머니마켓", "금리",
    "(H)",
]

TODAY = datetime.now()
FROM_60D = (TODAY - timedelta(days=60)).strftime("%Y%m%d")
TO = TODAY.strftime("%Y%m%d")

PRICE_CHANGE_LEVELS = [
    (10, "긴급"),
    (7, "경고"),
    (5, "주의"),
    (3, "정보"),
]


def load_universe():
    universe = []
    existing = set()

    # 보유종목은 최우선으로 감시 대상에 편입 (top30/custom 여부와 무관하게 항상 감시)
    try:
        with open("data/holdings.json", "r", encoding="utf-8") as f:
            holdings = json.load(f)
        for item in holdings:
            ticker = item.get("ticker")
            name = item.get("name", ticker)
            if ticker and ticker not in existing:
                universe.append((ticker, name, "보유종목"))
                existing.add(ticker)
        print(f"[디버그] 보유종목 {len(existing)}개 감시목록에 최우선 편입")
    except Exception as e:
        print(f"[경고] holdings.json 로드 실패(없어도 정상 동작): {e}")

    try:
        with open("data/etf_top30.json", "r", encoding="utf-8") as f:
            ranking = json.load(f)
        added = 0
        for item in ranking.get("top30", []):
            ticker = item["ticker"]
            if ticker not in existing:
                universe.append((ticker, item["name"], "기본(거래대금상위)"))
                existing.add(ticker)
                added += 1
        print(f"[디버그] 랭킹 기반 기본목록 {added}개 추가 (보유종목과 중복 제외)")
    except Exception as e:
        print(f"[경고] etf_top30.json 로드 실패: {e}")

    try:
        with open("data/custom_universe.json", "r", encoding="utf-8") as f:
            custom = json.load(f)
        for item in custom:
            ticker = item.get("ticker")
            name = item.get("name", ticker)
            if ticker and ticker not in existing:
                universe.append((ticker, name, "사용자추가"))
                existing.add(ticker)
    except Exception as e:
        print(f"[경고] custom_universe.json 로드 실패(없어도 정상 동작): {e}")

    print(f"[디버그] 최종 감시 대상 총 {len(universe)}개 (보유종목 포함)")
    return universe


def price_change_level(pct):
    abs_pct = abs(pct)
    for threshold, label in PRICE_CHANGE_LEVELS:
        if abs_pct >= threshold:
            return label
    return None


def main():
    universe = load_universe()
    print(f"[디버그] 총 모니터링 대상 {len(universe)}개")
    alerts = []
    checked = 0

    for ticker, name, origin in universe:
        if any(kw in name for kw in EXCLUDE_KEYWORDS):
            continue

        try:
            ohlcv = stock.get_etf_ohlcv_by_date(FROM_60D, TO, ticker)
            closes = ohlcv["종가"].dropna()
            if len(closes) < 2:
                print(f"[경고] {name}({ticker}) 데이터 부족, 스킵")
                continue

            checked += 1
            last = closes.iloc[-1]
            prev = closes.iloc[-2]
            change_pct = round((last / prev - 1) * 100, 2)

            level = price_change_level(change_pct)
            if level:
                direction = "급등" if change_pct > 0 else "급락"
                alerts.append(
                    {
                        "ticker": ticker,
                        "name": name,
                        "origin": origin,
                        "type": "가격변동",
                        "level": level,
                        "change_pct": change_pct,
                        "message": f"{name} 1일 {direction} {abs(change_pct)}%",
                    }
                )
                print(f"[디버그] {name}({ticker}) 가격변동 알림: {level} ({change_pct}%)")

            window = closes.tail(250)
            high52, low52 = window.max(), window.min()
            if high52 != low52:
                position = (last - low52) / (high52 - low52) * 100
                if position >= 95:
                    alerts.append(
                        {
                            "ticker": ticker,
                            "name": name,
                            "origin": origin,
                            "type": "리밸런싱검토",
                            "level": "주의",
                            "band_position_pct": round(position, 1),
                            "message": f"{name} 52주 밴드 상단 근접({round(position,1)}%) - 비중 축소 검토",
                        }
                    )
                elif position <= 5:
                    alerts.append(
                        {
                            "ticker": ticker,
                            "name": name,
                            "origin": origin,
                            "type": "리밸런싱검토",
                            "level": "주의",
                            "band_position_pct": round(position, 1),
                            "message": f"{name} 52주 밴드 하단 근접({round(position,1)}%) - 저가매수 후보 검토",
                        }
                    )

        except Exception as e:
            print(f"[경고] {name}({ticker}) 모니터링 중 오류, 스킵: {e}")
            continue

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checked_count": checked,
        "alert_count": len(alerts),
        "alerts": alerts,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/risk_alerts.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(json.dumps(output, ensure_ascii=False, indent=2))

    # 알림 발송: "긴급"/"경고" 등급만 발송 (주의/정보는 알림 피로 방지 위해 생략)
    urgent = [a for a in alerts if a.get("level") in ("긴급", "경고")]
    if urgent:
        names = ", ".join(a["message"] for a in urgent[:3])
        more = f" 외 {len(urgent) - 3}건" if len(urgent) > 3 else ""
        send_notification(
            title=f"⚠️ DC 자비스 리스크 알림 ({len(urgent)}건)",
            body=f"{names}{more}",
            url="https://github.com/kkandelo-arch/jarvis/blob/main/data/risk_alerts.json",
        )


if __name__ == "__main__":
    main()
