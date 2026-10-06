# INVESTBRIEF_OPS_STABILIZATION

> 지시서 G — InvestBrief 런타임 정착(launchd/venv) · KRX 수급 조회 견고화(재로그인) · 수급 소스 폴백(네이버+전일 캐시)
> 대상: Claude Code / InvestBrief (`~/dev/investbrief`, **macOS 로컬 실행** — 과거 문서의 Oracle VM 서술은 폐기)
> 작성 기준일: 2026-07-03
> 우선순위: **P1** — 매일 아침 브리프의 핵심 데이터(수급)가 오늘까지 침묵 실패 중이었고, 백엔드 자체가 수동 프로세스라 터미널 종료·재부팅 한 번에 서비스가 소리 없이 죽는 상태. StockAI와 독립 배포.
> 선행: 없음. 단 2026-07-03 응급조치 완료 상태를 전제 — homebrew python3.11에 pykrx 설치됨, KRX 계정(inpenet69) 로그인 검증 완료, `backend/.env`에 KRX_ID/KRX_PW 추가됨.

---

## 1. 개요 (Overview)

2026-07-03 진단으로 확정된 사실: 모닝 브리프의 "수급 데이터 미제공 — 판단 유보"는 (a) 실행 파이썬(homebrew 3.11)에 pykrx 미설치 → 설치 후 (b) KRX 정보데이터시스템이 투자자별 매매 데이터를 **로그인 필수**로 전환(KRX_ID/KRX_PW 요구, 토큰 1시간 만료)한 이중 원인이었다. 응급조치(설치+계정)로 조회는 성공했으나 세 가지 구조 문제가 남았다:

1. **런타임**: 백엔드가 launchd·crontab 없이 터미널 수동 프로세스(포트 8001, homebrew 파이썬 직접) — 죽으면 아무도 모른다. 프론트도 `next dev`(개발 모드)로 상시 운영 중.
2. **KRX 세션**: 로그인 토큰 1시간 만료 vs 백엔드는 장기 실행 — 다음 날 07:40 조회 시 만료 토큰의 자동 재로그인 여부 미검증. 실패하면 브리프는 다시 "미제공"으로 돌아간다.
3. **단일 소스**: 수급이 KRX(pykrx 크롤) 하나에 의존 — KRX 정책 변경 한 번에 또 부러진다 (이번이 그 실증).

본 지시서는 StockAI에서 검증된 운영 패턴(launchd KeepAlive + 재시작 해시 검증 + status 별칭)의 축소판을 InvestBrief에 이식하고, 수급 조회를 3단 폴백으로 견고화한다.

---

## 2. 배경 및 문제 정의 (Background & Problem Statement)

### 2026-07-03 확정 사실
- `ps`/`launchctl`/`crontab` 조사: 백엔드(PID 31108, :8001)는 `/opt/homebrew/.../python3.11` 직접 실행, venv 없음(`investbrief/` 루트에 venv 부재), launchd·crontab 등록 없음. 프론트는 `next dev --port 3001`.
- pykrx 재현 테스트: 미설치 → 설치 후 `KRX 로그인 실패: KRX_ID 또는 KRX_PW 환경 변수가 설정되지 않았습니다` + `KeyError: '거래대금'` → 계정 인증 후 정상 수신 (로그인 09:13, **만료 10:13 = 1시간 토큰**).
- `investor_flow_collector.py`: 예외 → None → 프롬프트에 "수급 데이터 없음" → 브리프 AI가 "미제공, 판단 유보" 생성. 실패가 텔레그램 어디에도 경보되지 않는 침묵 실패.

### 함의
- 이 서비스는 "안 오면 눈치채기 어려운" 아침 브리프다 — 침묵 사망·침묵 열화 둘 다 관측 장치가 없다.
- 환경이 고정되지 않아(글로벌 파이썬, 문서화 없음) 오늘 같은 의존성 사고가 재발 가능하다.

---

## 3. 근본 원인 분석 (Root Cause Analysis)

- **런타임**: 초기 개발 상태 그대로 운영에 진입 — 배포·상주화 단계가 생략됨.
- **의존성 사고**: 수급 기능 코드는 커밋됐지만 requirements/환경 반영이 누락 — 실행 환경이 venv로 고정돼 있지 않으니 "어떤 파이썬으로 띄웠는가"에 따라 결과가 달라짐.
- **KRX**: 무료 비로그인 크롤 전제가 KRX 정책 변경으로 무효화 — 외부 비공식 소스의 태생적 리스크.
- **침묵 실패**: 수집 실패가 None으로 흡수되고 하류(AI)가 자연어로 완충 — 우아한 열화 자체는 옳았으나, 열화 발생 사실이 운영자에게 전달되지 않음.

---

## 4. 목표 및 비목표 (Goals / Non-Goals)

