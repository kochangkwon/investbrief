# ─────────────────────────────────────────────────────────────
# InvestBrief Backend — Koyeb 무료 티어 (512MB RAM) 최적화
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

# 시스템 패키지 (yfinance가 lxml 요구할 수 있음 + healthcheck용 curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 복사 → 레이어 캐싱 극대화
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 앱 코드 복사
COPY app/ ./app/
COPY scripts/ ./scripts/

# 비루트 사용자 (보안)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Koyeb는 PORT 환경변수를 주입함
ENV PORT=8000
EXPOSE 8000

# 헬스체크 (Koyeb가 이 경로 호출)
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health || exit 1

# uvicorn 단일 워커 (512MB RAM 절약)
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1