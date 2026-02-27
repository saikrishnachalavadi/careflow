"""
Mental health: handoff-first (same as physical). P0–P3 severity for later use.
Crisis helplines returned; nearby psychologists/psychiatrists/counselors with phones.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.core.severity import calculate_severity
from app.services.maps import get_mental_health_with_phones, geocode

router = APIRouter()

CRISIS_HELPLINES = [
    {"name": "iCall", "number": "9152987821"},
    {"name": "Vandrevala Foundation", "number": "1860-2662-345"},
]


class AssessRequest(BaseModel):
    user_id: str
    message: str


@router.post("/assess")
async def assess_mental_health(body: AssessRequest):
    """Assess psychological severity (P0–P3). Handoff-first: recommend therapist or crisis helpline."""
    _, severity_psychological = calculate_severity([body.message])

    if severity_psychological == "P3":
        return {
            "severity": "P3",
            "action": "crisis_helpline",
            "message": "Please reach out to a crisis helpline. You are not alone.",
            "helplines": CRISIS_HELPLINES,
        }
    if severity_psychological == "P2":
        return {
            "severity": "P2",
            "action": "therapist_handoff",
            "message": "Talking to a professional can help. We recommend connecting with a therapist.",
        }
    if severity_psychological == "P1":
        return {
            "severity": "P1",
            "action": "supportive_response",
            "message": "Take care. If things feel heavier, consider speaking with a counselor.",
        }
    return {
        "severity": "P0",
        "action": "supportive_response",
        "message": "Thanks for sharing. CareFlow is here if you need to talk to a professional.",
    }


@router.get("/crisis-helplines")
async def get_crisis_helplines():
    """Get crisis helpline numbers."""
    return {"helplines": CRISIS_HELPLINES}


@router.get("/nearby")
async def get_nearby_mental_health(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    q: Optional[str] = None,
    specialty: Optional[str] = None,
):
    """Get mental health professionals by coordinates (lat, lon) or by place query (q=city). Returns only with phone numbers."""
    if lat is None or lon is None:
        if q:
            coords = geocode(q)
            if not coords:
                return {"professionals": [], "error": "Could not find that place. Try a city name."}
            lat, lon = coords
        else:
            return {"professionals": [], "error": "Provide lat and lon, or q (e.g. city name)."}
    professionals = get_mental_health_with_phones(lat, lon, specialty=specialty)
    return {"professionals": professionals}
