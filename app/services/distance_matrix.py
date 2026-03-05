"""
Google Distance Matrix API: origin → destinations → driving distance and duration.
Used to add distance/duration to Places results (doctors, pharmacy, labs).
"""
import logging
from typing import List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Max destinations per request (Google limit)
MAX_DESTINATIONS = 25


def get_distances(
    origin_lat: float,
    origin_lng: float,
    destinations: List[Tuple[float, float]],
) -> List[Optional[dict]]:
    """
    Call Distance Matrix API: origin → each destination.
    Returns list aligned with destinations: each item is
    {"distance_m": int, "distance_text": str, "duration_s": int, "duration_text": str} or None on error.
    """
    if not destinations:
        return []
    key = getattr(settings, "google_maps_api_key", None) or None
    if not key:
        return [None] * len(destinations)

    results: List[Optional[dict]] = []
    for start in range(0, len(destinations), MAX_DESTINATIONS):
        batch = destinations[start : start + MAX_DESTINATIONS]
        dest_str = "|".join(f"{lat},{lng}" for lat, lng in batch)
        url = (
            "https://maps.googleapis.com/maps/api/distancematrix/json"
            f"?origins={origin_lat},{origin_lng}"
            f"&destinations={dest_str}"
            "&units=metric"
            f"&key={key}"
        )
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.get(url)
            if r.status_code != 200:
                logger.warning("Distance Matrix HTTP %s: %s", r.status_code, r.text[:200])
                results.extend([None] * len(batch))
                continue
            data = r.json()
            if data.get("status") != "OK":
                logger.warning("Distance Matrix status %s: %s", data.get("status"), data.get("error_message"))
                results.extend([None] * len(batch))
                continue
            rows = data.get("rows") or []
            if not rows:
                results.extend([None] * len(batch))
                continue
            elements = rows[0].get("elements") or []
            for el in elements:
                if el.get("status") != "OK":
                    results.append(None)
                    continue
                dist = el.get("distance") or {}
                dur = el.get("duration") or {}
                results.append({
                    "distance_m": dist.get("value"),
                    "distance_text": dist.get("text"),
                    "duration_s": dur.get("value"),
                    "duration_text": dur.get("text"),
                })
            # Pad if API returned fewer elements than batch size
            while len(results) < start + len(batch):
                results.append(None)
        except Exception as e:
            logger.exception("Distance Matrix request failed: %s", e)
            results.extend([None] * len(batch))

    return results[: len(destinations)]
