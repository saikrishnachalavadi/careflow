"""
Chat API: route input (NLP) → medical route runs Dr.GPT pipeline (PubMed RAG + Gemini).
Returns user message + action (doctors/pharmacy/emergency/etc). Used by web UI.
"""
import logging
from datetime import datetime
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User, Session as SessionModel
from app.schemas.chat import ChatRequest, ChatResponse
from app.core.router import route_input
from app.core.severity import calculate_severity
from app.core.auth_utils import get_current_user_from_request, get_message_limit_for_user
from app.config import settings
from app.api.triage import _get_or_create_session
from app.services.medical_pipeline import run_medical_pipeline

router = APIRouter()
logger = logging.getLogger(__name__)

# Fixed fallback when LLM is unavailable for unclear messages
_UNCLEAR_FALLBACK = "I can only help with health-related questions—symptoms, finding a doctor, pharmacy, lab, or emergencies. What do you need?"


def _otc_suggestion_for_message(message: str) -> Optional[str]:
    """
    Lightweight OTC suggestions for common mild symptoms.
    Keep this conservative: generic options + label-following, no dosing.
    """
    msg = (message or "").lower()

    # Common cold / URTI
    if any(k in msg for k in ("cold", "common cold", "runny nose", "stuffy nose", "congestion", "sore throat")):
        return (
            "For a typical cold, OTC options include acetaminophen/paracetamol for fever or aches, "
            "saline nasal spray, and throat lozenges—follow the label and seek care if symptoms are severe or persist"
        )

    # Headache / mild pain
    if "headache" in msg or "head ache" in msg:
        return "For a mild headache, OTC options include acetaminophen/paracetamol—follow the label and seek care if severe or persistent"

    return None


async def _generate_unclear_reply(user_message: str) -> str:
    """Use Gemini (free tier) to generate a short, polite redirect for off-topic or unclear input."""
    if not settings.google_api_key:
        return _UNCLEAR_FALLBACK
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=settings.google_api_key,
        )
        prompt = SystemMessage(content="""You are CareFlow, a healthcare-only assistant. The user said something that is not clearly about health.
Reply in ONE short sentence (max 15 words). Politely say you only help with health topics and ask them to share a symptom or what they need (e.g. doctor, pharmacy, lab). Do NOT recommend a doctor. Be friendly and brief.""")
        resp = llm.invoke([prompt, HumanMessage(content=user_message)])
        text = (resp.content or "").strip()
        if text and len(text) < 200:
            return text
    except Exception as e:
        logger.debug("Unclear-reply LLM failed: %s", e)
    return _UNCLEAR_FALLBACK


def _route_to_action(route: str) -> Optional[str]:
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
        return None
    return "medical"


# Short list for template messages; LLM can suggest others
_SPECIALTY_LABELS = {
    "general_physician": "a general physician",
    "pediatrician": "a pediatrician",
    "dermatologist": "a dermatologist",
    "cardiologist": "a cardiologist",
    "psychiatrist": "a psychiatrist",
    "orthopedic": "an orthopedic specialist",
    "dentist": "a dentist",
    "gynecologist": "a gynecologist",
}


def _doctor_label(specialty: Optional[str]) -> str:
    if not specialty:
        return "a doctor"
    if specialty in _SPECIALTY_LABELS:
        return _SPECIALTY_LABELS[specialty]
    p = specialty.replace("_", " ").strip()
    return f"{'an' if p and p[0] in 'aeiou' else 'a'} {p}" if p else "a doctor"


