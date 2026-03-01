"""
Medical chat bot using CrewAI agents. Third LLM call in the app (router, medical pipeline, bot).
"""
import logging
from typing import List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Fallback when CrewAI or Gemini is unavailable
_BOT_FALLBACK = (
    "I can only help with general health information. "
    "For prescription advice and routing use the main chat."
)


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


def run_bot(message: str, history: Optional[List[dict]] = None) -> str:
    """
    Run the CrewAI medical assistant agent on the user's message (with optional history).
    Returns the assistant's reply. This is the third LLM call (router, medical pipeline, bot).
    """
    if not (message or "").strip():
        return "Please type a health-related question or topic."
    if not settings.google_api_key:
        logger.warning("Bot: no Google API key configured")
        return _BOT_FALLBACK

    try:
        from crewai import Agent, Crew, LLM, Process, Task
    except ImportError as e:
        logger.warning("Bot: CrewAI not available: %s", e)
        return _BOT_FALLBACK

    context = _build_conversation_context(history or [], message.strip())

    try:
        llm = LLM(
            model="gemini-2.5-flash",
            api_key=settings.google_api_key,
            temperature=0.4,
        )
        medical_agent = Agent(
            role="Medical information assistant",
            goal="Answer health-related questions in a clear, educational, and non-diagnostic way.",
            backstory=(
                "You are a helpful assistant within CareFlow. You provide general health information "
                "and education. You never diagnose or prescribe. You encourage users to see a doctor "
                "when needed and keep replies concise (under 150 words when possible)."
            ),
            llm=llm,
            verbose=False,
        )
        task = Task(
            description=(
                "Based on the following conversation, reply to the user's latest message. "
                "Be helpful, accurate, and non-diagnostic. Do not prescribe or diagnose. "
                "Keep the reply concise.\n\nConversation:\n" + context
            ),
            expected_output="A single concise reply to the user (plain text, no bullet list unless helpful).",
            agent=medical_agent,
        )
        crew = Crew(agents=[medical_agent], tasks=[task], process=Process.sequential)
        result = crew.kickoff()
        if hasattr(result, "raw") and result.raw:
            return (result.raw or "").strip() or _BOT_FALLBACK
        if isinstance(result, str):
            return result.strip() or _BOT_FALLBACK
        # CrewOutput or similar
        out = getattr(result, "raw", None) or str(result)
        return (out or "").strip() or _BOT_FALLBACK
    except Exception as e:
        logger.exception("Bot crew failed: %s", e)
        return _BOT_FALLBACK
