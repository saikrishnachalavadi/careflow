from typing import Optional, Tuple
import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User, Session as SessionModel
from app.schemas.triage import TriageRequest, TriageResponse
from app.core.router import route_input
from app.core.severity import calculate_severity
from app.core.auth_utils import get_current_user_from_request, get_message_limit_for_user
from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_or_create_session(db: Session, user_id: str) -> Tuple[Optional[SessionModel], Optional[str]]:
    """
    Get active session for user or create one. Enforces max_sessions_per_day and timeout.
    Returns (session, error_message). error_message set if over session limit.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(days=1)
    same_day = db.query(SessionModel).filter(
        SessionModel.user_id == user_id,
        SessionModel.created_at >= cutoff,
    ).count()
    if same_day >= settings.max_sessions_per_day:
        last = db.query(SessionModel).filter(SessionModel.user_id == user_id).order_by(SessionModel.created_at.desc()).first()
        return (last, "Maximum sessions per day reached. Please try again tomorrow.")

    active = (
        db.query(SessionModel)
        .filter(
            SessionModel.user_id == user_id,
            SessionModel.status == "ACTIVE",
        )
        .first()
    )
    if active:
        timeout = now - timedelta(minutes=settings.session_timeout_minutes)
        if active.last_activity < timeout:
            active.status = "TIMEOUT"
            db.commit()
            active = None
    if not active:
        active = SessionModel(
            id=str(uuid.uuid4()),
            user_id=user_id,
            status="ACTIVE",
            message_count=0,
        )
        db.add(active)
        db.commit()
        db.refresh(active)
    return (active, None)


def _route_to_action(route: str) -> str:
    """Map router route to recommended_action for response."""
    if route == "emergency":
        return "emergency"
    if route == "doctor_handoff":
        return "doctor_handoff"
    if route == "pharmacy_handoff":
        return "pharmacy_handoff"
    if route == "lab_handoff":
        return "lab_handoff"
    if route == "blocked":
        return "blocked"
    if route == "unclear":
        return "unclear"
    return "medical"  # medical flow → severity decides doctor vs OTC later


@router.post("/", response_model=TriageResponse)
async def create_triage(http_request: Request, request: TriageRequest, db: Session = Depends(get_db)):
    """Main triage: LangGraph routing, session limits, severity scoring, recommended action."""
    cookie_user_id, _, _ = get_current_user_from_request(http_request)
    effective_user_id = cookie_user_id if cookie_user_id else request.user_id

    try:
        user = db.query(User).filter(User.id == effective_user_id).first()
        abuse_strikes = user.abuse_strikes if user else 0
    except Exception as e:
        logger.exception("Database error loading user")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "service_unavailable",
                "message": "Database is not available. Ensure PostgreSQL is running and tables exist.",
                "hint": str(e),
            },
        )

    limit = get_message_limit_for_user(effective_user_id, user)
    session, session_error = _get_or_create_session(db, effective_user_id)
    if session_error:
        return TriageResponse(
            session_id=session.id if session else "none",
            severity_medical="M0",
            severity_psychological="P0",
            recommended_action="blocked",
            message=session_error,
        )

    if session.message_count >= limit:
        msg = "You've used your 6 free messages. Sign in to get 20 messages." if limit <= 6 else "You've reached the message limit. Sign in for more messages."
        return TriageResponse(
            session_id=session.id,
            severity_medical="M0",
            severity_psychological="P0",
            recommended_action="blocked",
            message=msg,
        )

    try:
        result = await route_input(
            user_id=effective_user_id,
            message=request.message,
            session_id=request.session_id or session.id,
            abuse_strikes=abuse_strikes,
        )
    except Exception as e:
        logger.exception("Router/AI error")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "routing_failed",
                "message": "Triage routing failed. Check GOOGLE_API_KEY in .env if AI classification is used.",
                "hint": str(e),
            },
        )

    route = result.get("route") or "medical"
    block_reason = result.get("block_reason")

    if route == "blocked":
        if user and result.get("abuse_strikes") is not None:
            user.abuse_strikes = result["abuse_strikes"]
            db.commit()
        return TriageResponse(
            session_id=session.id,
            severity_medical="M0",
            severity_psychological="P0",
            recommended_action="blocked",
            message=block_reason or result.get("response_message", "Request blocked."),
        )

    if route == "unclear":
        session.last_activity = datetime.utcnow()
        session.message_count = (session.message_count or 0) + 1
        db.commit()
        return TriageResponse(
            session_id=session.id,
            severity_medical="M0",
            severity_psychological="P0",
            recommended_action="unclear",
            message="I can only help with health-related questions. Tell me about a symptom or what you need (e.g. doctor, pharmacy, lab).",
        )

    # Update session activity
    session.last_activity = datetime.utcnow()
    session.message_count = (session.message_count or 0) + 1
    db.commit()

    recommended_action = _route_to_action(route)
    severity_medical = "M1"
    severity_psychological = "P0"

    if route == "medical":
        severity_medical, severity_psychological = calculate_severity([request.message])
        if severity_medical == "M3":
            recommended_action = "emergency"
        elif severity_medical in ("M1", "M2"):
            recommended_action = "doctor_handoff"
        else:
            recommended_action = "doctor_handoff"

    message = result.get("response_message") or f"Routed to {recommended_action}."

    return TriageResponse(
        session_id=session.id,
        severity_medical=severity_medical,
        severity_psychological=severity_psychological,
        recommended_action=recommended_action,
        message=message,
    )
