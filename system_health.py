"""
DC 자비스 - 시스템 자가검증 (v2.2 - "장마감 전 예외" 로직을 직전 거래일 정확 대조로 수정)
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


def get_latest_trading_day():
    try:
        result = stock.get_nearest_business_day_in_a_week()
        print(f"[디버그] pykrx가 반환한 최근 거래일: {result}")
        return datetime.strptime(result, "%Y%m%d").date()
    except Exception as e:
        print(f"[경고] 거래일 조회 실패, 오늘 날짜로 대체: {e}")
        return datetime.now(KST).date()


def get_previous_trading_day(from_date):
    try:
        candidate = from_date - timedelta(days=1)
        result = stock.get_nearest_business_day_in_a_week(candidate.strftime("%Y%m%d"), prev=True)
        print(f"[디버그] 직전 거래일: {result}")
        return datetime.strptime(result, "%Y%m%d").date()
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
