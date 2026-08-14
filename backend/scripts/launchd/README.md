# InvestBrief launchd 설치 (지시서 G-1)

백엔드를 launchd KeepAlive 상주 서비스로 전환한다. 크래시·재부팅 시 자동 복구되고,
`investbrief-restart`/`investbrief-status` 별칭으로 운영한다.

> ⚠️ **이 절차는 실행 중인 라이브 백엔드를 교체한다.** 아침 브리프 발송 시각(07:30)을
> 피해 실행할 것. `.env`의 `KRX_ID`/`KRX_PW`가 채워져 있어야 수급이 정상 동작한다.

## 0. 선행 조건

- `backend/.venv` 존재 + `requirements.txt` 설치 (pykrx 포함):
  ```
  cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
  ```
- `backend/.env`에 KRX 자격증명 추가:
  ```
  KRX_ID=<KRX 정보데이터시스템 ID>
  KRX_PW=<비밀번호>
  ```
- 워커 단독 검증 (자격증명 정상이면 JSON 출력, 없으면 exit 3):
  ```
  cd backend && .venv/bin/python -m app.collectors._krx_flow_worker $(date +%Y%m%d)
  ```

## 1. 로그 디렉토리

```
mkdir -p ~/dev/investbrief/backend/logs
```

## 2. plist 설치 (심볼릭 링크)

```
ln -sf ~/dev/investbrief/backend/scripts/launchd/com.investbrief.backend.plist \
       ~/Library/LaunchAgents/com.investbrief.backend.plist
```

## 3. 기존 수동 프로세스 종료

```
# 현재 :8001 점유 프로세스 확인 후 종료
lsof -ti :8001 | xargs kill
```

## 4. 서비스 로드

```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.investbrief.backend.plist
# (재로드 시) launchctl bootout gui/$(id -u)/com.investbrief.backend 후 다시 bootstrap
```

## 5. 별칭 등록

`~/.zshrc`에 추가 후 `source ~/.zshrc`:
```
source ~/dev/investbrief/backend/scripts/zshrc_snippet.sh
```

## 6. 검증

```
investbrief-status                       # state=running, PID, 실행 커밋
curl -s localhost:8001/api/health        # {"status":"ok","commit":"..."}
# 시작 로그에서 자격증명 인식 확인 (값은 출력되지 않음)
grep "KRX 자격증명" ~/dev/investbrief/backend/logs/backend.err.log   # → "설정됨"
```

## 7. 재부팅/크래시 복구 실증

```
kill $(lsof -ti :8001)     # 강제 종료 → KeepAlive가 수초 내 자동 재기동
investbrief-status         # 다시 running 확인
```

## 롤백

```
launchctl bootout gui/$(id -u)/com.investbrief.backend
rm ~/Library/LaunchAgents/com.investbrief.backend.plist
# 기존 수동 기동으로 복귀
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8001
```

폴백 체인만 끄려면(1단 KRX-only 복귀) — 코드 레벨 config가 아니라, `.env`에서
`KRX_ID/PW`를 채우면 1단이 정상 성공해 폴백은 자연히 발동하지 않는다.

## 프론트엔드 (선택 — P2)

현행 `next dev` 상시 운영은 **비권장**(개발 모드). production 전환 권장:
```
cd frontend && npm run build && npm run start   # 또는 별도 plist 작성
```
브리프 생성·발송은 백엔드 단독으로 완결되므로 프론트 상주화는 필수가 아니다.
