"""
Dr.GPT-style pipeline: symptoms → (optional AWS entities) → PubMed RAG → Gemini → educational reply.
Single entry: run_medical_pipeline(symptoms). Severity-only call then RAG-reply call. Safe fallbacks if APIs fail.
"""
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)
PUBMED = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TIMEOUT = 12.0


def run_medical_pipeline(symptoms: str) -> tuple[str, str]:
    """
    Dr.GPT flow: PubMed RAG (3 abstracts, 500–600 chars each) → severity-only call → RAG-reply call.
    Returns (message, severity_medical). On failure, returns fallback message and "M1".
    """
    symptoms = (symptoms or "").strip()[:2000]
    if not symptoms:
        return _fallback("M1"), "M1"
    entities = _extract_entities(symptoms)
    query = _query(symptoms, entities)
    abstracts = _pubmed(query, 3)
    severity = _severity_only(symptoms)
    return _rag_reply(symptoms, abstracts, severity)


def _extract_entities(text: str) -> dict:
    """AWS Comprehend Medical; empty dict if not configured or error."""
    if not settings.aws_region:
        return {}
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
        client = boto3.client(
            "comprehendmedical",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        text = text.encode("utf-8")[:20000].decode("utf-8", errors="ignore")
        out = client.detect_entities_v2(Text=text)
        by_cat: dict[str, list[str]] = {}
        for e in out.get("Entities") or []:
            cat = e.get("Category") or "OTHER"
            t = (e.get("Text") or "").strip()
            if t and (cat not in by_cat or t not in by_cat[cat]):
                by_cat.setdefault(cat, []).append(t)
        return {"by_category": by_cat}
    except Exception as e:
        logger.debug("Comprehend Medical skip: %s", e)
        return {}


def _query(msg: str, entities: dict) -> str:
    """Search query from message + entity terms."""
    parts = [re.sub(r"\s+", " ", msg.strip())[:400]]
    for cat in ("MEDICAL_CONDITION", "SYMPTOM", "MEDICATION"):
        for t in (entities.get("by_category") or {}).get(cat, [])[:5]:
            if t and t not in parts[0]:
                parts.append(t)
    return " ".join(parts)[:500]


def _pubmed(query: str, n: int) -> list[dict]:
    """PubMed E-utilities: esearch → efetch. Returns [{pmid, title, abstract}]."""
    if not query:
        return []
    params = {"db": "pubmed", "retmode": "json", "retmax": n, "sort": "relevance", "term": query}
    if settings.pubmed_api_key:
        params["api_key"] = settings.pubmed_api_key
    try:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.get(f"{PUBMED}/esearch.fcgi", params=params)
            r.raise_for_status()
            ids = (r.json().get("esearchresult") or {}).get("idlist") or []
        if not ids:
            return []
        fp = {"db": "pubmed", "retmode": "xml", "id": ",".join(ids[:n])}
        if settings.pubmed_api_key:
            fp["api_key"] = settings.pubmed_api_key
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.get(f"{PUBMED}/efetch.fcgi", params=fp)
            r.raise_for_status()
            root = ET.fromstring(r.text)
    except Exception as e:
        logger.warning("PubMed failed: %s", e)
        return []
    out = []
    for art in root.iter("PubmedArticle"):
        pmid = next((a.text or "" for a in art.iter("ArticleId") if a.get("IdType") == "pubmed"), "")
        title, abstract = "", ""
        for a in art.iter("Article"):
            for t in a.iter("ArticleTitle"):
                title = (t.text or " ".join(t.itertext())).strip()
                break
            for ab in a.iter("Abstract"):
                for at in ab.iter("AbstractText"):
                    abstract = (at.text or " ".join(at.itertext())).strip()[:600]
                    break
            break
        out.append({"pmid": pmid, "title": title, "abstract": abstract})
    return out


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


def _rag_reply(symptoms: str, abstracts: list[dict], severity: str) -> tuple[str, str]:
    """One call: use the Research section above; keep causes/urgency specific to symptoms and research; 60–80 words."""
    if not settings.google_api_key:
        return _fallback(severity), severity
    ctx = "\n\n".join(
        (f"[{a.get('title','')}] {a.get('abstract','')}".strip() for a in abstracts[:3] if a.get("abstract"))
    ) or "(No abstracts retrieved.)"
    sys = """You are a medical info assistant. Use the Research section above. Keep possible causes, urgency, and when to see a doctor specific to the user's symptoms and to the research—do not give generic filler. Reply in 60–80 words. Use format: Possible causes: ... Urgency: ... When to see a doctor: ... No disclaimer."""
    user = f"Symptoms: {symptoms}\n\nResearch section above:\n{ctx}\n\nYour reply (60–80 words, grounded in the research):"
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=settings.google_api_key)
        r = llm.invoke([SystemMessage(content=sys), HumanMessage(content=user)])
        reply = (r.content or "").strip()
        reply = _drop_disclaimer(reply)
        reply = _truncate_to_words(reply, 80)
        if reply:
            return reply, severity
    except Exception as e:
        logger.warning("RAG reply failed: %s", e)
    return _fallback(severity), severity


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
