from sqlalchemy import Column, String, Integer, DateTime, Enum
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    username = Column(String, unique=True, nullable=True, index=True)  # for sign-in; unique per user
    email = Column(String, unique=True, nullable=True, index=True)
    password_hash = Column(String, nullable=True)  # for username/password auth
    email_verified = Column(Integer, default=0)  # 0=False, 1=True
    verification_token = Column(String, nullable=True, index=True)
    verification_token_expires = Column(DateTime, nullable=True)
    phone = Column(String, unique=True, nullable=True)
    auth_provider = Column(String, nullable=True)  # google | yahoo | github | password
    created_at = Column(DateTime, default=datetime.utcnow)
    otc_attempts_used = Column(Integer, default=0)
    otc_privilege_status = Column(String, default="ACTIVE")  # ACTIVE | LOCKED
    abuse_strikes = Column(Integer, default=0)


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)
    message_count = Column(Integer, default=0)
    status = Column(String, default="ACTIVE")  # ACTIVE | CLOSED | TIMEOUT


class HealthEvent(Base):
    __tablename__ = "health_events"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    event_type = Column(String)  # SYMPTOM | OTC | DOCTOR_VISIT | LAB | EMERGENCY | MOOD
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)