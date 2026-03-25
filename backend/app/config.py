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

    # Database
    database_url: str = "sqlite+aiosqlite:///./investbrief.db"

    # Server
    backend_port: int = 8001
    frontend_port: int = 3001

    # Brief
    brief_send_hour: int = 7
    ai_model: str = "claude-sonnet-4-20250514"
    ai_max_tokens: int = 1000


settings = Settings()
