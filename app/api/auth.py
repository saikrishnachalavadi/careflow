"""
Auth API: Sign up (email verification), Sign in (username/password), OAuth, logout, /auth/me.
Uses JWT in httpOnly cookie.
"""
import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth_utils import (
    clear_auth_cookie,
    get_current_user_from_request,
    hash_password,
    set_auth_cookie,
    verify_password,
)
from app.core.email_sender import send_verification_email
from app.db.database import get_db
from app.db.models import User

router = APIRouter()
logger = logging.getLogger(__name__)


class SignupRequest(BaseModel):
    username: str
    password: str
    email: str


class LoginRequest(BaseModel):
    username: str
    password: str


def _verification_base_url() -> str:
    base = (settings.public_base_url or "").strip().rstrip("/")
    if base:
        return base
    return "https://careflow-ypfn.onrender.com"


# ----- Sign up (email verification) and Sign in (username/password) -----


@router.post("/signup")
async def signup(body: SignupRequest, db: Session = Depends(get_db)):
    """Create user with email unverified; send verification email."""
    username = (body.username or "").strip()
    email = (body.email or "").strip().lower()
    password = body.password or ""
    if not username or len(username) < 2:
        raise HTTPException(status_code=400, detail="Username must be at least 2 characters")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        email=email,
        password_hash=hash_password(password),
        email_verified=0,
        verification_token=token,
        verification_token_expires=expires,
        auth_provider="password",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    verification_url = f"{_verification_base_url()}/auth/verify?token={token}"
    send_verification_email(email, username, verification_url)
    return {"message": "Verification email sent. Check your inbox to activate your account."}


@router.get("/verify")
async def verify(token: Optional[str] = None, db: Session = Depends(get_db)):
    """Verify email via link; redirect to /ui."""
    if not token:
        return RedirectResponse(url="/ui?auth_error=no_token", status_code=302)
    user = db.query(User).filter(
        User.verification_token == token,
        User.verification_token_expires > datetime.now(timezone.utc),
    ).first()
    if not user:
        return RedirectResponse(url="/ui?auth_error=invalid_or_expired", status_code=302)
    user.email_verified = 1
    user.verification_token = None
    user.verification_token_expires = None
    db.commit()
    return RedirectResponse(url="/ui?verified=1", status_code=302)


