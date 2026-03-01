"""
Dr.GPT-style pipeline: symptoms → (optional AWS entities) → PubMed RAG → Gemini → educational reply.
Single entry: run_medical_pipeline(symptoms, severity). Safe fallbacks if APIs fail.
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


def run_medical_pipeline(symptoms: str, severity: str) -> str:
    """
    Dr.GPT flow: extract entities (if AWS) → PubMed search → Gemini with context → reply.
    Returns educational, disclaimer-led text. On any failure, returns safe fallback.
    """
    symptoms = (symptoms or "").strip()[:2000]
    if not symptoms:
        return _fallback(severity)
    entities = _extract_entities(symptoms)
    query = _query(symptoms, entities)
    abstracts = _pubmed(query, 5)
    return _gemini_reply(symptoms, abstracts, severity)


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
                    abstract = (at.text or " ".join(at.itertext())).strip()[:1500]
                    break
            break
        out.append({"pmid": pmid, "title": title, "abstract": abstract})
    return out


def _gemini_reply(symptoms: str, abstracts: list[dict], severity: str) -> str:
    """One prompt: symptoms + PubMed context + severity → brief educational reply (disclaimer)."""
    if not settings.google_api_key:
        return _fallback(severity)
    ctx = "\n\n".join(
        (f"[{a.get('title','')}] {a.get('abstract','')}".strip() for a in abstracts[:5] if a.get("abstract"))
    ) or "(No abstracts retrieved.)"
    sev = {"M3": "High urgency.", "M2": "Moderate; consider a doctor.", "M1": "Low.", "M0": "Low."}.get(severity, "Consider evaluation.")
    sys = """You are a medical info assistant for education only. Not a doctor; not professional advice.
In max 120 words: 1) Possible causes (1–3). 2) Urgency: low/moderate/high. 3) When to see a doctor.
End with: "For educational purposes only; not a substitute for professional medical advice." Be concise."""
    user = f"Symptoms: {symptoms}\nSeverity note: {sev}\nResearch:\n{ctx}\nReply:"
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=settings.google_api_key)
        r = llm.invoke([SystemMessage(content=sys), HumanMessage(content=user)])
        t = (r.content or "").strip()
        if t and len(t) < 1800:
            return t
    except Exception as e:
        logger.warning("Gemini medical reply failed: %s", e)
    return _fallback(severity)


def _fallback(severity: str) -> str:
    if severity == "M3":
        return "This may need prompt care. Please seek help or call emergency services if needed. For educational purposes only; not a substitute for professional medical advice."
    return "Consider speaking with a doctor for evaluation. For educational purposes only; not a substitute for professional medical advice."
