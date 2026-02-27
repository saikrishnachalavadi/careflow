"""
Labs: nearby diagnostic labs (with phones, optional city search q=) + book lab test.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
import uuid
from datetime import datetime
from typing import Optional

from app.db.database import get_db
from app.db.models import HealthEvent
from app.services.maps import get_labs_with_phones, geocode

router = APIRouter()


class BookLabRequest(BaseModel):
    user_id: str
    test_type: str
    lab_id: str


@router.get("/nearby")
async def get_nearby_labs_endpoint(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    q: Optional[str] = None,
):
    """Get labs by coordinates (lat, lon) or by place query (q=city). Returns only labs with phone numbers."""
    if lat is None or lon is None:
        if q:
            coords = geocode(q)
            if not coords:
                return {"labs": [], "error": "Could not find that place. Try a city name."}
            lat, lon = coords
        else:
            return {"labs": [], "error": "Provide lat and lon, or q (e.g. city name)."}
    labs = get_labs_with_phones(lat, lon)
    return {"labs": labs}


@router.post("/book")
async def book_lab_test(body: BookLabRequest, db: Session = Depends(get_db)):
    """Book a lab test: create HEALTH EVENT and return status."""
    event = HealthEvent(
        id=str(uuid.uuid4()),
        user_id=body.user_id,
        event_type="LAB",
        description=f"Lab booking: {body.test_type} at lab_id={body.lab_id}",
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()
    return {"status": "booking_initiated", "event_id": event.id, "test_type": body.test_type, "lab_id": body.lab_id}
