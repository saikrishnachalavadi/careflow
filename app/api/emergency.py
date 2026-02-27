"""
Emergency flow: 3-step confirmation then show 112, ambulances, hospitals.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.services.maps import get_emergency_services

router = APIRouter()

# In-memory confirmation state (session_id -> step 1..3). Use Redis/DB in production.
_emergency_confirmation: dict[str, int] = {}


class ConfirmRequest(BaseModel):
    session_id: str
    confirmed: bool  # user confirmed "yes" for current step


class EmergencyServicesResponse(BaseModel):
    emergency_number: str
    ambulances: list
    hospitals: list


def _next_step(session_id: str, confirmed: bool) -> tuple[int, str]:
    """Returns (current_step, message). Step 3 done -> return (3, 'show_services')."""
    step = _emergency_confirmation.get(session_id, 0)
    if not confirmed:
        _emergency_confirmation[session_id] = 0
        return (0, "Emergency flow cancelled. If you're safe, you can describe your symptoms for triage.")
    step += 1
    _emergency_confirmation[session_id] = step
    if step == 1:
        return (1, "Are you or someone else currently experiencing a life-threatening emergency (e.g. chest pain, stroke, severe bleeding, difficulty breathing)? Reply yes to continue.")
    if step == 2:
        return (2, "Please confirm: you need emergency services now. Reply yes to see emergency numbers and nearby help.")
    if step >= 3:
        return (3, "show_services")
    return (step, "")


@router.post("/confirm")
async def confirm_emergency(body: ConfirmRequest):
    """3-step emergency confirmation. After step 3, call GET /emergency/services with location to get 112, ambulances, hospitals."""
    step, message = _next_step(body.session_id, body.confirmed)
    if step == 3:
        return {"step": 3, "message": "Please share your location to see nearby emergency services.", "ready_for_services": True}
    return {"step": step, "message": message, "ready_for_services": False}


@router.get("/services")
async def get_emergency_services_endpoint(lat: Optional[float] = None, lon: Optional[float] = None, q: Optional[str] = None):
    """Get emergency services by coordinates (lat, lon) or by place query (q=city or address)."""
    if lat is None or lon is None:
        if q:
            from app.services.maps import geocode
            coords = geocode(q)
            if not coords and "india" not in q.strip().lower():
                coords = geocode(q.strip() + ", India")
            if not coords:
                return {
                    "emergency_number": "112",
                    "ambulances": [],
                    "hospitals": [],
                    "error": "Could not find that place. Try 'Hyderabad, India' or enable Geocoding API in Google Cloud for your key.",
                }
            lat, lon = coords
        else:
            return {"emergency_number": "112", "ambulances": [], "hospitals": [], "error": "Provide lat and lon, or q (e.g. city name)."}
    data = get_emergency_services(lat, lon)
    return {
        "emergency_number": data["emergency_number"],
        "ambulances": data["ambulances"],
        "hospitals": data["hospitals"],
    }
