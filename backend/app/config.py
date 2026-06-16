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


settings = Settings()
