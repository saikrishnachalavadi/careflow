"""
Medical pipeline: symptoms → Gemini (severity + reply). No RAG, no AWS Comprehend.
Reply step uses Gemini; can be swapped for Google Medical API when integrated.
"""
import logging
import re

from app.config import settings

logger = logging.getLogger(__name__)


def run_medical_pipeline(symptoms: str) -> tuple[str, str]:
    """
    Flow: severity-only call (Gemini) → medical reply call (Gemini, symptoms only).
    Returns (message, severity_medical). On failure, returns fallback message and "M1".
    """
    symptoms = (symptoms or "").strip()[:2000]
    if not symptoms:
        return _fallback("M1"), "M1"
    severity = _severity_only(symptoms)
    return _medical_reply(symptoms, severity)


def _severity_only(symptoms: str) -> str:
    """One small call: symptoms only → M0|M1|M2|M3."""
    if not settings.google_api_key:
        return "M1"
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=settings.google_api_key)
        sys = "You are a triage assistant. Reply with ONLY one code: M0, M1, M2, or M3. M0=no concern, M1=low/self-care, M2=moderate/see doctor, M3=emergency. No other text."
        r = llm.invoke([SystemMessage(content=sys), HumanMessage(content=symptoms)])
        raw = (r.content or "").strip().upper()
        for code in ("M3", "M2", "M0", "M1"):
            if code in raw:
                return code
    except Exception as e:
        logger.debug("Severity call failed: %s", e)
    return "M1"


def _medical_reply(symptoms: str, severity: str) -> tuple[str, str]:
    """One call: Gemini (symptoms only). Format: Possible causes, Urgency (1 word), When to see a doctor. Replace with Google Medical API when integrated."""
    if not settings.google_api_key:
        return _fallback(severity), severity
    sys = """You are a medical info assistant for education only. Not a doctor; not professional advice.
Based on the symptoms given, in max 120 words: 1) Possible causes (1-3). 2) Urgency: low, moderate, or high. 3) When to see a doctor."""
    user = f"Symptoms: {symptoms}\n\nYour reply (max 120 words, concise):"
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=settings.google_api_key)
        r = llm.invoke([SystemMessage(content=sys), HumanMessage(content=user)])
        reply = (r.content or "").strip()
        reply = _drop_disclaimer(reply)
        reply = _normalize_urgency(reply, severity)
        reply = _truncate_to_words(reply, 120)
        if reply:
            return reply, severity
    except Exception as e:
        logger.warning("Medical reply failed: %s", e)
    return _fallback(severity), severity


def _normalize_urgency(text: str, severity: str) -> str:
    """Force 'Urgency: ...' to be exactly 1 word: Low, Medium, or High. Mapping: M3→High, M2→Medium, M0/M1→Low."""
    severity_to_urgency = {"M3": "High", "M2": "Medium", "M1": "Low", "M0": "Low"}
    urgency_word = severity_to_urgency.get(severity, "Medium")
    m = re.search(r"(\bUrgency\s*:\s*)(.+?)(?=\s*When to see|$)", text, re.IGNORECASE | re.DOTALL)
    if m:
        rest = m.group(2).strip().rstrip(".").strip()
        first = rest.split()[0].lower() if rest.split() else ""
        if first in ("low", "medium", "high", "moderate"):
            replacement = "Medium" if first == "moderate" else first.capitalize()
        else:
            replacement = urgency_word
        before, after = text[: m.start(2)], text[m.end(2) :]
        text = before + replacement + after
    return text


def _drop_disclaimer(text: str) -> str:
    """Remove common disclaimer sentence if present."""
    for phrase in (
        "for educational purposes only",
        "not a substitute for professional medical advice",
        "not medical advice",
    ):
        idx = text.lower().find(phrase)
        if idx != -1:
            before = text[:idx].rstrip().rstrip(".;")
            after = text[idx + len(phrase):].lstrip().lstrip(".;")
            text = (before + " " + after).strip()
    return text.strip()


def _truncate_to_words(text: str, max_words: int) -> str:
    """If over max_words, truncate to first max_words words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _fallback(severity: str) -> str:
    if severity == "M3":
        return "Possible causes: Needs assessment. Urgency: High. See doctor or emergency services now."
    return "Possible causes: Unclear. Urgency: Low. Consider speaking with a doctor for evaluation."
