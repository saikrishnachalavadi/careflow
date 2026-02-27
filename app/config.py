
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    app_name: str = "CareFlow"
    debug: bool = False

    # Database (SQLite by default; set DATABASE_URL for PostgreSQL later)
    database_url: str = "sqlite:///./careflow.db"

    # AI - Gemini
    google_api_key: Optional[str] = None  # For Gemini

    # Google Maps
    google_maps_api_key: Optional[str] = None

    # LangSmith Monitoring
    langchain_tracing_v2: bool = True
    langchain_api_key: Optional[str] = None
    langchain_project: str = "careflow"

    # Session limits (high defaults for testing; set in .env for production: e.g. 10 and 8)
    max_sessions_per_day: int = 9999
    max_messages_per_session: int = 9999
    session_timeout_minutes: int = 10

    # OTC limits
    max_otc_attempts: int = 3

    class Config:
        env_file = ".env"


settings = Settings()