def _user_message(
    user_message: str,
    route: str,
    severity_medical: str,
    severity_psychological: str,
    block_reason: Optional[str],
    doctor_specialty: Optional[str] = None,
    doctor_suggestion_text: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Return (message_for_user, action). No severity or internal labels."""
    if route == "greeting":
        return ("Hi! How can I help you today?", None)
    if route == "blocked":
        return (block_reason or "I can only help with health-related questions. Please ask about doctors, pharmacy, labs, or emergencies.", None)
    if route == "emergency":
        return ("Opening nearby emergency services.", "emergency_services")
    if route == "doctor_handoff":
        return (f"I can help you find {_doctor_label(doctor_specialty)}. Share your location to see nearby options.", "doctors")
    if route == "pharmacy_handoff":
        otc = _otc_suggestion_for_message(user_message)
        if otc:
            return (f"{otc}. If you'd like, I can help you find a pharmacy nearby—share your location.", "pharmacy")
        return ("I can help you find a pharmacy. Share your location for nearby pharmacies.", "pharmacy")
    if route == "lab_handoff":
        return ("I can help you with lab tests. Share your location to find nearby labs.", "labs")
    if route == "unclear":
        # Message is set by caller using _generate_unclear_reply()
        return (_UNCLEAR_FALLBACK, None)
    if route == "medical":
        if severity_medical == "M3":
            return ("Opening nearby emergency services.", "emergency_services")
        if severity_medical == "M1":
            otc = _otc_suggestion_for_message(user_message)
            if otc:
                return (f"{otc}. If you'd like, I can help you find a pharmacy nearby—share your location.", "pharmacy")
        if severity_psychological == "P3":
            return (
                "If you're in crisis, please reach out to a helpline. Open the link below to see numbers and find mental health support.",
                "psychological",
            )
        if severity_psychological in ("P1", "P2"):
            return (
                "Based on what you've shared, I recommend speaking with a mental health professional. I can help you find a psychologist, psychiatrist, or counselor nearby, or show you crisis helpline numbers.",
                "psychological",
            )
        if doctor_suggestion_text:
            return (f"{doctor_suggestion_text} I can help you find one nearby if you share your location.", "doctors")
        return (f"Based on what you've described, I recommend speaking with {_doctor_label(doctor_specialty)}. I can help you find one nearby if you share your location.", "doctors")
    return ("How can I help you today?", None)


def _limit_reached_message(limit: int) -> str:
    if limit <= 6:
        return "You've used your 6 free messages. Sign in to get 20 messages."
    return "You've reached the message limit for this session. Sign in for more messages."


@router.post("/", response_model=ChatResponse)
async def chat(http_request: Request, request: ChatRequest, db: Session = Depends(get_db)):
    """Chat endpoint: returns only a user-facing message and optional action. No severity/route exposed."""
    # Resolve effective user: from auth cookie if logged in, else body user_id (anonymous)
    cookie_user_id, _, _ = get_current_user_from_request(http_request)
    effective_user_id = cookie_user_id if cookie_user_id else request.user_id

    try:
        user = db.query(User).filter(User.id == effective_user_id).first()
        abuse_strikes = user.abuse_strikes if user else 0
    except Exception as e:
        logger.exception("Database error loading user")
        raise HTTPException(status_code=503, detail={"message": "Service temporarily unavailable.", "hint": str(e)})

    limit = get_message_limit_for_user(effective_user_id, user)
    session, session_error = _get_or_create_session(db, effective_user_id)
    if session_error:
        return ChatResponse(message=session_error, action=None, session_id=session.id if session else "none", remaining_prompts=None)
    if session.message_count >= limit:
        return ChatResponse(
            message=_limit_reached_message(limit),
            action=None,
            session_id=session.id,
            remaining_prompts=0,
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
        raise HTTPException(status_code=503, detail={"message": "Something went wrong. Please try again.", "hint": str(e)})

    route = result.get("route") or "medical"
    block_reason = result.get("block_reason")

    if route == "blocked":
        if user and result.get("abuse_strikes") is not None:
            user.abuse_strikes = result["abuse_strikes"]
            db.commit()
        msg, action = _user_message(request.message, route, "M0", "P0", block_reason, None)
        remaining = limit - (session.message_count or 0)
        return ChatResponse(message=msg, action=action, doctor_specialty=None, session_id=session.id, remaining_prompts=remaining)

    if route == "unclear":
        session.last_activity = datetime.utcnow()
        session.message_count = (session.message_count or 0) + 1
        db.commit()
        msg = await _generate_unclear_reply(request.message)
        remaining = limit - session.message_count
        return ChatResponse(message=msg, action=None, doctor_specialty=None, session_id=session.id, remaining_prompts=remaining)

    session.last_activity = datetime.utcnow()
    session.message_count = (session.message_count or 0) + 1
    db.commit()

    severity_medical = "M1"
    severity_psychological = "P0"
    doctor_specialty = result.get("doctor_specialty")
    doctor_suggestion_text = result.get("doctor_suggestion_text")

    if route == "medical":
        severity_medical, severity_psychological = calculate_severity([request.message])

    msg, action = _user_message(
        request.message,
        route, severity_medical, severity_psychological, block_reason,
        doctor_specialty=doctor_specialty,
        doctor_suggestion_text=doctor_suggestion_text,
    )

    if route == "medical":
        try:
            msg = run_medical_pipeline(request.message, severity_medical)
            if action == "doctors" and "nearby" not in msg.lower():
                msg = msg.rstrip() + " I can help you find a doctor nearby if you share your location."
        except Exception as e:
            logger.warning("Medical pipeline failed: %s", e)

    remaining = limit - session.message_count
    return ChatResponse(
        message=msg,
        action=action,
        doctor_specialty=doctor_specialty if action == "doctors" else None,
        doctor_suggestion_text=doctor_suggestion_text if action == "doctors" else None,
        session_id=session.id,
        remaining_prompts=remaining,
    )
