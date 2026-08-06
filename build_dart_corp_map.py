"""
DC 자비스 - DART 기업고유번호 매핑 수집
DART Open API의 corpCode.xml(전체 상장사 고유번호 목록, zip 압축)을 받아서
종목코드 -> DART고유번호 매핑을 data/dart_corp_map.json 에 저장
"""
import io
import json
import os
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

import requests

DART_API_KEY = os.environ["DART_API_KEY"]
CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"


def main():
    print("[디버그] DART 기업고유번호 목록 다운로드 시도...")
    resp = requests.get(CORP_CODE_URL, params={"crtfc_key": DART_API_KEY}, timeout=30)
    resp.raise_for_status()

    print(f"[디버그] 응답 크기: {len(resp.content)} bytes, content-type: {resp.headers.get('content-type')}")

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
            print(f"[디버그] zip 내부 파일: {names}")
            xml_bytes = zf.read(names[0])
    except zipfile.BadZipFile:
        print(f"[오류] zip 파일이 아님. 응답 내용 일부: {resp.content[:300]}")
        raise

    root = ET.fromstring(xml_bytes)

    mapping = {}
    total = 0
    for corp in root.findall("list"):
        total += 1
        corp_code = corp.findtext("corp_code")
        corp_name = corp.findtext("corp_name")
        stock_code = corp.findtext("stock_code")
        if stock_code and stock_code.strip():
            mapping[stock_code.strip()] = {
                "corp_code": corp_code,
                "corp_name": corp_name,
            }

    print(f"[디버그] 전체 {total}건 중 상장(종목코드 보유) {len(mapping)}건 매핑")

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_count": len(mapping),
        "mapping": mapping,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/dart_corp_map.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("[디버그] 저장 완료")


if __name__ == "__main__":
    main()