### 목표
1. 백엔드가 launchd KeepAlive 상주 서비스로 전환 (재부팅·크래시 자동 복구), venv로 환경 고정, `investbrief-restart`/`investbrief-status` 별칭 제공.
2. KRX 수급 조회가 토큰 만료·일시 오류에 견디도록: **매 조회를 신선한 서브프로세스에서 실행**(조회 시마다 새 로그인) + 실패 시 1회 재시도.
3. 수급 3단 폴백: KRX → 네이버 금융 → 전일 캐시(기준일 표기) → 최후 "데이터 없음".
4. 수급 폴백 발동·전체 실패가 텔레그램으로 경보 (침묵 실패 제거).

### 비목표
- 서버(클라우드) 이전 — 현행 맥북 유지. StockAI와 같은 기계이므로 기계 수준 리스크는 공유하되, 이는 별도 논의.
- 프론트엔드 production 빌드 전환 — 권장 사항으로만 기록 (브리프 생성·발송은 백엔드 단독으로 완결되므로 P2).
- StockAI 쪽 수급(investor_flow 분리 브랜치) 처분 — 별도 트랙.
- 브리프 내용·프롬프트 변경 — 없음 (§7의 기준일 표기 1줄 제외).

---

## 5. 변경 사항 상세 — G-1: 런타임 정착

### 5.1 venv 고정

- `backend/venv` 생성(python3.11), `backend/requirements.txt` 현행화 — **pykrx 포함**(이번 사고의 직접 재발 방지), 버전 고정(`pykrx==현재 설치 버전`).
- 기동 명령을 venv 파이썬 절대경로로 통일: `backend/venv/bin/python -m uvicorn app.main:app --port 8001` (형태는 실제 엔트리포인트 확인 후 확정).

### 5.2 launchd 등록

- `scripts/launchd/com.investbrief.backend.plist`: KeepAlive, RunAtLoad, WorkingDirectory=backend, StandardOut/ErrorPath=`logs/backend.{out,err}.log` (프로젝트 내부 — /tmp 금지, StockAI 관행 동일).
- **환경변수 전달 확인이 핵심**: launchd 기동 프로세스는 셸 환경을 상속하지 않으므로, 앱이 시작 시 `backend/.env`를 load_dotenv로 **os.environ까지** 주입하는지 확인하고, 안 하면 추가한다 (pykrx는 os.environ의 KRX_ID/KRX_PW를 읽는다 — 이 연결이 끊기면 launchd 전환 순간 수급이 다시 죽는다). 시작 로그에 `KRX 자격증명: 설정됨/누락` 1줄 출력(값은 절대 출력 금지).
- `scripts/launchd/README.md`에 설치/재설치 절차 (StockAI와 동일 포맷).

### 5.3 운영 별칭 (`scripts/zshrc_snippet.sh`)

- `investbrief-restart`: `launchctl kickstart -k` 후 `:8001/health`(없으면 신설 — git 커밋 해시 포함, StockAI /health와 동일 사양) 폴링 → 커밋 해시 대조 → ✅/❌ 출력, 불일치·기동실패 시 텔레그램 (StockAI O-2 이식).
- `investbrief-status`: launchd 상태, PID, 실행 커밋, 마지막 브리프 발송 시각(로그 grep).
- 프론트: 별도 plist는 선택 항목으로 README에만 기록. 단 현행 `next dev` 상시 운영은 비권장임을 명시.

### 5.4 기존 수동 프로세스 정리

배포 시 PID 31108(및 프론트 dev) 종료 → launchd 기동으로 대체. 절차를 §11에 명시.

---

## 6. 변경 사항 상세 — G-2: KRX 조회 견고화

### 6.1 서브프로세스 격리 (권장안)

`investor_flow_collector`의 pykrx 호출을 **매 조회마다 단명 서브프로세스**로 실행:

```
asyncio.to_thread(내부 pykrx 호출)          [현행 — 프로세스 수명 = 백엔드 수명, 토큰 만료 노출]
→ asyncio.create_subprocess_exec(
    sys.executable, "-m", "app.collectors._krx_flow_worker", date_str)
  워커: 신선한 프로세스 → pykrx import 시 새 로그인 → 조회 → JSON을 stdout으로 → 종료
```

- 근거: 호출 빈도가 하루 1~2회(07:40 브리프, 테마 스캔 참조 시)라 서브프로세스 비용은 무의미한 반면, **토큰 만료·세션 오염·pykrx 내부 상태 문제가 원천 소멸**한다. 장기 프로세스 안에서 "만료 감지 후 재로그인"을 구현하는 것보다 단순하고 검증 가능.
- 워커 timeout 60초, 실패(비정상 종료·타임아웃·JSON 파싱 실패) 시 **1회 재시도** 후 폴백(§7)으로.
- KRX_ID/PW는 부모의 os.environ이 서브프로세스에 상속 — 별도 전달 코드 불필요(§5.2의 주입이 전제).

### 6.2 로그인 실패의 명시 구분

워커 stderr에 "KRX 로그인 실패"가 포함되면 일반 실패와 구분해 로그·경보에 `자격증명 문제 의심` 표기 — 비밀번호 변경·계정 잠금을 즉시 알 수 있게.

---

