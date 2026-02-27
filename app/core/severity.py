"""
CareFlow severity scoring: M0–M3 (medical), P0–P3 (psychological).
Uses Gemini when available; falls back to rule-based heuristics.
"""
from typing import Tuple, Literal

from app.config import settings

MedicalSeverity = Literal["M0", "M1", "M2", "M3"]
PsychologicalSeverity = Literal["P0", "P1", "P2", "P3"]

EMERGENCY_KEYWORDS = [
    "stroke", "chest pain", "heart attack", "severe bleeding",
    "unconscious", "not breathing", "seizure", "overdose",
    "can't breathe", "suicidal", "suicide", "severe pain",
]

HIGH_MEDICAL_KEYWORDS = [
    "severe", "critical", "intense pain", "high fever", "vomiting blood",
    "allergic reaction", "broken bone", "deep cut", "burn",
]

MODERATE_MEDICAL_KEYWORDS = [
    "fever", "cough", "headache", "stomach", "rash", "infection",
    "pain", "dizzy", "nausea", "cold", "flu",
]

LOW_PSYCH_KEYWORDS = ["stress", "tired", "sleep", "worried", "mood"]
MODERATE_PSYCH_KEYWORDS = ["anxiety", "panic", "depressed", "insomnia", "overwhelmed"]
CRISIS_PSYCH_KEYWORDS = ["suicidal", "suicide", "self-harm", "end my life", "want to die"]


def _severity_with_ai(message: str) -> Tuple[MedicalSeverity, PsychologicalSeverity]:
    """Use Gemini to output M0–M3 and P0–P3."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage
    except ImportError:
        return _severity_rules(message)

    if not settings.google_api_key:
        return _severity_rules(message)

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=settings.google_api_key,
    )
    prompt = SystemMessage(content="""You are a triage assistant. Given the user's health message, output exactly two codes separated by a comma: medical severity then psychological severity.

Medical: M0=no concern, M1=low/self-care, M2=moderate/doctor recommended, M3=high/emergency.
Psychological: P0=no concern, P1=low, P2=moderate/therapist helpful, P3=crisis/immediate helpline.

Reply with ONLY two codes, e.g. M1,P0 or M2,P2. No other text.""")
    resp = llm.invoke([prompt, HumanMessage(content=message)])
    text = (resp.content or "").strip().upper()
    parts = [p.strip() for p in text.replace(",", " ").split() if p.strip()]
    m = "M1"
    p = "P0"
    for part in parts:
        if part in ("M0", "M1", "M2", "M3"):
            m = part
        elif part in ("P0", "P1", "P2", "P3"):
            p = part
    return (m, p)  # type: ignore


def _severity_rules(message: str) -> Tuple[MedicalSeverity, PsychologicalSeverity]:
    """Rule-based fallback when AI is unavailable."""
    msg = message.lower()

    # Psychological first (crisis overrides)
    for kw in CRISIS_PSYCH_KEYWORDS:
        if kw in msg:
            return ("M1", "P3")  # P3 = crisis helpline
    for kw in MODERATE_PSYCH_KEYWORDS:
        if kw in msg:
            return ("M1", "P2")
    for kw in LOW_PSYCH_KEYWORDS:
        if kw in msg:
            return ("M0", "P1")

    # Emergency
    for kw in EMERGENCY_KEYWORDS:
        if kw in msg:
            return ("M3", "P0")

    # Medical
    for kw in HIGH_MEDICAL_KEYWORDS:
        if kw in msg:
            return ("M2", "P0")
    for kw in MODERATE_MEDICAL_KEYWORDS:
        if kw in msg:
            return ("M1", "P0")

    return ("M1", "P0")  # Default: low medical, no psych concern


def calculate_severity(symptoms: list[str]) -> Tuple[MedicalSeverity, PsychologicalSeverity]:
    """
    Calculate medical (M0–M3) and psychological (P0–P3) severity.
    If symptoms is a list, joins into one message for scoring.
    """
    text = " ".join(symptoms).strip() if symptoms else ""
    if not text:
        return ("M0", "P0")
    if settings.google_api_key:
        return _severity_with_ai(text)
    return _severity_rules(text)


def is_emergency(message: str) -> bool:
    """True if message suggests an emergency."""
    msg = message.lower()
    return any(kw in msg for kw in EMERGENCY_KEYWORDS)