@router.post("/login")
async def login_post(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Sign in with username and password."""
    username = (body.username or "").strip()
    password = body.password or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not getattr(user, "email_verified", 1):
        raise HTTPException(status_code=403, detail="Please verify your email first. Check your inbox for the verification link.")
    if not getattr(user, "password_hash", None):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    set_auth_cookie(response, user.id, user.email or "", "password")
    return {"user_id": user.id, "username": user.username}


# OAuth provider configs: auth_url, token_url, userinfo (or way to get email), scope
OAUTH_CONFIG = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "scope": "openid email profile",
    },
    "github": {
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "emails_url": "https://api.github.com/user/emails",
        "scope": "user:email read:user",
    },
    "yahoo": {
        "auth_url": "https://api.login.yahoo.com/oauth2/request_auth",
        "token_url": "https://api.login.yahoo.com/oauth2/get_token",
        "userinfo_url": "https://api.login.yahoo.com/openid/v1/userinfo",
        # Only "openid" is required; "email"/"profile" can cause invalid_scope unless enabled in Yahoo app API Permissions
        "scope": "openid",
    },
}


def _get_redirect_uri(request: Request, provider: str) -> str:
    # Prefer explicit base URL (set PUBLIC_BASE_URL in production so it matches OAuth app config exactly)
    base = (settings.public_base_url or "").strip().rstrip("/")
    if base:
        out = f"{base}/auth/callback/{provider}"
        logger.info("OAuth redirect_uri (from PUBLIC_BASE_URL): %s", out)
        return out
    # Else build from request; behind Render/proxy use forwarded headers
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").strip().lower()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").strip()
    if host and forwarded_proto:
        base = f"{forwarded_proto}://{host}".rstrip("/")
    elif host and ("onrender.com" in host or "ngrok" in host):
        base = f"https://{host}".rstrip("/")
    else:
        base = str(request.base_url).rstrip("/")
    out = f"{base}/auth/callback/{provider}"
    logger.info("OAuth redirect_uri (from request): %s", out)
    return out


def _get_oauth_client(provider: str) -> tuple:
    if provider == "google":
        return (settings.google_client_id, settings.google_client_secret)
    if provider == "github":
        return (settings.github_client_id, settings.github_client_secret)
    if provider == "yahoo":
        return (settings.yahoo_client_id, settings.yahoo_client_secret)
    return (None, None)


@router.get("/login/{provider}")
async def login(request: Request, provider: str):
    """Redirect user to OAuth provider. Supported: google, github, yahoo."""
    provider = provider.lower()
    if provider not in OAUTH_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    client_id, client_secret = _get_oauth_client(provider)
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail=f"OAuth for {provider} is not configured. Set {provider.upper()}_CLIENT_ID and _SECRET in .env",
        )
    cfg = OAUTH_CONFIG[provider]
    redirect_uri = _get_redirect_uri(request, provider)
    state = secrets.token_urlsafe(32)
    # Store state in cookie so we can verify on callback (optional; we'll keep it in redirect for simplicity)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": cfg["scope"],
        "state": state,
    }
    auth_url = cfg["auth_url"] + "?" + urlencode(params)
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/callback/{provider}")
async def callback(
    request: Request,
    provider: str,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Handle OAuth callback: exchange code for token, get email, find/create user, set cookie, redirect to /ui."""
    if error:
        logger.warning("OAuth error from %s: %s", provider, error)
        return RedirectResponse(url="/ui?auth_error=1", status_code=302)
    if not code:
        return RedirectResponse(url="/ui?auth_error=no_code", status_code=302)

    provider = provider.lower()
    if provider not in OAUTH_CONFIG:
        return RedirectResponse(url="/ui?auth_error=unknown_provider", status_code=302)
    client_id, client_secret = _get_oauth_client(provider)
    if not client_id or not client_secret:
        return RedirectResponse(url="/ui?auth_error=config", status_code=302)

    cfg = OAUTH_CONFIG[provider]
    redirect_uri = _get_redirect_uri(request, provider)

    # Exchange code for access_token (redirect_uri must match exactly what was sent to the provider)
    token_payload = {
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    token_headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient() as client:
        if provider == "yahoo":
            token_resp = await client.post(
                cfg["token_url"],
                data=token_payload,
                headers=token_headers,
                auth=(client_id, client_secret),
            )
        else:
            token_payload["client_id"] = client_id
            token_payload["client_secret"] = client_secret
            token_resp = await client.post(
                cfg["token_url"],
                data=token_payload,
                headers=token_headers,
            )
    if token_resp.status_code != 200:
        logger.warning(
            "Token exchange failed provider=%s status=%s body=%s redirect_uri=%s",
            provider, token_resp.status_code, token_resp.text[:200], redirect_uri,
        )
        return RedirectResponse(url="/ui?auth_error=token", status_code=302)

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return RedirectResponse(url="/ui?auth_error=token", status_code=302)

    # Get user info (email)
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {access_token}"}
        if provider == "github":
            headers["Accept"] = "application/vnd.github.v3+json"
        user_resp = await client.get(cfg["userinfo_url"], headers=headers)
    if user_resp.status_code != 200:
        logger.warning("Userinfo failed %s: %s", user_resp.status_code, user_resp.text)
        return RedirectResponse(url="/ui?auth_error=userinfo", status_code=302)

    user_data = user_resp.json()

    if provider == "google":
        email = (user_data.get("email") or "").strip()
    elif provider == "github":
        email = (user_data.get("email") or "").strip()
        if not email and cfg.get("emails_url"):
            async with httpx.AsyncClient() as em_client:
                em_resp = await em_client.get(
                    cfg["emails_url"],
                    headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github.v3+json"},
                )
            if em_resp.status_code == 200:
                emails = em_resp.json()
                for e in emails or []:
                    if e.get("primary") or (emails and not email):
                        email = (e.get("email") or "").strip()
                        if email:
                            break
    elif provider == "yahoo":
        email = (user_data.get("email") or user_data.get("sub") or "").strip()
        if not email and token_data.get("id_token"):
            try:
                # With scope=openid only, userinfo may not include email; id_token sometimes does
                id_payload = jwt.decode(
                    token_data["id_token"],
                    options={"verify_signature": False},
                    algorithms=["RS256", "ES256"],
                )
                email = (id_payload.get("email") or id_payload.get("sub") or "").strip()
            except Exception:
                pass
        if not email:
            email = (user_data.get("sub") or "").strip()
    else:
        email = (user_data.get("email") or user_data.get("mail") or "").strip()

    if not email:
        logger.warning("No email from %s userinfo: %s", provider, user_data)
        return RedirectResponse(url="/ui?auth_error=no_email", status_code=302)

    email = email.lower()
    # Persist subscriber in database (PostgreSQL on Render when DATABASE_URL is set)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            phone=f"oauth_{provider}_{email}",
            auth_provider=provider,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # Same person signing in with a different provider: update email and provider so display matches current login
        user.email = email
        user.auth_provider = provider
        db.commit()
        db.refresh(user)

    redir = RedirectResponse(url="/ui", status_code=302)
    set_auth_cookie(redir, user.id, user.email, user.auth_provider or provider)
    return redir


@router.get("/logout")
async def logout():
    """Clear auth cookie and redirect to /ui. Cache-busting query so browser loads fresh page and /auth/me runs without stale cookie."""
    redir = RedirectResponse(url=f"/ui?logged_out={int(time.time())}", status_code=302)
    clear_auth_cookie(redir)
    redir.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    redir.headers["Pragma"] = "no-cache"
    return redir


@router.get("/me")
async def me(request: Request, response: Response, db: Session = Depends(get_db)):
    """Return current user from cookie (DB is single source of truth) or 401."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    user_id, _, _ = get_current_user_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        clear_auth_cookie(response)
        raise HTTPException(status_code=401, detail="User not found")

    from app.core.auth_utils import is_tester_email
    tester = is_tester_email(user.email) if user.email else False
    return {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "provider": user.auth_provider or "",
        "is_tester": tester,
    }
