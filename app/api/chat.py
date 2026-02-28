"""
Chat API: same routing as triage but returns only user-facing message + optional action.
No severity or internal data. Used by the web UI.
"""
import logging
from datetime import datetime
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User, Session as SessionModel
from app.schemas.chat import ChatRequest, ChatResponse
from app.core.router import route_input
from app.core.severity import calculate_severity
from app.config import settings
from app.api.triage import _get_or_create_session

router = APIRouter()
logger = logging.getLogger(__name__)

# Fixed fallback when LLM is unavailable for unclear messages
_UNCLEAR_FALLBACK = "I can only help with health-related questions—symptoms, finding a doctor, pharmacy, lab, or emergencies. What do you need?"


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


# Human-readable labels for doctor specialty (for messages). Unknown specialties are formatted as "a/an {specialty}".
DOCTOR_SPECIALTY_LABELS = {
    "general_physician": "a general physician",
    "pediatrician": "a pediatrician (children's doctor)",
    "dermatologist": "a dermatologist",
    "cardiologist": "a cardiologist",
    "gynecologist": "a gynecologist",
    "orthopedic": "an orthopedic specialist",
    "psychiatrist": "a psychiatrist",
    "clinic": "a doctor or clinic",
    "neurologist": "a neurologist",
    "dentist": "a dentist",
    "ophthalmologist": "an ophthalmologist",
    "ent": "an ENT specialist",
    "gastroenterologist": "a gastroenterologist",
    "pulmonologist": "a pulmonologist",
    "nephrologist": "a nephrologist",
    "urologist": "a urologist",
    "rheumatologist": "a rheumatologist",
    "endocrinologist": "an endocrinologist",
}


def _doctor_specialty_label(specialty: Optional[str]) -> str:
    if not specialty:
        return "a doctor"
    if specialty in DOCTOR_SPECIALTY_LABELS:
        return DOCTOR_SPECIALTY_LABELS[specialty]
    # Free-form from LLM: "a neurologist", "an orthopedist" etc.
    phrase = specialty.replace("_", " ").strip()
    if not phrase:
        return "a doctor"
    article = "an" if phrase[0] in "aeiou" else "a"
    return f"{article} {phrase}"


def _user_message(
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
        doc_label = _doctor_specialty_label(doctor_specialty)
        return (f"I can help you find {doc_label}. Share your location to see nearby options.", "doctors")
    if route == "pharmacy_handoff":
        return ("I can help you find a pharmacy or with over-the-counter options. Share your location for nearby pharmacies.", "pharmacy")
    if route == "lab_handoff":
        return ("I can help you with lab tests. Share your location to find nearby labs.", "labs")
    if route == "unclear":
        # Message is set by caller using _generate_unclear_reply()
        return (_UNCLEAR_FALLBACK, None)
    if route == "medical":
        if severity_medical == "M3":
            return ("Opening nearby emergency services.", "emergency_services")
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
            return (
                f"{doctor_suggestion_text} I can help you find one nearby if you share your location.",
                "doctors",
            )
        doc_label = _doctor_specialty_label(doctor_specialty)
        return (
            f"Based on what you've described, I recommend speaking with {doc_label}. I can help you find one nearby if you share your location.",
            "doctors",
        )
    return ("How can I help you today?", None)


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """Chat endpoint: returns only a user-facing message and optional action. No severity/route exposed."""
    try:
        user = db.query(User).filter(User.id == request.user_id).first()
        abuse_strikes = user.abuse_strikes if user else 0
    except Exception as e:
        logger.exception("Database error loading user")
        raise HTTPException(status_code=503, detail={"message": "Service temporarily unavailable.", "hint": str(e)})

    session, session_error = _get_or_create_session(db, request.user_id)
    if session_error:
        return ChatResponse(message=session_error, action=None, session_id=session.id if session else "none")
    if session.message_count >= settings.max_messages_per_session:
        session.status = "CLOSED"
        db.commit()
        return ChatResponse(
            message="You've reached the message limit for this session. Send another message to start a fresh conversation.",
            action=None,
            session_id=session.id,
        )

    try:
        result = await route_input(
            user_id=request.user_id,
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
        msg, action = _user_message(route, "M0", "P0", block_reason, None)
        return ChatResponse(message=msg, action=action, doctor_specialty=None, session_id=session.id)

    if route == "unclear":
        session.last_activity = datetime.utcnow()
        session.message_count = (session.message_count or 0) + 1
        db.commit()
        msg = await _generate_unclear_reply(request.message)
        return ChatResponse(message=msg, action=None, doctor_specialty=None, session_id=session.id)

    session.last_activity = datetime.utcnow()
    session.message_count = (session.message_count or 0) + 1
    db.commit()

    recommended_action = _route_to_action(route)
    severity_medical = "M1"
    severity_psychological = "P0"
    doctor_specialty = result.get("doctor_specialty")
    doctor_suggestion_text = result.get("doctor_suggestion_text")

    if route == "medical":
        severity_medical, severity_psychological = calculate_severity([request.message])
        if severity_medical == "M3":
            recommended_action = "emergency"
        elif severity_medical in ("M1", "M2"):
            recommended_action = "doctor_handoff"

    msg, action = _user_message(
        route, severity_medical, severity_psychological, block_reason,
        doctor_specialty=doctor_specialty,
        doctor_suggestion_text=doctor_suggestion_text,
    )
    return ChatResponse(
        message=msg,
        action=action,
        doctor_specialty=doctor_specialty if action == "doctors" else None,
        doctor_suggestion_text=doctor_suggestion_text if action == "doctors" else None,
        session_id=session.id,
    )
