# DC 자비스 — 퇴직연금 DC ETF 운용 자동화 시스템

## 프로젝트 개요
매매는 하지 않고, ETF 발굴·시장감시·리스크경보·포트폴리오 손익추적을 무료 인프라(GitHub Actions + KRX/DART/FRED 공개데이터)로 24시간 자동화하는 개인용 시스템. 사용자는 비개발자, 모든 코드는 Claude가 작성.

## 기술 스택
- 실행: GitHub Actions (스케줄 + 수동 실행 workflow_dispatch)
- 데이터: pykrx(KRX 시세/수급/구성종목, KRX_ID/KRX_PW 로그인 필요), DART Open API(재무데이터, DART_API_KEY), FRED API, yfinance
- 저장: 저장소 내 `data/*.json` 파일 (별도 DB 없음)

## 핵심 모듈 현황 (전부 정상 작동 확인됨)
| 모듈 | 파일 | 워크플로 | 설명 |
|---|---|---|---|
| 위험도 스코어링 | risk_score.py | risk_score.yml | VIX/하이일드스프레드/장단기금리차/코스피낙폭 4개 거시지표 종합 0~100점 |
| ETF 전체목록 | build_etf_master_list.py | build_etf_master_list.yml | KRX 전체 상장 ETF 티커+이름 (월1회) |
| ETF 랭킹(자동선정) | build_etf_ranking.py | build_etf_ranking.yml | 거래대금 상위 30개 자동 선정 (레버리지/인버스/순수채권형/금리연동/환헤지 제외, 매일) |
| ETF 검색 | search_etf.py | search_etf.yml | 종목명/티커 키워드 검색 (수동 입력 실행) |
| DART 기업매핑 | build_dart_corp_map.py | build_dart_corp_map.yml | 종목코드→DART고유번호 매핑 (월1회) |
| DART 스마트발굴 | dart_smart_score.py | dart_smart_score.yml | ETF 구성종목 상위5개 순이익 증가율 가중평균 (평일) |
| 백테스팅 | backtest.py | backtest.yml | 모멘텀+52주밴드 신호의 과거 승률 검증, etf_top30 기준 동적 (주1회) |
| **ETF 발굴(최종)** | etf_discovery.py | etf_discovery.yml | 5지표(모멘텀30%+52주밴드15%+거시10%+수급25%+DART스마트20%) 가중합산, 백테스트신뢰도 반영, 매수후보/관심종목/관망/제외권장 판단+근거 출력 |
| 강화 모니터링 | risk_monitor.py | risk_monitor.yml | 1일 급등락 + 52주밴드 과열/과매도 경보 |
| 포트폴리오 분석 | portfolio_analysis.py | portfolio_analysis.yml | data/holdings.json(사용자가 직접 입력) 기준 손익 계산 |
| **시스템 자가검증** | system_health.py | system_health.yml | KRX 실제 거래일 캘린더로 각 데이터의 최신성 판정, 오래되면 자동 재실행, force_all 옵션으로 강제 전체갱신 가능 |

## 사용자가 직접 관리하는 데이터 파일
- `data/holdings.json` — 실제 보유종목 (수동 입력)
- `data/custom_universe.json` — 임의 추가 종목 (수동 입력, 기본은 `[]`)

## 알려진 설계 원칙 / 주의사항
1. **모든 워크플로 마지막 저장 단계는 `git pull --no-rebase -X ours` 사용** (여러 워크플로 동시 실행 시 저장 충돌 방지, 8개 파일 전부 적용 완료)
2. **KRX 로그인은 동시에 여러 워크플로가 시도하면 충돌남** → system_health.py는 재실행 요청 사이 90초 대기
3. 채권혼합형은 포함, 순수채권형/CD금리/환헤지(H)는 제외 (EXCLUDE_KEYWORDS 참고)
4. 레버리지/인버스는 항상 제외
5. 매매는 절대 하지 않음 — 발굴/판단/알림까지만

## 다음 단계 (아직 안 함)
- PWA(홈화면 설치 앱) + 채팅 엔진(Cloudflare Workers + Groq) 구축
- Web Push 알림
- 완전한 거래일 캘린더 기반 자가검증 검증 완료 (v2.2까지 적용, 최종 테스트 필요)

## 새 채팅에서 이어가는 법
이 저장소 링크(`https://github.com/kkandelo-arch/jarvis`)와 이 README를 Claude에게 알려주면, 파일들을 직접 열어보며 현재 상태를 파악하고 이어서 작업 가능.
