from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from app.api import triage, chat, emergency, doctors, pharmacy, labs, mental_health, auth
from app.db.database import init_db
from app.observability import setup_langsmith_crewai_tracing

app = FastAPI(
    title="CareFlow",
    description="AI-powered healthcare navigation and triage platform",
    version="0.1.0"
)


@app.on_event("startup")
def on_startup():
    """Create SQLite tables on startup. No PostgreSQL required."""
    init_db()
    # Connect CrewAI (Medical bot) to LangSmith via OpenTelemetry
    setup_langsmith_crewai_tracing()


# Register routers
app.include_router(triage.router, prefix="/triage", tags=["Triage"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(emergency.router, prefix="/emergency", tags=["Emergency"])
app.include_router(doctors.router, prefix="/doctors", tags=["Doctors"])
app.include_router(pharmacy.router, prefix="/pharmacy", tags=["Pharmacy"])
app.include_router(labs.router, prefix="/labs", tags=["Labs"])
app.include_router(mental_health.router, prefix="/mental-health", tags=["Mental Health"])
app.include_router(auth.router, prefix="/auth", tags=["Auth"])


@app.get("/")
async def root():
    return {"message": "Welcome to CareFlow", "status": "healthy"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# Simple UI – open in browser
_ui_path = Path(__file__).parent / "static" / "index.html"


@app.get("/ui")
async def ui():
    """Serve the triage UI. Open this in your browser."""
    return FileResponse(_ui_path, media_type="text/html")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Ensure all errors return JSON so the UI can display them."""
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "message": str(exc),
            "error": "internal_error",
        },
    )