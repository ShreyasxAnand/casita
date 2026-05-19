"""Address geocoding via the ArcGIS World GeocodeServer."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from app.services.arcgis import fetch_json

ARCGIS_GEOCODER_URL = (
    "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/"
    "findAddressCandidates"
)

# Conservative bounding box used to reject geocoder hits that are obviously
# outside San Jose city limits (e.g. Sunnyvale, Milpitas).
SAN_JOSE_BBOX = {
    "west": -122.08,
    "south": 37.10,
    "east": -121.55,
    "north": 37.50,
}


def _inside_san_jose_bbox(lon: float, lat: float) -> bool:
    return (
        SAN_JOSE_BBOX["west"] <= lon <= SAN_JOSE_BBOX["east"]
        and SAN_JOSE_BBOX["south"] <= lat <= SAN_JOSE_BBOX["north"]
    )


def normalize_address(address: str) -> str:
    """Ensure the address ends with ', San Jose, CA' for the geocoder."""
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
) -> dict[str, Any]:
    """Resolve a typed address to a single San Jose candidate."""
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
        lon = float(location.get("x", 0.0))
        lat = float(location.get("y", 0.0))
        attrs = candidate.get("attributes") or {}
        city = str(attrs.get("City") or "").lower()
        region = str(attrs.get("Region") or "").lower()
        if _inside_san_jose_bbox(lon, lat) and (
            not city or "san jose" in city or "ca" in region or "california" in region
        ):
            return {
                "input": address,
                "normalized": normalized,
                "matched_address": candidate.get("address") or normalized,
                "latitude": lat,
                "longitude": lon,
                "score": candidate.get("score"),
                "attributes": attrs,
            }

    raise HTTPException(
        404,
        "Could not geocode that to a San Jose address. Try a complete "
        "street address inside San Jose city limits.",
    )
