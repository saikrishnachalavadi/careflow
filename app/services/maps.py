"""
Google Places API client for CareFlow.
Used for: emergency services, doctors, pharmacies, labs.
Filtering and ranking done in-app (medical keywords, open-now, rating).
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PLACES_BASE = "https://maps.googleapis.com/maps/api/place"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def geocode(query: str, region: str = "in") -> Optional[tuple]:
    """Convert city/address to (lat, lon). Returns None if not found.
    region: country code to bias results (default 'in' for India).
    """
    if not settings.google_maps_api_key or not query or not query.strip():
        return None
    q = query.strip()
    try:
        with httpx.Client(timeout=8.0) as client:
            params = {
                "address": q,
                "key": settings.google_maps_api_key,
                "region": region,
            }
            r = client.get(GEOCODE_URL, params=params)
            r.raise_for_status()
            data = r.json()
        status = data.get("status") or ""
        if status != "OK":
            logger.warning("Geocode status %r for %r", status, q[:50])
            if status == "ZERO_RESULTS" and "india" not in q.lower():
                return _geocode_retry(q + ", India", region)
            return None
        results = data.get("results") or []
        if not results:
            return None
        loc = results[0].get("geometry", {}).get("location", {})
        lat = loc.get("lat")
        lon = loc.get("lng")
        if lat is None or lon is None:
            return None
        return (float(lat), float(lon))
    except Exception as e:
        logger.warning("Geocode failed for %r: %s", q[:50], e)
        return None


def _geocode_retry(query: str, region: str) -> Optional[tuple]:
    """Retry geocode with modified query (e.g. appended ', India')."""
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.get(
                GEOCODE_URL,
                params={"address": query, "key": settings.google_maps_api_key, "region": region},
            )
            r.raise_for_status()
            data = r.json()
        if (data.get("status") or "") != "OK":
            return None
        results = data.get("results") or []
        if not results:
            return None
        loc = results[0].get("geometry", {}).get("location", {})
        lat, lon = loc.get("lat"), loc.get("lng")
        if lat is None or lon is None:
            return None
        return (float(lat), float(lon))
    except Exception:
        return None


def _is_night() -> bool:
    """True between 10 PM and 7 AM (night-time routing)."""
    hour = datetime.utcnow().hour
    return hour >= 22 or hour < 7


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km between two points (WGS84)."""
    import math as _math
    R = 6371  # Earth radius in km
    phi1, phi2 = _math.radians(lat1), _math.radians(lat2)
    dphi = _math.radians(lat2 - lat1)
    dlam = _math.radians(lon2 - lon1)
    a = _math.sin(dphi / 2) ** 2 + _math.cos(phi1) * _math.cos(phi2) * _math.sin(dlam / 2) ** 2
    c = 2 * _math.atan2(_math.sqrt(a), _math.sqrt(1 - a))
    return round(R * c, 1)


def _sort_by_distance(places: List[dict]) -> List[dict]:
    """Sort by distance_km ascending (nearest first). Entries without distance_km go last."""
    return sorted(places, key=lambda p: (p.get("distance_km") is None, p.get("distance_km") if p.get("distance_km") is not None else 0.0))


def _add_distance(place: dict, origin_lat: float, origin_lon: float) -> None:
    """Add distance_km to place in-place from origin (search center)."""
    geo = place.get("geometry") or {}
    loc = geo.get("location") or {}
    lat = loc.get("lat")
    lng = loc.get("lng")
    if lat is not None and lng is not None:
        place["distance_km"] = _haversine_km(origin_lat, origin_lon, float(lat), float(lng))
    else:
        place["distance_km"] = None


