# DC 자비스 — 퇴직연금 DC ETF 운용 자동화 시스템

## 프로젝트 개요
매매는 하지 않고, ETF 발굴·시장감시·리스크경보·포트폴리오 손익추적을 무료 인프라(GitHub Actions + KRX/DART/FRED 공개데이터 + Cloudflare Workers + Groq)로 24시간 자동화하는 개인용 시스템. 사용자는 비개발자, 모든 코드는 Claude가 작성. 실사용 기기는 삼성 갤럭시 S24(홈화면 설치 PWA), 구축 작업은 PC에서 진행.

## 기술 스택
- 데이터 자동화: GitHub Actions (스케줄 + 수동 실행 workflow_dispatch)
- 데이터 소스: pykrx(KRX 시세/수급/구성종목, KRX_ID/KRX_PW 로그인 필요), DART Open API(재무데이터, DART_API_KEY), FRED API, yfinance
- 저장: 저장소 내 `data/*.json` 파일 (별도 DB 없음)
- 앱: GitHub Pages(`docs/`) 기반 PWA — 대시보드 + 알림구독 + 채팅 통합 단일 페이지
- 알림: Web Push (VAPID 키 기반, pywebpush)
- 채팅엔진: Cloudflare Workers(백엔드 프록시) + Groq API(LLM, 모델: `openai/gpt-oss-120b`)

## 핵심 데이터 모듈 현황 (전부 정상 작동 확인됨)
| 모듈 | 파일 | 워크플로 | 설명 |
|---|---|---|---|
| 위험도 스코어링 | risk_score.py | risk_score.yml | VIX/하이일드스프레드/장단기금리차/코스피낙폭 4개 거시지표 종합 0~100점 |
| ETF 전체목록 | build_etf_master_list.py | build_etf_master_list.yml | KRX 전체 상장 ETF 티커+이름 (월1회) |
| ETF 랭킹(자동선정) | build_etf_ranking.py | build_etf_ranking.yml | 거래대금 상위 30개 자동 선정 (레버리지/인버스/순수채권형/금리연동/환헤지 제외, 매일) |
| ETF 검색 | search_etf.py | search_etf.yml | 종목명/티커 키워드 검색 (수동 입력 실행) |
| DART 기업매핑 | build_dart_corp_map.py | build_dart_corp_map.yml | 종목코드→DART고유번호 매핑 (월1회) |
| DART 스마트발굴 | dart_smart_score.py | dart_smart_score.yml | ETF 구성종목 상위5개 순이익 증가율 가중평균 (평일) |
| 백테스팅 | backtest.py | backtest.yml | 모멘텀+52주밴드 신호의 과거 승률 검증, etf_top30 기준 동적 (주1회) |
| **ETF 발굴(최종)** | etf_discovery.py | etf_discovery.yml | 5지표(모멘텀30%+52주밴드15%+거시10%+수급25%+DART스마트20%) 가중합산, 백테스트신뢰도 반영, 매수후보/관심종목/관망/제외권장 판단+근거 출력, **매수후보 발견 시 Web Push 알림 발송** |
| 강화 모니터링 | risk_monitor.py | risk_monitor.yml | 1일 급등락 + 52주밴드 과열/과매도 경보, **긴급/경고 등급만 Web Push 알림 발송** |
| 포트폴리오 분석 | portfolio_analysis.py | portfolio_analysis.yml | data/holdings.json(사용자가 직접 입력) 기준 손익 계산 |
| **시스템 자가검증** | system_health.py | system_health.yml | KRX 거래일을 `get_previous_business_days`(30일 범위 조회)로 판정해 연휴 길이와 무관하게 안전. 오래되면 자동 재실행, force_all 옵션으로 강제 전체갱신 가능 |
| 알림 발송 공용모듈 | send_push.py | (다른 워크플로에서 import) | VAPID 기반 Web Push 발송, 구독 없거나 실패해도 다른 작업 안 죽게 안전 처리 |

