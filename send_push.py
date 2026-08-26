"""
DC 자비스 - Web Push 알림 발송 공용 모듈
다른 스크립트에서 import해서 send_notification()을 호출하거나,
커맨드라인에서 --title/--body/--url 인자로 직접 실행 가능.
"""
import argparse
import json
import os
import sys

from pywebpush import webpush, WebPushException

SUBSCRIPTION_FILE = "data/push_subscription.json"


def _load_subscription():
    if not os.path.exists(SUBSCRIPTION_FILE):
        print(f"[알림 건너뜀] {SUBSCRIPTION_FILE} 없음 — 아직 구독 전")
        return None
    try:
        with open(SUBSCRIPTION_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            print(f"[알림 건너뜀] {SUBSCRIPTION_FILE} 비어있음")
            return None
        return json.loads(content)
    except Exception as e:
        print(f"[경고] {SUBSCRIPTION_FILE} 파싱 실패: {e}")
        return None


def send_notification(title, body, url=None, icon=None):
    """
    알림 1건 발송. 실패해도 예외를 던지지 않고 False를 반환한다.
    (알림 발송 실패로 다른 워크플로 전체가 죽지 않도록 하기 위함)
    """
    subscription = _load_subscription()
    if subscription is None:
        return False

    private_key = os.environ.get("VAPID_PRIVATE_KEY")
    subject = os.environ.get("VAPID_SUBJECT")
    if not private_key or not subject:
        print("[경고] VAPID_PRIVATE_KEY 또는 VAPID_SUBJECT 환경변수 없음")
        return False

    payload = {
        "title": title,
        "body": body,
        "url": url or "https://github.com/kkandelo-arch/jarvis",
    }
    if icon:
        payload["icon"] = icon

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=private_key,
            vapid_claims={"sub": subject},
        )
        print(f"[알림 발송 성공] {title} - {body}")
        return True
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            print(f"[알림 발송 실패] 구독이 만료/취소됨 (status={status}). "
                  f"docs/index.html 페이지에서 재구독 필요.")
        else:
            print(f"[알림 발송 실패] {e}")
        return False
    except Exception as e:
        print(f"[알림 발송 실패] 예상치 못한 오류: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="DC 자비스 푸시 알림 발송")
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--url", default=None)
    parser.add_argument("--icon", default=None)
    args = parser.parse_args()

    ok = send_notification(args.title, args.body, url=args.url, icon=args.icon)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