def _fetch_nearby(
    lat: float,
    lon: float,
    keyword: str,
    type_filter: Optional[str] = None,
    radius_m: int = 5000,
    open_now: bool = False,
) -> List[dict]:
    """Nearby Search. Returns list of place dicts with name, place_id, rating, opening_hours.
    open_now: if True, pass opennow=1 so Google returns only places open at query time (Google Maps hours).
    """
    if not settings.google_maps_api_key:
        return []

    url = f"{PLACES_BASE}/nearbysearch/json"
    params = {
        "location": f"{lat},{lon}",
        "key": settings.google_maps_api_key,
        "keyword": keyword,
        "radius": radius_m,
    }
    if type_filter:
        params["type"] = type_filter
    if open_now:
        params["opennow"] = 1

    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning("Places API request failed: %s", e)
        return []

    results = data.get("results") or []
    out = []
    for p in results[:20]:
        out.append({
            "name": p.get("name", ""),
            "place_id": p.get("place_id", ""),
            "rating": p.get("rating"),
            "open_now": p.get("opening_hours", {}).get("open_now"),
            "vicinity": p.get("vicinity", ""),
            "geometry": p.get("geometry"),
        })
    return out


def _format_opening_hours_short(oh: dict) -> Optional[str]:
    """Turn opening_hours from Place Details into a short label: '24x7' or today's hours (e.g. '9 AM – 5 PM')."""
    if not oh:
        return None
    weekday_text = oh.get("weekday_text") or []
    if not weekday_text:
        return None
    # Check if all days are "Open 24 hours" (avoid matching "9:24 AM")
    def _is_24h_line(line: str) -> bool:
        part = line.split(":", 1)[-1].strip().lower() if ":" in line else line.lower()
        return "open 24" in part or "24 hours" in part or part == "open 24 hours"
    all_24 = all(_is_24h_line(line) for line in weekday_text)
    if all_24:
        return "24x7"
    # Show today's hours (Python: Monday=0, Sunday=6; weekday_text usually Monday first)
    today_idx = datetime.utcnow().weekday()
    if today_idx < len(weekday_text):
        today_line = weekday_text[today_idx].strip()
        if ":" in today_line:
            time_part = today_line.split(":", 1)[1].strip()
            return time_part if time_part else None
        return today_line
    return weekday_text[0].split(":", 1)[-1].strip() if weekday_text else None


def _get_place_phone(place_id: str) -> Optional[str]:
    """Fetch formatted_phone_number for a place (Place Details)."""
    details = _get_place_contact_and_hours(place_id)
    return details.get("phone") if details else None


