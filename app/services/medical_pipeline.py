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
    Flow: one Gemini call (severity + reply). Returns (message, severity_medical). On failure, fallback and "M1".
    """
    symptoms = (symptoms or "").strip()[:2000]
    if not symptoms:
        return _fallback("M1"), "M1"
    return _severity_and_reply(symptoms)


def _severity_and_reply(symptoms: str) -> tuple[str, str]:
    """One call: Gemini returns severity code (M0–M3) and full reply. Parse and normalize."""
    if not settings.google_api_key:
        return _fallback("M1"), "M1"
    sys = """You are a medical info assistant for education only. Not a doctor; not professional advice.
You may suggest common over-the-counter (OTC) non-prescription options for mild symptoms (e.g. acetaminophen/paracetamol for fever or pain, saline nasal spray or throat lozenges for cold). Do not suggest prescription drugs. Always say to follow the label and see a doctor if symptoms are severe or persist.

Reply in this exact format. Line 1: one severity code only—M0, M1, M2, or M3. Line 2 and below: use exactly these headings (copy verbatim). If the user asks for medication or for mild/self-care symptoms, include an OTC options line.
Possible causes: (1-3 short items)
OTC options: (when relevant: common non-prescription options and "follow the label"; omit if not relevant)
Urgency: (one word: low, moderate, or high)
When to see a doctor: (one short sentence)
Max 120 words total after the headings."""
    user = f"Symptoms: {symptoms}\n\nYour reply (line 1 = code only; then Possible causes:, optionally OTC options:, Urgency:, When to see a doctor:):"
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=settings.google_api_key)
        r = llm.invoke([SystemMessage(content=sys), HumanMessage(content=user)])
        raw = (r.content or "").strip()
        severity = _parse_severity(raw)
        reply = _strip_severity_line(raw)
        reply = _drop_disclaimer(reply)
        reply = _normalize_urgency(reply, severity)
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
    # Ensure "When to see a doctor:" starts on a new line (not "Urgency:LowWhen...")
    text = re.sub(r"(Low|Medium|High)(\s*)When to see a doctor:", r"\1\nWhen to see a doctor:", text, flags=re.IGNORECASE)
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
