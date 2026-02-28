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
    """Create tables if they don't exist. Call on startup."""
    Base.metadata.create_all(bind=engine)
    # SQLite: add new auth columns if they don't exist (no-op if already present)
    if settings.database_url.startswith("sqlite"):
        with engine.connect() as conn:
            for stmt in [
                "ALTER TABLE users ADD COLUMN email VARCHAR",
                "ALTER TABLE users ADD COLUMN auth_provider VARCHAR",
            ]:
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception:
                    conn.rollback()
                    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
