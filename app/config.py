
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
    # OAuth redirect: set in production (e.g. https://careflow-ypfn.onrender.com) so redirect_uri matches exactly what you registered in Google/GitHub/Yahoo consoles
    public_base_url: Optional[str] = None

    # Email (for verification): set in .env to send verification emails; if not set, verification link is logged only
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    email_from: Optional[str] = None  # e.g. "CareFlow <noreply@yourdomain.com>"

    # OAuth (optional; set in .env to enable each provider)
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    github_client_id: Optional[str] = None
    github_client_secret: Optional[str] = None
    yahoo_client_id: Optional[str] = None
    yahoo_client_secret: Optional[str] = None

    # OTC limits
    max_otc_attempts: int = 3

    # Medical pipeline: AWS Comprehend Medical (optional; pipeline works without it)
    aws_region: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    # PubMed E-utilities are free; optional key for higher rate limit
    pubmed_api_key: Optional[str] = None

    class Config:
        env_file = ".env"


settings = Settings()