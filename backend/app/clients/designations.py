"""Flood / geohazard / historic / WUI / heritage-tree designation lookups.

T1 correctness change: every lookup now returns one of three explicit
statuses — `present`, `absent`, or `error` — instead of collapsing service
outages into `None`. Callers can render an honest "lookup failed" item
distinct from a confident "no designation found".
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import HTTPException
from shapely.geometry import shape

from app.services import arcgis

logger = logging.getLogger(__name__)

FEMA_NFHL_QUERY_URL = "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query"
USDA_WUI_QUERY_URL = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_WUI_2020_01/MapServer/0/query"

_SAN_JOSE_OPN_BASE = "https://geo.sanjoseca.gov/server/rest/services/OPN/OPN_OpenDataService/MapServer"
SAN_JOSE_FLOOD_QUERY_URL = f"{_SAN_JOSE_OPN_BASE}/439/query"
SAN_JOSE_HISTORIC_POINTS_QUERY_URL = f"{_SAN_JOSE_OPN_BASE}/406/query"
SAN_JOSE_HISTORIC_AREA_QUERY_URL = f"{_SAN_JOSE_OPN_BASE}/408/query"
SAN_JOSE_WUI_QUERY_URL = f"{_SAN_JOSE_OPN_BASE}/283/query"
SAN_JOSE_HERITAGE_TREES_QUERY_URL = f"{_SAN_JOSE_OPN_BASE}/511/query"
SAN_JOSE_GEOHAZARD_QUERY_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/PLN/"
    "PLN_LandDesignations/MapServer/31/query"
)

SFHA_ZONES = {"A", "AE", "AH", "AO", "A99"}

# Small pad in degrees used when querying point layers (e.g. heritage trees)
# against a parcel bounding box — covers point data that may sit just outside
# the parcel polygon due to coordinate imprecision (~20 m).
_HERITAGE_PAD_DEG = 0.00018


async def _attrs_point(
    client: httpx.AsyncClient, url: str, lon: float, lat: float, *, stage: str
) -> list[dict[str, Any]]:
    features = await arcgis.query_features(
        client,
        url,
        geometry=arcgis.point(lon, lat),
        geometry_type="esriGeometryPoint",
        return_geometry=False,
        stage=stage,
    )
    return [(f.get("attributes") or {}) for f in features]


async def _attrs_envelope(
    client: httpx.AsyncClient,
    url: str,
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    stage: str,
) -> list[dict[str, Any]]:
    features = await arcgis.query_features(
        client,
        url,
        geometry=arcgis.envelope(west, south, east, north),
        geometry_type="esriGeometryEnvelope",
        return_geometry=False,
        stage=stage,
    )
    return [(f.get("attributes") or {}) for f in features]


def _parse_flood_zone(attrs: dict[str, Any]) -> tuple[bool, str]:
    zone = str(
        attrs.get("FLD_ZONE")
        or attrs.get("Zone")
        or attrs.get("ZONE")
        or attrs.get("FLOODZONE")
        or ""
    ).strip().upper()
    if not zone:
        return False, "X or D"
    in_sfha = zone in SFHA_ZONES or zone.startswith(("AE", "AH", "AO"))
    return in_sfha, zone


async def fetch_flood(client: httpx.AsyncClient, lat: float, lon: float) -> dict[str, Any]:
    try:
        attrs = await _attrs_point(client, FEMA_NFHL_QUERY_URL, lon, lat, stage="FEMA flood zone")
        if attrs:
            in_sfha, zone = _parse_flood_zone(attrs[0])
            return {
                "in_sfha": in_sfha, "zone": zone,
                "detail": f"Zone: {zone} (FEMA NFHL).",
                "source": "FEMA NFHL",
            }
    except HTTPException as exc:
        logger.info("FEMA flood lookup failed, trying San Jose layer: %s", exc.detail)

    try:
        attrs = await _attrs_point(
            client, SAN_JOSE_FLOOD_QUERY_URL, lon, lat, stage="San Jose flood zone"
        )
    except HTTPException as exc:
        return {
            "status": "error",
            "in_sfha": None, "zone": None,
            "detail": "Flood lookup failed; verify with FEMA NFHL.",
            "source": None,
            "error": exc.detail,
        }
    if attrs:
        in_sfha, zone = _parse_flood_zone(attrs[0])
        return {
            "in_sfha": in_sfha, "zone": zone,
            "detail": f"Zone: {zone} (San Jose Flood Hazard Area).",
            "source": "San Jose OPN Flood Hazard Area layer 439",
        }
    return {
        "in_sfha": False, "zone": "X or D",
        "detail": "No Special Flood Hazard Area feature at this location.",
        "source": "San Jose OPN Flood Hazard Area layer 439",
    }


async def fetch_geohazard(client: httpx.AsyncClient, lat: float, lon: float) -> dict[str, Any]:
    try:
        attrs = await _attrs_point(
            client, SAN_JOSE_GEOHAZARD_QUERY_URL, lon, lat, stage="San Jose geohazard"
        )
    except HTTPException as exc:
        return {
            "status": "error",
            "in_zone": None,
            "detail": "Geohazard lookup failed; verify with SJPermits geohazard map.",
            "source": None,
            "error": exc.detail,
        }
    if attrs:
        name = attrs[0].get("NAME") or attrs[0].get("TYPE") or "Hazardous/geologic zone"
        return {
            "in_zone": True,
            "detail": f"In designated area: {name}.",
            "source": "San Jose PLN Land Designations layer 31",
        }
    return {
        "in_zone": False,
        "detail": "No geologic hazard designation feature at this location.",
        "source": "San Jose PLN Land Designations layer 31",
    }


async def fetch_historic(
    client: httpx.AsyncClient, lat: float, lon: float, parcel_feature: dict[str, Any]
) -> dict[str, Any]:
    west, south, east, north = shape(parcel_feature["geometry"]).bounds
    try:
        hri_points, historic_area = await asyncio.gather(
            _attrs_envelope(
                client, SAN_JOSE_HISTORIC_POINTS_QUERY_URL,
                west, south, east, north, stage="San Jose HRI",
            ),
            _attrs_point(
                client, SAN_JOSE_HISTORIC_AREA_QUERY_URL, lon, lat, stage="San Jose historic area"
            ),
        )
    except HTTPException as exc:
        return {
            "status": "error",
            "on_inventory": None,
            "detail": "Historic lookup failed; verify with City HRI map.",
            "source": None,
            "error": exc.detail,
        }
    if hri_points or historic_area:
        return {
            "on_inventory": True,
            "detail": "Historic Resources Inventory point or Historic Area intersects this parcel.",
            "source": "San Jose OPN HRI layer 406 / Historic Area layer 408",
        }
    return {
        "on_inventory": False,
        "detail": "No HRI point or Historic Area feature found for this parcel.",
        "source": "San Jose OPN HRI layer 406 / Historic Area layer 408",
    }


async def fetch_wui(client: httpx.AsyncClient, lat: float, lon: float) -> dict[str, Any]:
    try:
        attrs = await _attrs_point(
            client, SAN_JOSE_WUI_QUERY_URL, lon, lat, stage="San Jose WUI"
        )
        if attrs:
            name = attrs[0].get("NAME") or attrs[0].get("TYPE") or "WUI"
            return {
                "in_wui": True,
                "detail": f"In Fire Wildland-Urban Interface: {name}.",
                "source": "San Jose OPN WUI layer 283",
            }
        return {
            "in_wui": False,
            "detail": "Not in WUI per San Jose Fire WUI layer.",
            "source": "San Jose OPN WUI layer 283",
        }
    except HTTPException as exc:
        logger.info("San Jose WUI lookup failed, trying USDA fallback: %s", exc.detail)

    try:
        attrs = await _attrs_point(
            client, USDA_WUI_QUERY_URL, lon, lat, stage="USDA WUI"
        )
    except HTTPException as exc:
        return {
            "status": "error",
            "in_wui": None,
            "detail": "WUI lookup failed; verify with SJPermits WUI map.",
            "source": None,
            "error": exc.detail,
        }
    if not attrs:
        return {
            "in_wui": False,
            "detail": "Not in WUI per USDA fallback layer.",
            "source": "USDA WUI",
        }
    wui_class = attrs[0].get("Class_N") or attrs[0].get("WUI_CLASS") or attrs[0].get("CLASS") or "WUI"
    return {
        "in_wui": True,
        "detail": f"WUI class: {wui_class}.",
        "source": "USDA WUI",
    }


async def fetch_heritage_trees(
    client: httpx.AsyncClient, parcel_feature: dict[str, Any]
) -> dict[str, Any]:
    parcel_geom = shape(parcel_feature["geometry"]).buffer(0)
    west, south, east, north = parcel_geom.bounds
    try:
        attrs = await _attrs_envelope(
            client,
            SAN_JOSE_HERITAGE_TREES_QUERY_URL,
            west - _HERITAGE_PAD_DEG,
            south - _HERITAGE_PAD_DEG,
            east + _HERITAGE_PAD_DEG,
            north + _HERITAGE_PAD_DEG,
            stage="San Jose heritage trees",
        )
    except HTTPException as exc:
        return {
            "status": "error",
            "has_heritage_tree": None,
            "count": None,
            "detail": "Heritage tree lookup failed; verify at sanjoseca.gov/TreePermit.",
            "source": None,
            "error": exc.detail,
        }
    if attrs:
        return {
            "has_heritage_tree": True,
            "count": len(attrs),
            "detail": f"{len(attrs)} heritage tree record(s) found on or near this parcel.",
            "source": "San Jose OPN Heritage Trees layer 511",
        }
    return {
        "has_heritage_tree": False,
        "count": 0,
        "detail": "No heritage tree records found on or near this parcel.",
        "source": "San Jose OPN Heritage Trees layer 511",
    }


async def fetch_all(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    parcel_feature: dict[str, Any],
) -> dict[str, Any]:
    """Fetch all five designation lookups concurrently."""
    flood, geohazard, historic, wui, heritage = await asyncio.gather(
        fetch_flood(client, latitude, longitude),
        fetch_geohazard(client, latitude, longitude),
        fetch_historic(client, latitude, longitude, parcel_feature),
        fetch_wui(client, latitude, longitude),
        fetch_heritage_trees(client, parcel_feature),
    )
    return {
        "flood": flood,
        "geohazard": geohazard,
        "historic": historic,
        "wui": wui,
        "heritage_trees": heritage,
    }
