"""
DC 자비스 - ETF 검색 (전체목록에서 이름/티커로 검색)
"""
import json
import os

keyword = os.environ.get("SEARCH_KEYWORD", "").strip()

with open("data/etf_master_list.json", "r", encoding="utf-8") as f:
    master = json.load(f)

matches = [
    e for e in master["etfs"]
    if keyword in e["name"] or keyword == e["ticker"]
]

result = {"keyword": keyword, "match_count": len(matches), "matches": matches}

os.makedirs("data", exist_ok=True)
with open("data/etf_search_result.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(json.dumps(result, ensure_ascii=False, indent=2))
