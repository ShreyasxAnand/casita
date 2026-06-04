"""Address geocoding via the ArcGIS World GeocodeServer."""

from __future__ import annotations

import logging

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

from app.cities.base import GeocodeResult
from app.services.arcgis import fetch_json

__all__ = [
    "GEOCODE_MIN_SCORE",
    "GeocodeResult",
    "geocode_san_jose_address",
    "geocode_zip_extent",
    "normalize_address",
]

ARCGIS_GEOCODER_URL = (
    "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/"
    "findAddressCandidates"
)

# Below this score we refuse to proceed — a bad geocode poisons every
# downstream calculation silently. 85 rejects fuzzy/partial matches while
# accepting clean street-level hits.
GEOCODE_MIN_SCORE = 85.0

# Conservative bbox: rejects candidates that are clearly outside San Jose
# (Sunnyvale, Milpitas, etc.).
_SAN_JOSE_BBOX = {
    "west": -122.08, "south": 37.10,
    "east": -121.55, "north": 37.50,
}


def _inside_bbox(lon: float, lat: float) -> bool:
    return (
        _SAN_JOSE_BBOX["west"] <= lon <= _SAN_JOSE_BBOX["east"]
        and _SAN_JOSE_BBOX["south"] <= lat <= _SAN_JOSE_BBOX["north"]
    )


def normalize_address(address: str) -> str:
    value = " ".join((address or "").strip().split())
    if not value:
        raise HTTPException(422, "Type a San Jose address.")
    lower = value.lower()
    if "san jose" not in lower:
        value = f"{value}, San Jose, CA"
    elif " ca" not in lower and "california" not in lower:
        value = f"{value}, CA"
    return value


async def geocode_zip_extent(
    client: httpx.AsyncClient,
    zip_code: str,
) -> dict[str, float | str]:
    """Resolve a 5-digit ZIP to its bounding extent and centre.

    Returns ``{zip, center_lat, center_lon, west, south, east, north}``.
    Raises 422 for a malformed ZIP and 404 for a ZIP whose centroid does not
    fall inside San Jose bounds (the parcel service only covers San Jose).
    """
    zip_clean = (zip_code or "").strip()
    if not (len(zip_clean) == 5 and zip_clean.isdigit()):
        raise HTTPException(422, "Enter a valid 5-digit ZIP code.")

    data = await fetch_json(
        client,
        ARCGIS_GEOCODER_URL,
        {
            "Postal": zip_clean,
            "Region": "CA",
            "f": "json",
            "outFields": "Postal,City,Region",
            "maxLocations": 5,
            "sourceCountry": "USA",
        },
        stage="geocoder_zip",
    )

    candidates = data.get("candidates") or []
    if not candidates:
        raise HTTPException(404, f"Could not locate ZIP {zip_clean}.")

    selected = None
    for candidate in candidates:
        attrs = candidate.get("attributes") or {}
        postal = str(attrs.get("Postal") or "").strip()
        region = str(attrs.get("Region") or "").strip().upper()
        location = candidate.get("location") or {}
        cx, cy = location.get("x"), location.get("y")
        extent = candidate.get("extent") or {}
        if cx is None or cy is None or not extent:
            continue
        if postal and postal != zip_clean:
            continue
        if region and region not in ("CA", "CALIFORNIA"):
            continue
        if _inside_bbox(float(cx), float(cy)):
            selected = candidate
            break

    if selected is None:
        raise HTTPException(
            404,
            f"ZIP {zip_clean} is outside San Jose coverage. "
            "This heatmap currently scores San Jose parcels only.",
        )

    location = selected["location"]
    extent = selected["extent"]
    cx, cy = location["x"], location["y"]
    center_lon, center_lat = float(cx), float(cy)

    return {
        "zip": zip_clean,
        "center_lat": center_lat,
        "center_lon": center_lon,
        "west": float(extent["xmin"]),
        "south": float(extent["ymin"]),
        "east": float(extent["xmax"]),
        "north": float(extent["ymax"]),
    }


async def geocode_san_jose_address(
    client: httpx.AsyncClient,
    address: str,
) -> GeocodeResult:
    """Resolve a typed address to a single verified San Jose candidate.

    Raises 422 if the best match scores below GEOCODE_MIN_SCORE — the
    caller gets the matched address and score so they can correct the input.
    Raises 404 if no candidate lands inside San Jose bounds.
    """
    normalized = normalize_address(address)
    data = await fetch_json(
        client,
        ARCGIS_GEOCODER_URL,
        {
            "SingleLine": normalized,
            "f": "json",
            "outFields": "Match_addr,Addr_type,City,Region,Postal,Country",
            "maxLocations": 5,
            "sourceCountry": "USA",
        },
        stage="geocoder",
    )

    for candidate in data.get("candidates") or []:
        location = candidate.get("location") or {}
        x = location.get("x")
        y = location.get("y")
        if x is None or y is None:
            logger.warning(
                "Geocode candidate missing coordinates, skipping: %s",
                candidate.get("address"),
            )
            continue
        lon = float(x)
        lat = float(y)

        if not _inside_bbox(lon, lat):
            continue

        attrs  = candidate.get("attributes") or {}
        city   = str(attrs.get("City")   or "").strip()
        region = str(attrs.get("Region") or "").strip().upper()

        if city and "san jose" not in city.lower():
            continue
        if region and region not in ("CA", "CALIFORNIA"):
            continue

        score = float(candidate.get("score") or 0.0)
        matched = candidate.get("address") or normalized

        if score < GEOCODE_MIN_SCORE:
            raise HTTPException(
                422,
                f"Low-confidence geocode match: '{matched}' scored {score:.0f}/100 "
                f"(minimum {GEOCODE_MIN_SCORE:.0f}). Provide a more specific address.",
            )

        return GeocodeResult(
            matched_address=matched,
            latitude=lat,
            longitude=lon,
            score=score,
            normalized_input=normalized,
            zip_code=str(attrs.get("Postal") or "").strip(),
            city=city or "San Jose",
            state=region or "CA",
        )

    raise HTTPException(
        404,
        "Could not geocode that to a San Jose address. "
        "Try a complete street address inside San Jose city limits.",
    )