## PWA + 알림 + 채팅 (완료)
- **`docs/index.html`**: 대시보드(위험도/보유손익/발굴TOP5/리스크경보) + 🔔 알림구독 + 💬 채팅창이 통합된 단일 페이지. `manifest.json` + 아이콘으로 S24 홈화면에 앱처럼 설치됨(PWA).
- **`docs/sw.js`**: 서비스워커, Push 이벤트 수신 후 시스템 알림 표시.
- **`docs/manifest.json`**: PWA 설치 메타데이터.
- **알림 흐름**: 사용자가 대시보드 🔔 버튼으로 구독 → JSON을 `data/push_subscription.json`에 수동 저장(1회) → `risk_monitor.py`/`etf_discovery.py`가 조건 충족 시 `send_push.py`로 발송.
- **채팅 흐름**: 대시보드 💬 버튼 → Cloudflare Worker(`dc-jarvis-chat`)에 POST → Worker가 GitHub의 실시간 `data/*.json` 5종을 읽어 시스템 프롬프트로 구성 → Groq(`openai/gpt-oss-120b`) 호출 → 답변 반환. 대화 이력은 브라우저 메모리에만 유지(새로고침 시 초기화).
- Worker 코드: Cloudflare 대시보드(`dash.cloudflare.com` → Workers 및 Pages → `dc-jarvis-chat` → 코드 편집)에서 직접 관리, 이 저장소에는 사본 없음 — **수정 시 반드시 Cloudflare 쪽에서 직접 편집**.

## 사용자가 직접 관리하는 데이터 파일
- `data/holdings.json` — 실제 보유종목 (수동 입력)
- `data/custom_universe.json` — 임의 추가 종목 (수동 입력, 기본은 `[]`)
- `data/push_subscription.json` — 알림 구독 기기 정보 (S24에서 구독 시 자동 생성된 JSON을 붙여넣어 저장, 재구독 시 덮어쓰기)

## 알려진 설계 원칙 / 주의사항
1. **모든 워크플로 마지막 저장 단계는 `git pull --no-rebase -X ours` 사용** (여러 워크플로 동시 실행 시 저장 충돌 방지, 12개 파일 전부 적용 완료 및 검증됨)
2. **KRX 로그인은 동시에 여러 워크플로가 시도하면 충돌남** → system_health.py는 재실행 요청 사이 90초 대기
3. 채권혼합형은 포함, 순수채권형/CD금리/환헤지(H)는 제외 (EXCLUDE_KEYWORDS 참고)
4. 레버리지/인버스는 항상 제외
5. 매매는 절대 하지 않음 — 발굴/판단/알림/채팅 답변까지만
6. **거래일 판정은 `pykrx.stock.get_previous_business_days(fromdate, todate)`를 30일 범위로 조회하는 방식 사용** (구버전 `get_nearest_business_day_in_a_week`는 정확히 7일짜리 창이라 최장 연휴 시 실패 위험 있었음 — 실제 2025년 7일 연휴 사례로 검증 후 교체)
7. **VAPID 개인키는 PEM이 아니라 raw base64url(BEGIN/END 없이 32바이트) 형식으로 저장** — `pywebpush`가 그 형식만 인식함
8. **VAPID_SUBJECT는 경로 없는 origin만 허용** (예: `https://github.com`, 경로 포함 시 형식 오류)
9. **Groq 채팅 시스템 프롬프트는 마크다운 표(`|`)·헤더(`#`) 금지, `-` 목록과 `**볼드**`만 허용** — 좁은 모바일 채팅창 특성 반영
10. Groq 모델은 수시로 단종될 수 있음 (2026-06-17 `llama-3.3-70b-versatile` 단종 확인, 현재 `openai/gpt-oss-120b` 사용 중) — 채팅 오류 시 가장 먼저 의심할 부분
11. 데이터 조회는 `raw.githubusercontent.com`에서 캐시 우회용 `?t=timestamp` 쿼리 붙여서 항상 최신 반영

## 다음 단계 (선택적 개선, 필수 아님)
- S24 배터리 최적화 예외 설정(알림 지연 개선, 사용자 판단에 맡김 — 필수 아님)
- 채팅 대화 이력을 새로고침 후에도 유지하고 싶다면 로컬 스토리지 등 영속화 고려 가능 (현재는 매번 새 대화로 시작, 의도된 단순화)

## 새 채팅에서 이어가는 법
이 저장소 링크(`https://github.com/kkandelo-arch/jarvis`)와 이 README를 Claude에게 알려주면, 파일들을 직접 열어보며 현재 상태를 파악하고 이어서 작업 가능. Cloudflare Worker 코드는 저장소에 없으므로, Worker 관련 작업이 필요하면 Cloudflare 대시보드 접속 상태에서 화면을 캡처해 공유.
