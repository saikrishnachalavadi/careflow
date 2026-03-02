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


def _set_span_token_usage(result: object) -> None:
    """Set token usage on the current OpenTelemetry span so LangSmith can show Tokens/Cost for crewai.workflow runs."""
    usage = getattr(result, "token_usage", None)
    if not usage or (getattr(usage, "total_tokens", 0) == 0 and getattr(usage, "prompt_tokens", 0) == 0):
        return
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if not span or not span.is_recording():
            return
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens)
        if total_tokens == 0:
            return
        # LangSmith / OpenLLMetry-style attributes so Tokens column can be populated
        span.set_attribute("gen_ai.prompt.tokens", prompt_tokens)
        span.set_attribute("gen_ai.completion.tokens", completion_tokens)
        span.set_attribute("gen_ai.total.tokens", total_tokens)
        # Alternate names some backends expect
        span.set_attribute("llm.token_count.prompt", prompt_tokens)
        span.set_attribute("llm.token_count.completion", completion_tokens)
        span.set_attribute("langsmith.metadata.total_tokens", total_tokens)
    except Exception as e:
        logger.debug("Could not set span token usage: %s", e)


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
            role="Medical assistant",
            goal="Answer medical and health questions helpfully: explain conditions, suggest common OTC options where appropriate, and give practical guidance. Only restriction: respond only to medical/health topics; decline non-medical questions.",
            backstory=(
                "You are CareFlow's medical bot. You give clear, useful health information. You may suggest "
                "common over-the-counter options (e.g. acetaminophen for fever, throat lozenges for sore throat) "
                "and when to see a doctor. Do not prescribe prescription drugs. If the user asks something "
                "not related to health or medicine, politely say you only answer medical questions. Keep replies "
                "concise (under 150 words when possible)."
            ),
            llm=llm,
            verbose=False,
        )
        task = Task(
            description=(
                "Reply to the user's latest message. You may recommend common OTC options and give practical "
                "health advice. Do not prescribe prescription medicines. If the question is not about health or "
                "medicine, say you only answer medical questions. Otherwise be helpful and concise.\n\n"
                "Conversation:\n" + context
            ),
            expected_output="A single concise, helpful reply (plain text).",
            agent=medical_agent,
        )
        crew = Crew(agents=[medical_agent], tasks=[task], process=Process.sequential)
        result = crew.kickoff()

        # Attach token usage to current OpenTelemetry span so LangSmith shows Tokens/Cost for crewai.workflow
        _set_span_token_usage(result)

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
