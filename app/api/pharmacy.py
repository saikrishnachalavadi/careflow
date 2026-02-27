"""
Pharmacy: nearby list (with phones, optional city search q=) + OTC request.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.db.database import get_db
from app.db.models import User
from app.services.maps import get_pharmacies_with_phones, geocode
from app.config import settings

router = APIRouter()


class OTCRequest(BaseModel):
    user_id: str
    symptom: str


@router.get("/nearby")
async def get_nearby_pharmacies_endpoint(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    q: Optional[str] = None,
):
    """Get pharmacies by coordinates (lat, lon) or by place query (q=city). Returns only pharmacies with phone numbers."""
    if lat is None or lon is None:
        if q:
            coords = geocode(q)
            if not coords:
                return {"pharmacies": [], "error": "Could not find that place. Try a city name."}
            lat, lon = coords
        else:
            return {"pharmacies": [], "error": "Provide lat and lon, or q (e.g. city name)."}
    pharmacies = get_pharmacies_with_phones(lat, lon)
    return {"pharmacies": pharmacies}


@router.post("/otc-request")
async def request_otc(body: OTCRequest, db: Session = Depends(get_db)):
    """Handle OTC medication request. Checks OTC attempts remaining (max 3). LOCKED after 3."""
    user = db.query(User).filter(User.id == body.user_id).first()
    if not user:
        return {"status": "error", "message": "User not found", "otc_attempts_remaining": 0}

    if (user.otc_privilege_status or "").upper() == "LOCKED":
        return {
            "status": "locked",
            "message": "OTC privilege locked. Contact support to request unlock.",
            "otc_attempts_remaining": 0,
        }

    used = user.otc_attempts_used or 0
    remaining = max(0, settings.max_otc_attempts - used)

    if remaining <= 0:
        user.otc_privilege_status = "LOCKED"
        db.commit()
        return {
            "status": "locked",
            "message": "No OTC attempts remaining. OTC privilege locked.",
            "otc_attempts_remaining": 0,
        }

    return {
        "status": "pending",
        "otc_attempts_remaining": remaining,
        "message": f"You have {remaining} OTC suggestion(s) remaining. A healthcare professional will review your request.",
    }
