"""
LangSmith + OpenTelemetry integration so CrewAI (and other OTel-instrumented code) traces appear in LangSmith.
Uses LANGCHAIN_API_KEY / LANGCHAIN_PROJECT from config; sets LANGSMITH_* env vars for the OTel exporter.
"""
import logging
import os

from app.config import settings

logger = logging.getLogger(__name__)


def setup_langsmith_crewai_tracing() -> None:
    """
    If LangSmith is configured, set LANGSMITH_* env vars and instrument CrewAI with OpenTelemetry
    so Medical bot (CrewAI) runs show up in LangSmith.
    """
    if not settings.langchain_tracing_v2 or not settings.langchain_api_key:
        logger.debug("LangSmith tracing disabled or no API key; skipping CrewAI instrumentation")
        return

    # LangSmith OTel exporter reads these env vars
    os.environ["LANGSMITH_API_KEY"] = settings.langchain_api_key
    os.environ["LANGSMITH_PROJECT"] = getattr(settings, "langchain_project", None) or "careflow"

    try:
        from langsmith.integrations.otel import OtelSpanProcessor
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.instrumentation.crewai import CrewAIInstrumentor
    except ImportError as e:
        logger.warning("LangSmith/CrewAI tracing dependencies missing: %s. Install: pip install opentelemetry-instrumentation-crewai", e)
        return

    try:
        current_provider = trace.get_tracer_provider()
        if isinstance(current_provider, TracerProvider):
            tracer_provider = current_provider
        else:
            tracer_provider = TracerProvider()
            trace.set_tracer_provider(tracer_provider)

        tracer_provider.add_span_processor(OtelSpanProcessor())
        CrewAIInstrumentor().instrument(tracer_provider=tracer_provider)
        logger.info("LangSmith + CrewAI OpenTelemetry instrumentation enabled; project=%s", os.environ.get("LANGSMITH_PROJECT"))
    except Exception as e:
        logger.warning("Failed to enable CrewAI LangSmith tracing: %s", e)
