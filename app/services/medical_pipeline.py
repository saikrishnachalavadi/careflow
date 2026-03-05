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
    Router already classified as medical. Returns (message, severity_medical).
    Message is only 3 parts: Possible causes, Non prescriptive, When to see a doctor.
    """
    symptoms = (symptoms or "").strip()[:2000]
    if not symptoms:
        return _fallback("M1"), "M1"
    return _severity_and_reply(symptoms)


def _severity_and_reply(symptoms: str) -> tuple[str, str]:
    """One call: severity (M0–M3) + 3-part reply only. Router already said medical."""
    if not settings.google_api_key:
        return _fallback("M1"), "M1"
    sys = """You are a medical info assistant for education only. Not a doctor; not professional advice.
The router has already classified this as medical.

Reply format: Line 1 = one severity code only (M0, M1, M2, or M3). Line 2 and below use ONLY these three headings:
Possible causes: (one brief line)
Non prescriptive: (when relevant: common non-prescription OTC options and "follow the label"; omit if not relevant)
When to see a doctor: (one short sentence)
Max 120 words total after the headings. You may suggest common OTC options. Do not suggest prescription drugs."""

    user = f"User message: {symptoms}\n\nYour reply (line 1 = M0/M1/M2/M3 then only the 3 headings above):"
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=settings.google_api_key)
        r = llm.invoke([SystemMessage(content=sys), HumanMessage(content=user)])
        raw = (r.content or "").strip()
        severity = _parse_severity(raw)
        reply = _strip_severity_line(raw)
        reply = _drop_disclaimer(reply)
        reply = _truncate_to_words(reply, 120)
        if reply:
            return reply, severity
    except Exception as e:
        logger.warning("Medical reply failed: %s", e)
    return _fallback("M1"), "M1"


def _parse_severity(raw: str) -> str:
    """Extract M0|M1|M2|M3 from first line or anywhere in text."""
    upper = raw.upper()
    for code in ("M3", "M2", "M0", "M1"):
        if code in upper:
            return code
    return "M1"


def _strip_severity_line(raw: str) -> str:
    """Remove first line if it is only a severity code (M0, M1, M2, M3), return rest as reply."""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return raw
    first = re.sub(r"[^\w]", "", lines[0].upper())
    if first in ("M0", "M1", "M2", "M3"):
        return "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    return raw


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
        return "Possible causes: Needs assessment.\nWhen to see a doctor: See doctor or emergency services now."
    return "Possible causes: Unclear.\nWhen to see a doctor: Consider speaking with a doctor for evaluation."
