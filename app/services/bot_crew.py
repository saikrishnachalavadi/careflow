"""
Medical chat bot using LangGraph + Gemini. Third LLM call in the app (router, medical pipeline, bot).
Uses same LangChain/LangSmith tracing as call 1 and call 2.
"""
import logging
from typing import List, Optional
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.config import settings

logger = logging.getLogger(__name__)

# Fallback when Gemini is unavailable
_BOT_FALLBACK = (
    "I can only help with general health information. "
    "For prescription advice and routing use the main chat."
)

MEDICAL_BOT_SYSTEM = """You are CareFlow's medical bot. Answer medical and health questions helpfully: explain conditions, suggest common OTC options where appropriate, and give practical guidance.

Rules:
- Respond only to medical/health topics; for non-medical questions, politely say you only answer medical questions.
- You may suggest common over-the-counter options (e.g. acetaminophen for fever, throat lozenges for sore throat) and when to see a doctor.
- Do not prescribe prescription drugs.
- Keep replies concise (under 150 words when possible).
- Reply with a single concise, helpful plain-text response."""


def _build_conversation_context(history: List[dict], latest_message: str) -> str:
    """Build a single context string from chat history + latest user message."""
    parts = []
    for item in history or []:
        role = (item.get("role") or "user").lower()
        content = (item.get("content") or "").strip()
        if not content:
            continue
        label = "User" if role == "user" else "Assistant"
        parts.append(f"{label}: {content}")
    if parts:
        parts.append(f"User: {latest_message}")
        return "\n".join(parts)
    return latest_message


# ─── LangGraph state and node ────────────────────────────────────

class BotState(TypedDict):
    context: str
    reply: Optional[str]


def medical_reply_node(state: BotState) -> BotState:
    """Single node: call Gemini with conversation context, return reply."""
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=settings.google_api_key,
        temperature=0.4,
    )
    messages = [
        SystemMessage(content=MEDICAL_BOT_SYSTEM),
        HumanMessage(content=state["context"]),
    ]
    response = llm.invoke(messages)
    reply = (response.content or "").strip()
    return {**state, "reply": reply or _BOT_FALLBACK}


def _build_bot_graph():
    """Build and compile the medical bot graph (single node)."""
    graph = StateGraph(BotState)
    graph.add_node("reply", medical_reply_node)
    graph.set_entry_point("reply")
    graph.add_edge("reply", END)
    return graph.compile()


_bot_graph = None


def _get_bot_graph():
    """Lazy-compile the graph once."""
    global _bot_graph
    if _bot_graph is None:
        _bot_graph = _build_bot_graph()
    return _bot_graph


def run_bot(message: str, history: Optional[List[dict]] = None) -> str:
    """
    Run the medical assistant on the user's message (with optional history).
    Returns the assistant's reply. Uses LangGraph + Gemini; traces to LangSmith like router and pipeline.
    """
    if not (message or "").strip():
        return "Please type a health-related question or topic."
    if not settings.google_api_key:
        logger.warning("Bot: no Google API key configured")
        return _BOT_FALLBACK

    context = _build_conversation_context(history or [], message.strip())

    try:
        graph = _get_bot_graph()
        result = graph.invoke({"context": context, "reply": None})
        reply = result.get("reply") or _BOT_FALLBACK
        return reply.strip() or _BOT_FALLBACK
    except Exception as e:
        logger.exception("Bot failed: %s", e)
        return _BOT_FALLBACK
