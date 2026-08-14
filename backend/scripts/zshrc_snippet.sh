# ──────────────────────────────────────────────────────────────
# InvestBrief 운영 별칭 (지시서 G-1 §5.3) — StockAI O-2 이식
# ~/.zshrc 에 `source ~/dev/investbrief/backend/scripts/zshrc_snippet.sh` 추가
# ──────────────────────────────────────────────────────────────

export INVESTBRIEF_ROOT="/Users/changkwonko/dev/investbrief"
export INVESTBRIEF_LABEL="com.investbrief.backend"
export INVESTBRIEF_HEALTH="http://localhost:8001/api/health"

# .env에서 텔레그램 자격증명만 읽어 경보에 사용 (값 노출 없음)
_investbrief_telegram() {
    local msg="$1"
    local env_file="$INVESTBRIEF_ROOT/backend/.env"
    [ -f "$env_file" ] || return 0
    local token chat
    token=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$env_file" | head -1 | cut -d= -f2-)
    chat=$(grep -E '^TELEGRAM_CHAT_ID=' "$env_file" | head -1 | cut -d= -f2-)
    [ -n "$token" ] && [ -n "$chat" ] || return 0
    curl -s -o /dev/null "https://api.telegram.org/bot${token}/sendMessage" \
        --data-urlencode "chat_id=${chat}" \
        --data-urlencode "text=${msg}" >/dev/null 2>&1
}

# 재시작 + 배포 커밋 대조 (✅/❌). 불일치·기동실패 시 텔레그램 경보.
investbrief-restart() {
    local expected
    expected=$(git -C "$INVESTBRIEF_ROOT" rev-parse HEAD)
    echo "↻ 재시작 (기대 커밋 ${expected:0:8})..."
    launchctl kickstart -k "gui/$(id -u)/${INVESTBRIEF_LABEL}" 2>/dev/null

    local running=""
    for i in $(seq 1 20); do
        running=$(curl -s "$INVESTBRIEF_HEALTH" 2>/dev/null | \
            python3 -c "import sys,json; print(json.load(sys.stdin).get('commit',''))" 2>/dev/null)
        [ -n "$running" ] && break
        sleep 1
    done

    if [ -z "$running" ]; then
        echo "❌ 기동 실패 — /api/health 무응답"
        _investbrief_telegram "❌ InvestBrief 재시작 실패 — health 무응답 (기대 ${expected:0:8})"
        return 1
    fi
    if [ "$running" = "$expected" ]; then
        echo "✅ 재시작 완료 — 커밋 ${running:0:8} 일치"
    else
        echo "❌ 커밋 불일치 — 실행 ${running:0:8} vs 기대 ${expected:0:8}"
        _investbrief_telegram "❌ InvestBrief 커밋 불일치 — 실행 ${running:0:8} / 기대 ${expected:0:8}"
        return 1
    fi
}

# 상태: launchd 등록·PID·실행 커밋·마지막 브리프 발송
investbrief-status() {
    echo "── launchd ──"
    launchctl print "gui/$(id -u)/${INVESTBRIEF_LABEL}" 2>/dev/null | \
        grep -E "state =|pid =" || echo "  (미등록)"
    echo "── health ──"
    curl -s "$INVESTBRIEF_HEALTH" 2>/dev/null || echo "  (무응답)"
    echo ""
    echo "── 마지막 모닝브리프 발송 ──"
    grep "모닝브리프 완료" "$INVESTBRIEF_ROOT/backend/logs/backend.err.log" 2>/dev/null | \
        tail -1 || echo "  (로그 없음)"
}
