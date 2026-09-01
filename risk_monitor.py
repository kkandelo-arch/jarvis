"""
DC 자비스 - 강화 모니터링 모듈 (v1.3 - 보유종목 전량표시 + 개별알림 + 중복발송방지)
holdings.json(보유종목, 최우선) + etf_top30.json(거래대금 상위) + custom_universe.json(임의추가)을
합쳐서 1일 급등락 + 52주 밴드 과열/과매도 신호를 점검
보유종목은 변동폭과 무관하게 항상 기록됨(정상 구간 포함), 그 외는 3%↑ 변동 시에만 기록
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

NOTIFY_STATE_PATH = "data/notification_state.json"
DEDUP_WINDOW_HOURS = 4
PWA_URL = "https://kkandelo-arch.github.io/jarvis/"


def load_notify_state():
    try:
        with open(NOTIFY_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_notify_state(state):
    with open(NOTIFY_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def should_notify(state, key, level):
    """같은 종목+같은 유형의 알림이 등급 변화 없이 DEDUP_WINDOW_HOURS 이내 재발생하면 재발송 생략"""
    entry = state.get(key)
    now = datetime.now(timezone.utc)
    if not entry:
        return True
    if entry.get("last_level") != level:
        return True
    try:
        last_sent = datetime.fromisoformat(entry["last_sent"])
    except Exception:
        return True
    return (now - last_sent) > timedelta(hours=DEDUP_WINDOW_HOURS)


def mark_notified(state, key, level):
    state[key] = {"last_level": level, "last_sent": datetime.now(timezone.utc).isoformat()}


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
            is_holding = origin == "보유종목"

            level = price_change_level(change_pct)
            if level or is_holding:
                direction = "급등" if change_pct > 0 else ("급락" if change_pct < 0 else "보합")
                display_level = level or "정상"
                alerts.append(
                    {
                        "ticker": ticker,
                        "name": name,
                        "origin": origin,
                        "type": "가격변동",
                        "level": display_level,
                        "change_pct": change_pct,
                        "message": f"{name} 1일 {direction} {abs(change_pct)}%",
                    }
                )
                print(f"[디버그] {name}({ticker}) 가격변동 기록: {display_level} ({change_pct}%)")

            window = closes.tail(250)
            high52, low52 = window.max(), window.min()
            if high52 != low52:
                position = (last - low52) / (high52 - low52) * 100
                if position >= 95:
                    action = "비중 축소 검토" if is_holding else "신규매수 시 유의(과열구간)"
                    alerts.append(
                        {
                            "ticker": ticker,
                            "name": name,
                            "origin": origin,
                            "type": "리밸런싱검토",
                            "level": "주의",
                            "band_position_pct": round(position, 1),
                            "message": f"{name} 52주 밴드 상단 근접({round(position,1)}%) - {action}",
                        }
                    )
                elif position <= 5:
                    action = "저가매수 검토" if is_holding else "관망 후보(저평가구간)"
                    alerts.append(
                        {
                            "ticker": ticker,
                            "name": name,
                            "origin": origin,
                            "type": "리밸런싱검토",
                            "level": "주의",
                            "band_position_pct": round(position, 1),
                            "message": f"{name} 52주 밴드 하단 근접({round(position,1)}%) - {action}",
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

    # ===== 알림 발송 (건별 개별 발송 + 중복 발송 방지) =====
    notify_state = load_notify_state()
    sent_count = 0

    # 1) 가격변동: "긴급"/"경고"만 발송 (주의/정보/정상은 앱에서 확인, 알림 피로 방지)
    urgent_price = [a for a in alerts if a["type"] == "가격변동" and a["level"] in ("긴급", "경고")]
    for a in urgent_price:
        key = f"{a['ticker']}_가격변동"
        if not should_notify(notify_state, key, a["level"]):
            continue
        icon = "🚨" if a["level"] == "긴급" else "⚠️"
        ok = send_notification(
            title=f"{icon} DC 자비스 {a['level']} · {a['name']}",
            body=a["message"],
            url=PWA_URL,
        )
        if ok:
            mark_notified(notify_state, key, a["level"])
            sent_count += 1

    # 2) 리밸런싱검토: 보유종목만 발송 (미보유는 앱에서 확인, 알림 피로 방지)
    rebal_holding = [a for a in alerts if a["type"] == "리밸런싱검토" and a["origin"] == "보유종목"]
    for a in rebal_holding:
        key = f"{a['ticker']}_리밸런싱검토"
        if not should_notify(notify_state, key, a["level"]):
            continue
        ok = send_notification(
            title=f"📐 DC 자비스 리밸런싱 검토 · {a['name']}",
            body=a["message"].replace(f"{a['name']} ", ""),
            url=PWA_URL,
        )
        if ok:
            mark_notified(notify_state, key, a["level"])
            sent_count += 1

    save_notify_state(notify_state)
    print(f"[디버그] 알림 {sent_count}건 발송 (중복방지로 생략된 건 제외)")


if __name__ == "__main__":
    main()
