from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # API Keys
    dart_api_key: str = ""
    naver_client_id: str = ""
    naver_client_secret: str = ""
    anthropic_api_key: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Internal API (StockAI ↔ InvestBrief)
    stockai_internal_api_key: str = ""

    # 공개 API 보호용 (프론트엔드 프록시 ↔ 백엔드)
    admin_api_key: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./investbrief.db"

    # Server
    backend_port: int = 8001
    frontend_port: int = 3001

    # Brief
    brief_send_hour: int = 7
    brief_send_minute: int = 30
    ai_model: str = "claude-opus-4-8"
    ai_max_tokens: int = 1000

    # US Market (모닝브리프와 분리 발송)
    us_market_send_hour: int = 7
    us_market_send_minute: int = 40

    # Finnhub fallback (yfinance rate limit 시 자동 전환)
    finnhub_api_key: str = ""

    # 테마 신호 품질 (지시서 F) — 롤백용 플래그
    theme_verify_strict: bool = True       # false면 MATERIALITY LOW도 통과(검증 완화)
    theme_news_freshness_hours: int = 24   # 0이면 신선도 필터 무효

    # 키움 REST API (테마 선정 수급 필터 — 공매도/대차/기관·외국인)
    kiwoom_app_key: str = ""
    kiwoom_app_secret: str = ""
    kiwoom_account_no: str = ""
    kiwoom_is_mock: bool = False


settings = Settings()
