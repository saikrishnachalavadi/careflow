"""
Smart doctor routing: capability tags, night logic (10 PM–7 AM open only), ranking.
Handoff popup: location or city search (q=), returns only doctors with phone numbers.
"""
from fastapi import APIRouter
from typing import Optional

from app.services.maps import get_nearby_doctors, get_doctors_with_phones, geocode

router = APIRouter()


@router.get("/nearby")
async def get_nearby_doctors_endpoint(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    q: Optional[str] = None,
    specialty: Optional[str] = None,
    skip: int = 0,
    limit: int = 10,
):
    """Get doctors by coordinates (lat, lon) or by place query (q=city). skip/limit for Load more (10 per page)."""
    if lat is None or lon is None:
        if q:
            coords = geocode(q)
            if not coords:
                return {"doctors": [], "has_more": False, "error": "Could not find that place. Try a city name."}
            lat, lon = coords
        else:
            return {"doctors": [], "has_more": False, "error": "Provide lat and lon, or q (e.g. city name)."}
    doctors, has_more = get_doctors_with_phones(lat, lon, specialty=specialty, skip=skip, limit=limit)
    return {"doctors": doctors, "has_more": has_more}


@router.post("/handoff")
async def doctor_handoff(session_id: str):
    """Initiate doctor handoff (e.g. record in health timeline)."""
    return {"status": "handoff_initiated", "session_id": session_id}
