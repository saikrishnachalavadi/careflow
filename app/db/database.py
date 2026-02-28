from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.db.models import Base

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create tables if they don't exist. Add auth columns if missing (SQLite and PostgreSQL)."""
    Base.metadata.create_all(bind=engine)
    is_sqlite = settings.database_url.strip().startswith("sqlite")
    with engine.connect() as conn:
        if is_sqlite:
            for stmt in [
                "ALTER TABLE users ADD COLUMN username VARCHAR",
                "ALTER TABLE users ADD COLUMN password_hash VARCHAR",
                "ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN verification_token VARCHAR",
                "ALTER TABLE users ADD COLUMN verification_token_expires DATETIME",
            ]:
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception:
                    conn.rollback()
        else:
            # PostgreSQL: ADD COLUMN IF NOT EXISTS (no-op if already present)
            for stmt in [
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR UNIQUE",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token VARCHAR",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token_expires TIMESTAMP",
            ]:
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception:
                    conn.rollback()
            for stmt in [
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users(username)",
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_verification_token ON users(verification_token)",
            ]:
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception:
                    conn.rollback()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
