"""Address geocoding via the ArcGIS World GeocodeServer."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import HTTPException

from app.services.arcgis import fetch_json

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


@dataclass(frozen=True)
class GeocodeResult:
    matched_address: str
    latitude:        float
    longitude:       float
    score:           float
    normalized_input: str
    zip_code:        str
    city:            str
    state:           str


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
        lon = float(location.get("x") or 0.0)
        lat = float(location.get("y") or 0.0)

        if not _inside_bbox(lon, lat):
            continue

        attrs  = candidate.get("attributes") or {}
        city   = str(attrs.get("City")   or "").strip()
        region = str(attrs.get("Region") or "").strip().upper()

        if city and "san jose" not in city.lower() and region not in ("CA", "CALIFORNIA"):
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
