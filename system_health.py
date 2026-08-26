"""
DC 자비스 - 시스템 자가검증 (v2.3 - 거래일 판정을 30일 범위 조회로 교체, 연휴 길이 무관하게 안전)
"""
import json
import os
import time
from datetime import datetime, timezone, timedelta

import requests
from pykrx import stock

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO = os.environ.get("GITHUB_REPOSITORY")
FORCE_ALL = os.environ.get("FORCE_ALL", "false").lower() == "true"

RETRIGGER_DELAY_SEC = 90

CHECKS = [
    {"file": "data/risk_score.json", "workflow": "risk_score.yml"},
    {"file": "data/etf_top30.json", "workflow": "build_etf_ranking.yml"},
    {"file": "data/etf_discovery.json", "workflow": "etf_discovery.yml"},
    {"file": "data/risk_alerts.json", "workflow": "risk_monitor.yml"},
    {"file": "data/portfolio_snapshot.json", "workflow": "portfolio_analysis.yml"},
]

KST = timezone(timedelta(hours=9))
MARKET_CLOSE_HOUR_KST = 16

# 거래일 조회 시 과거로 몇 일까지 넉넉하게 검색할지 (한국 최장 연휴도 10일을 넘긴 적 없음, 3배 여유)
CALENDAR_LOOKBACK_DAYS = 30


def _to_date(x):
    """pandas Timestamp든 datetime.date든 date로 통일"""
    return x.date() if hasattr(x, "date") else x


def get_latest_trading_day():
    """오늘(KST) 기준, 오늘을 포함해 가장 최근의 실제 거래일을 반환한다."""
    today = datetime.now(KST).date()
    try:
        fromdate = (today - timedelta(days=CALENDAR_LOOKBACK_DAYS)).strftime("%Y%m%d")
        todate = today.strftime("%Y%m%d")
        raw_days = stock.get_previous_business_days(fromdate=fromdate, todate=todate)
        days = sorted(_to_date(d) for d in raw_days)
        print(f"[디버그] 최근 {CALENDAR_LOOKBACK_DAYS}일 내 거래일 개수: {len(days)}, 마지막: {days[-1] if days else None}")
        past_or_today = [d for d in days if d <= today]
        if past_or_today:
            return max(past_or_today)
        print("[경고] 검색 범위 내 거래일을 찾지 못함, 오늘 날짜로 대체")
    except Exception as e:
        print(f"[경고] 거래일 조회 실패, 오늘 날짜로 대체: {e}")
    return today


def get_previous_trading_day(from_date):
    """from_date보다 이전의 가장 최근 거래일을 반환한다."""
    try:
        fromdate = (from_date - timedelta(days=CALENDAR_LOOKBACK_DAYS)).strftime("%Y%m%d")
        todate = (from_date - timedelta(days=1)).strftime("%Y%m%d")
        raw_days = stock.get_previous_business_days(fromdate=fromdate, todate=todate)
        days = sorted(_to_date(d) for d in raw_days)
        print(f"[디버그] {from_date} 이전 거래일 후보: {days[-3:] if days else '없음'}")
        if days:
            return max(days)
        print("[경고] 검색 범위 내 직전 거래일을 찾지 못함, 하루 전 날짜로 대체")
    except Exception as e:
        print(f"[경고] 직전 거래일 조회 실패: {e}")
    return from_date - timedelta(days=1)


def get_timestamp(data):
    ts = data.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def trigger_workflow(workflow_file):
    if not GITHUB_TOKEN or not REPO:
        print(f"[경고] GITHUB_TOKEN/REPO 정보 없음, {workflow_file} 자동 재실행 불가")
        return False
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    try:
        resp = requests.post(url, headers=headers, json={"ref": "main"}, timeout=15)
        if resp.status_code == 204:
            print(f"[디버그] {workflow_file} 재실행 요청 성공")
            return True
        print(f"[경고] {workflow_file} 재실행 요청 실패: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        print(f"[경고] {workflow_file} 재실행 요청 중 오류: {e}")
        return False


def evaluate_freshness(file_ts_utc, expected_trading_day, previous_trading_day, now_kst):
    if file_ts_utc is None:
        return "확인불가(timestamp 없음)"

    file_date = file_ts_utc.astimezone(KST).date()

    if file_date >= expected_trading_day:
        return "정상"

    if file_date == previous_trading_day and now_kst.hour < MARKET_CLOSE_HOUR_KST:
        return "정상(직전 거래일 기준, 오늘 장마감 전)"

    return "오래됨"


def main():
    now_kst = datetime.now(KST)
    expected_trading_day = get_latest_trading_day()
    previous_trading_day = get_previous_trading_day(expected_trading_day)
    print(f"[디버그] 기대 거래일: {expected_trading_day}, 직전 거래일: {previous_trading_day}, 현재(KST): {now_kst}")
    print(f"[디버그] FORCE_ALL={FORCE_ALL}")

    results = []
    any_stale = False
    pending_triggers = []

    for check in CHECKS:
        path = check["file"]
        ts = None
        status = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ts = get_timestamp(data)
            status = evaluate_freshness(ts, expected_trading_day, previous_trading_day, now_kst)
        except Exception as e:
            print(f"[경고] {path} 읽기 실패: {e}")
            status = "파일없음"

        result = {
            "file": path,
            "last_updated_utc": ts.isoformat() if ts else None,
            "last_updated_kst": ts.astimezone(KST).isoformat() if ts else None,
            "expected_trading_day": expected_trading_day.isoformat(),
            "previous_trading_day": previous_trading_day.isoformat(),
            "status": status,
        }
        print(f"[디버그] {path}: {status}")

        need_retrigger = FORCE_ALL or (status in ("오래됨", "파일없음"))
        if need_retrigger:
            if "정상" not in status:
                any_stale = True
            pending_triggers.append((check["workflow"], result))

        results.append(result)

    for i, (workflow_file, result) in enumerate(pending_triggers):
        if i > 0:
            print(f"[디버그] KRX 동시로그인 방지를 위해 {RETRIGGER_DELAY_SEC}초 대기...")
            time.sleep(RETRIGGER_DELAY_SEC)
        triggered = trigger_workflow(workflow_file)
        result["retrigger_requested"] = triggered
        result["retrigger_reason"] = "강제 전체갱신" if FORCE_ALL else "데이터 오래됨"

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "expected_trading_day": expected_trading_day.isoformat(),
        "previous_trading_day": previous_trading_day.isoformat(),
        "force_all": FORCE_ALL,
        "any_stale": any_stale,
        "checks": results,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/system_health.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