## 7. 변경 사항 상세 — G-3: 수급 3단 폴백 + 경보

### 7.1 폴백 체인 (`get_market_flow_resilient`)

```
1단 KRX(서브프로세스, §6) 성공 → 결과 반환 + 캐시 저장
2단 네이버 금융 시장별 투자자 매매동향 파싱 (외인/기관/개인 순매수, 억원)
     성공 → 반환(source="naver") + 캐시 저장
3단 전일 캐시 runtime/investor_flow_cache.json (1단 성공 시마다 갱신)
     존재+7일 이내 → 반환(source="cache", trade_date는 캐시의 것)
4단 전부 실패 → None (현행 "수급 데이터 없음" 경로 유지)
```

- 반환 dict에 `source`와 `trade_date` 필수 포함. 프롬프트 포맷터(`_format_flow_for_prompt`)가 source≠"krx"일 때 `※ {trade_date} 기준({출처})` 1줄을 덧붙여 브리프 AI가 기준일을 정확히 서술하게 함 — **낡은 데이터를 최신인 척 쓰는 것이 폴백의 최악 실패 모드이므로 표기는 생략 불가**.
- 네이버 파서는 구조 변경에 대비해 파싱 실패를 조용히 0으로 뭉개지 말고 예외로 승격(3단으로 넘어가게).

### 7.2 침묵 실패 제거

- 2단 이하로 내려간 날: 브리프 발송 직후 운영 텔레그램으로 1줄 경보 `⚠️ 수급 폴백 {단계/출처} — KRX 조회 실패 ({사유 요약})`.
- 4단(전부 실패): `🛑 수급 전 소스 실패 — 브리프는 수급 없이 발송됨`.
- 성공한 날은 침묵 (경보 채널 원칙 — StockAI와 동일).

---

## 8. DB 스키마 / 마이그레이션

없음. 캐시는 `runtime/investor_flow_cache.json` 파일 (원자적 tmp→rename 기록).

---

## 9. 텔레그램 / 웹 반영 체크

| 항목 | 텔레그램 | 웹 |
|---|---|---|
| 브리프 본문 | 폴백 시 기준일·출처 표기 (§7.1) | 브리프 뷰 동일 (같은 본문 소비 시 자동) |
| 폴백/전체실패 경보 | §7.2 신규 | — |
| restart/status | O-2식 ✅/❌ | — |

---

## 10. 테스트 계획

1. 워커 단위: 정상 조회 JSON 반환 / KRX_ID 제거 상태에서 "자격증명 문제 의심" 분기 / timeout 강제 → 1회 재시도 → 폴백 진입.
2. 폴백 체인: 1단 강제 실패 → 네이버 결과 + source="naver" + 경보 발송 / 1·2단 실패 → 캐시 반환 + 기준일 표기 / 캐시 8일 경과 → 4단 None.
3. 캐시: 1단 성공 시 갱신, 원자적 기록.
4. launchd: plist 로드 → 재부팅 시뮬(kickstart -k) → 자동 복구, .env의 KRX 자격증명이 launchd 기동 프로세스의 os.environ에 존재(시작 로그 "설정됨").
5. `investbrief-restart` 해시 ✅/❌ 양 분기.
6. 통합: 브리프 수동 트리거 1회 → 수급 수치 포함 발송 확인.

---

## 11. 배포 및 롤백

### 배포 절차 (순서 엄수)
1. venv 생성 + requirements 설치 → 워커 단독 테스트(§10-1) 통과 확인.
2. 기존 수동 백엔드(PID 확인 후 kill) 종료 → plist 로드 → `investbrief-status`로 기동·커밋 확인.
3. 브리프 수동 트리거 1회로 즉시 검증 (다음 영업일 아침까지 기다리지 말 것).
4. 프론트 dev 프로세스는 사용자 판단으로 정리 (README 권장사항 참조).

### 롤백
- launchd unload 후 기존 방식 수동 기동으로 즉시 복귀 가능. 폴백 체인은 `flow_fallback_enabled=false` config로 1단-only(현행 동작) 복귀.

---

## 12. 완료 기준 (Definition of Done)

- [ ] 백엔드가 launchd KeepAlive로 상주, 강제 kill 후 자동 복구 실증
- [ ] venv 고정 + requirements에 pykrx 버전 명시 (환경 재현 가능)
- [ ] launchd 기동 프로세스에서 KRX 자격증명 인식 (시작 로그 "설정됨", 값 미출력)
- [ ] 수급 조회가 서브프로세스 격리로 동작 — 백엔드 24시간 이상 가동 후 조회도 성공 (토큰 만료 면역 실증)
- [ ] 폴백 2·3단 강제 시나리오에서 기준일 표기 + 경보 수신
- [ ] `investbrief-restart` ✅/❌ 판정 동작
- [ ] 다음 영업일 07:40 브리프에 외인/기관 net flow 실수치 게재 — "미제공" 문구 소멸
- [ ] 그다음 영업일에도 재현 (연속 2일 = 토큰 만료 사이클 통과 증명)