def _get_place_contact_and_hours(place_id: str) -> Optional[dict]:
    """Fetch phone and opening hours for a place (one Place Details call). Returns dict with phone, opening_hours_text."""
    if not settings.google_maps_api_key or not place_id:
        return None
    url = f"{PLACES_BASE}/details/json"
    params = {
        "place_id": place_id,
        "key": settings.google_maps_api_key,
        "fields": "formatted_phone_number,opening_hours",
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        result = data.get("result") or {}
        phone = result.get("formatted_phone_number")
        oh = result.get("opening_hours")
        hours_text = _format_opening_hours_short(oh) if oh else None
        open_now = oh.get("open_now") if oh else None
        return {"phone": phone, "opening_hours_text": hours_text, "open_now": open_now}
    except Exception as e:
        logger.debug("Place details failed for %s: %s", place_id[:20], e)
        return None


def get_nearby_places(
    lat: float,
    lon: float,
    keyword: str,
    type_filter: Optional[str] = None,
    open_now_only: bool = False,
    min_rating: Optional[float] = None,
) -> List[dict]:
    """
    Get nearby places with optional open_now and rating filter.
    At night (10 PM–7 AM), open_now_only is recommended for hospitals.
    When open_now_only is True, we pass opennow=1 to the API so Google returns only
    places that are open at query time (using Google Maps opening hours).
    """
    raw = _fetch_nearby(
        lat, lon, keyword,
        type_filter=type_filter,
        open_now=open_now_only,
    )
    if open_now_only:
        raw = [p for p in raw if p.get("open_now") is True]
    if min_rating is not None:
        raw = [p for p in raw if (p.get("rating") or 0) >= min_rating]
    # Sort by rating desc, then by name
    raw.sort(key=lambda p: (-(p.get("rating") or 0), p.get("name", "")))
    return raw


def get_emergency_services(lat: float, lon: float) -> dict:
    """
    Returns 112 number, nearby ambulances and hospitals with phone numbers when available.
    At night, only return hospitals that are open (open_now).
    """
    is_night = _is_night()
    ambulances = get_nearby_places(
        lat, lon, "ambulance", open_now_only=False, min_rating=3.0
    )
    hospitals = get_nearby_places(
        lat, lon, "hospital emergency",
        type_filter="hospital",
        open_now_only=is_night,
        min_rating=3.0,
    )

    def add_phones(places: List[dict], only_with_phone: bool = True, origin_lat: Optional[float] = None, origin_lon: Optional[float] = None) -> List[dict]:
        out = []
        for p in places[:15]:
            row = dict(p)
            if p.get("place_id"):
                details = _get_place_contact_and_hours(p["place_id"])
                if details:
                    row["phone"] = details.get("phone")
                    row["opening_hours_text"] = details.get("opening_hours_text")
                else:
                    row["phone"] = None
                    row["opening_hours_text"] = None
            else:
                row["phone"] = None
                row["opening_hours_text"] = None
            if origin_lat is not None and origin_lon is not None:
                _add_distance(row, origin_lat, origin_lon)
            if only_with_phone and not (row.get("phone") or "").strip():
                continue
            out.append(row)
        return out

    return {
        "emergency_number": "112",
        "ambulances": _sort_by_distance(add_phones(ambulances, origin_lat=lat, origin_lon=lon)),
        "hospitals": _sort_by_distance(add_phones(hospitals, origin_lat=lat, origin_lon=lon)),
    }


# Map internal specialty (from AI) to Google Places search keyword.
# Unknown specialties are used as-is with "doctor " prefix (e.g. doctor neurologist).
# Dentist/optometrist use bare keyword for better Places results.
DOCTOR_SPECIALTY_KEYWORDS = {
    "general_physician": "general practitioner",
    "pediatrician": "pediatrician",
    "dermatologist": "dermatologist",
    "cardiologist": "cardiologist",
    "gynecologist": "gynecologist",
    "orthopedic": "orthopedic",
    "psychiatrist": "psychiatrist",
    "clinic": "clinic",
    "neurologist": "neurologist",
    "dentist": "dentist",
    "ophthalmologist": "ophthalmologist",
    "ent": "ent specialist",
    "gastroenterologist": "gastroenterologist",
    "pulmonologist": "pulmonologist",
    "nephrologist": "nephrologist",
    "urologist": "urologist",
    "rheumatologist": "rheumatologist",
    "endocrinologist": "endocrinologist",
}

# Keywords to match in place name for specialty priority (name containing these → list first).
# Used to boost e.g. "Pediatric Clinic" when user asked for pediatrician.
DOCTOR_SPECIALTY_NAME_KEYWORDS: Dict[str, List[str]] = {
    "pediatrician": ["pediatric", "pediatrician", "children", "kids", "child"],
    "general_physician": ["general", "family", "gp", "primary care"],
    "dermatologist": ["dermatolog", "skin"],
    "cardiologist": ["cardio", "heart"],
    "gynecologist": ["gynecolog", "obstetric", "women", "maternity"],
    "orthopedic": ["orthopedic", "orthopaedic", "bone", "sport"],
    "psychiatrist": ["psychiatr", "mental health"],
    "neurologist": ["neuro"],
    "dentist": ["dental", "dentist", "teeth"],
    "ophthalmologist": ["ophthalmolog", "eye", "vision"],
    "ent": ["ent", "ear nose throat", "otolaryngolog"],
    "gastroenterologist": ["gastro", "digestive"],
    "pulmonologist": ["pulmonolog", "lung", "respiratory"],
    "nephrologist": ["nephrolog", "kidney"],
    "urologist": ["urolog"],
    "rheumatologist": ["rheumatolog"],
    "endocrinologist": ["endocrinolog", "diabetes", "thyroid"],
    "clinic": ["clinic"],
}


def _doctor_places_keyword(specialty: Optional[str]) -> str:
    if not specialty or not specialty.strip():
        return "doctor clinic"
    key = specialty.strip().lower()
    term = DOCTOR_SPECIALTY_KEYWORDS.get(key, key)
    # Dentist and similar: use bare term for Places; else "doctor {term}"
    if term in ("dentist",):
        return term
    return f"doctor {term}"


def _place_name_matches_specialty(place: dict, specialty: Optional[str]) -> bool:
    """True if place name contains any keyword for the given specialty (for list priority)."""
    if not specialty or not specialty.strip():
        return False
    key = specialty.strip().lower()
    keywords = DOCTOR_SPECIALTY_NAME_KEYWORDS.get(key)
    if not keywords:
        # Unknown specialty: check if the specialty term itself appears in the name
        keywords = [key]
    name = (place.get("name") or "").lower()
    return any(kw in name for kw in keywords)


def _sort_doctors_by_specialty_and_distance(
    places: List[dict], specialty: Optional[str] = None
) -> List[dict]:
    """Sort doctors: name-matching specialty first, then by distance (nearest first)."""
    def key(p: dict) -> tuple:
        matches = _place_name_matches_specialty(p, specialty)
        dist = p.get("distance_km")
        has_dist = dist is not None
        dist_val = dist if has_dist else 0.0
        # Matching first (False < True), then has_dist (False first), then distance
        return (not matches, not has_dist, dist_val)
    return sorted(places, key=key)


def get_nearby_doctors(
    lat: float,
    lon: float,
    specialty: Optional[str] = None,
) -> List[dict]:
    """Smart doctor/hospital routing. At night, prefer 24/7 (open_now)."""
    keyword = _doctor_places_keyword(specialty)
    return get_nearby_places(
        lat, lon, keyword,
        type_filter="doctor",
        open_now_only=_is_night(),
        min_rating=3.0,
    )[:50]


MIN_DOCTORS_IN_POPUP = 10
MAX_DOCTORS_POOL = 50
LOAD_MORE_PAGE_SIZE = 10


def get_doctors_with_phones(
    lat: float,
    lon: float,
    specialty: Optional[str] = None,
    skip: int = 0,
    limit: int = LOAD_MORE_PAGE_SIZE,
) -> tuple:
    """Nearby doctors for handoff popup. Returns (list_slice, has_more).
    Builds a pool (with_phone first, then no_phone to reach MIN_DOCTORS_IN_POPUP, cap at MAX_DOCTORS_POOL),
    then returns pool[skip:skip+limit]. has_more = (len(pool) > skip + limit).
    """
    raw = get_nearby_doctors(lat, lon, specialty=specialty)
    with_phone: List[dict] = []
    no_phone: List[dict] = []
    for p in raw:
        row = dict(p)
        if p.get("place_id"):
            details = _get_place_contact_and_hours(p["place_id"])
            if details:
                row["phone"] = details.get("phone")
                row["opening_hours_text"] = details.get("opening_hours_text")
                row["open_now"] = details.get("open_now")
            else:
                row["phone"] = None
                row["opening_hours_text"] = None
                row["open_now"] = None
        else:
            row["phone"] = None
            row["opening_hours_text"] = None
            row["open_now"] = None
        _add_distance(row, lat, lon)
        if (row.get("phone") or "").strip():
            with_phone.append(row)
        else:
            no_phone.append(row)
    with_phone = _sort_doctors_by_specialty_and_distance(with_phone, specialty)
    no_phone = _sort_doctors_by_specialty_and_distance(no_phone, specialty)
    pool: List[dict] = list(with_phone)
    while len(pool) < MIN_DOCTORS_IN_POPUP and no_phone:
        pool.append(no_phone.pop(0))
    pool = pool[:MAX_DOCTORS_POOL]
    slice_end = min(skip + limit, len(pool))
    return pool[skip:slice_end], (len(pool) > skip + limit)


def get_nearby_pharmacies(lat: float, lon: float) -> List[dict]:
    """Nearby pharmacies."""
    return get_nearby_places(
        lat, lon, "pharmacy",
        type_filter="pharmacy",
        open_now_only=False,
        min_rating=3.0,
    )[:15]


def get_pharmacies_with_phones(lat: float, lon: float) -> List[dict]:
    """Nearby pharmacies with phone numbers only (for handoff popup)."""
    raw = get_nearby_pharmacies(lat, lon)
    out = []
    for p in raw[:15]:
        row = dict(p)
        if p.get("place_id"):
            details = _get_place_contact_and_hours(p["place_id"])
            if details:
                row["phone"] = details.get("phone")
                row["opening_hours_text"] = details.get("opening_hours_text")
            else:
                row["phone"] = None
                row["opening_hours_text"] = None
        else:
            row["phone"] = None
            row["opening_hours_text"] = None
        _add_distance(row, lat, lon)
        if (row.get("phone") or "").strip():
            out.append(row)
    return _sort_by_distance(out)


def get_nearby_labs(lat: float, lon: float) -> List[dict]:
    """Nearby diagnostic/lab centers. At night, open only."""
    return get_nearby_places(
        lat, lon, "diagnostic lab pathology",
        open_now_only=_is_night(),
        min_rating=3.0,
    )[:15]


def get_labs_with_phones(lat: float, lon: float) -> List[dict]:
    """Nearby labs with phone numbers only (for handoff popup)."""
    raw = get_nearby_labs(lat, lon)
    out = []
    for p in raw[:15]:
        row = dict(p)
        if p.get("place_id"):
            details = _get_place_contact_and_hours(p["place_id"])
            if details:
                row["phone"] = details.get("phone")
                row["opening_hours_text"] = details.get("opening_hours_text")
            else:
                row["phone"] = None
                row["opening_hours_text"] = None
        else:
            row["phone"] = None
            row["opening_hours_text"] = None
        _add_distance(row, lat, lon)
        if (row.get("phone") or "").strip():
            out.append(row)
    return _sort_by_distance(out)


# Mental health: psychologist, psychiatrist, counselor (for Places keyword)
MENTAL_HEALTH_SPECIALTY_KEYWORDS = {
    "psychiatrist": "psychiatrist",
    "psychologist": "psychologist",
    "counselor": "counselor",
    "therapist": "therapist",
}


def get_nearby_mental_health(lat: float, lon: float, specialty: Optional[str] = None) -> List[dict]:
    """Nearby mental health professionals (psychologist, psychiatrist, counselor)."""
    if specialty and specialty.strip().lower() in MENTAL_HEALTH_SPECIALTY_KEYWORDS:
        keyword = MENTAL_HEALTH_SPECIALTY_KEYWORDS[specialty.strip().lower()]
    else:
        keyword = "psychologist psychiatrist counselor"
    return get_nearby_places(
        lat, lon, keyword,
        type_filter=None,
        open_now_only=False,
        min_rating=3.0,
    )[:15]


def get_mental_health_with_phones(lat: float, lon: float, specialty: Optional[str] = None) -> List[dict]:
    """Nearby mental health professionals with phone numbers only (for handoff popup)."""
    raw = get_nearby_mental_health(lat, lon, specialty=specialty)
    out = []
    for p in raw[:15]:
        row = dict(p)
        if p.get("place_id"):
            details = _get_place_contact_and_hours(p["place_id"])
            if details:
                row["phone"] = details.get("phone")
                row["opening_hours_text"] = details.get("opening_hours_text")
            else:
                row["phone"] = None
                row["opening_hours_text"] = None
        else:
            row["phone"] = None
            row["opening_hours_text"] = None
        _add_distance(row, lat, lon)
        if (row.get("phone") or "").strip():
            out.append(row)
    return _sort_by_distance(out)
