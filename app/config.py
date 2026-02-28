
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

    # Prompt limits: anonymous vs logged-in vs tester
    max_messages_anonymous: int = 6
    max_messages_logged_in: int = 20
    tester_emails: str = "saikrishnachalavadi@yahoo.com"  # comma-separated

    # Auth: JWT secret (set in .env in production)
    auth_secret_key: str = "careflow-dev-secret-change-in-production"
    auth_cookie_name: str = "careflow_session"
    auth_cookie_max_age_seconds: int = 86400 * 7  # used only for JWT exp claim; cookie is session-only (no max_age)

    # OAuth (optional; set in .env to enable each provider)
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    github_client_id: Optional[str] = None
    github_client_secret: Optional[str] = None
    yahoo_client_id: Optional[str] = None
    yahoo_client_secret: Optional[str] = None

    # OTC limits
    max_otc_attempts: int = 3

    class Config:
        env_file = ".env"


settings = Settings()