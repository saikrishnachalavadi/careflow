"""
JWT and cookie helpers for CareFlow auth.
Cookie is httpOnly; frontend gets identity via GET /auth/me.
Supports both OAuth (email, provider) and username/password (email, provider="password").
"""
import logging
import time
import uuid
from typing import Optional, Tuple

import jwt
from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from passlib.context import CryptContext

from app.config import settings

logger = logging.getLogger(__name__)
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Anonymous id prefix so backend can tell anon from logged-in
ANON_PREFIX = "anon_"


def _tester_emails_set() -> set:
    return {e.strip().lower() for e in (settings.tester_emails or "").split(",") if e.strip()}


def is_tester_email(email: Optional[str]) -> bool:
    if not email:
        return False
    return email.strip().lower() in _tester_emails_set()


def create_jwt(user_id: str, email: str, provider: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "provider": provider,
        "exp": int(time.time()) + settings.auth_cookie_max_age_seconds,
        "iat": int(time.time()),
    }
    return jwt.encode(
        payload,
        settings.auth_secret_key,
        algorithm="HS256",
    )


def decode_jwt(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.auth_secret_key, algorithms=["HS256"])
        return payload
    except Exception as e:
        logger.debug("JWT decode failed: %s", e)
        return None


def get_token_from_cookie(request: Request) -> Optional[str]:
    return request.cookies.get(settings.auth_cookie_name)


def _is_secure_deployment() -> bool:
    """True when deployed over HTTPS (e.g. Render). Cookie secure flag must match so set/clear work."""
    return not (settings.database_url or "").strip().startswith("sqlite")


def set_auth_cookie(response: Response, user_id: str, email: str, provider: str) -> None:
    """Set auth cookie as session-only (no max_age) so user must sign in again when they return."""
    token = create_jwt(user_id, email, provider)
    secure = _is_secure_deployment()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Clear auth cookie using same path/httponly/samesite/secure as set_cookie so browsers actually remove it."""
    secure = _is_secure_deployment()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value="",
        max_age=0,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def get_current_user_from_request(request: Request) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Returns (user_id, email, provider) from auth cookie, or (None, None, None).
    Does not validate that user exists in DB.
    """
    token = get_token_from_cookie(request)
    if not token:
        return (None, None, None)
    payload = decode_jwt(token)
    if not payload:
        return (None, None, None)
    return (
        payload.get("sub"),
        payload.get("email"),
        payload.get("provider"),
    )


def generate_anonymous_id() -> str:
    return ANON_PREFIX + str(uuid.uuid4()).replace("-", "")[:24]


def hash_password(password: str) -> str:
    return pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return pwd_ctx.verify(plain, hashed)
    except Exception:
        return False


def get_message_limit_for_user(user_id: Optional[str], user_obj: Optional[object]) -> int:
    """
    Return max messages allowed for this user.
    user_obj: SQLAlchemy User or None. If None, treat as anonymous (user_id may be anon_xxx).
    """
    from app.config import settings
    if not user_id:
        return settings.max_messages_anonymous
    if user_id.startswith(ANON_PREFIX):
        return settings.max_messages_anonymous
    if user_obj and getattr(user_obj, "email", None):
        if is_tester_email(user_obj.email):
            return 9999
        return settings.max_messages_logged_in
    return settings.max_messages_anonymous
