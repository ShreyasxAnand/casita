"""Flood / geohazard / historic / WUI / heritage-tree designation lookups.

Every lookup returns FetchResult[DesignationData] with three honest states:
  OK     — service responded; present=True/False reflects the actual designation
  ABSENT — service responded, no feature at this location (not designated)
  FAILED — service error; we have no information
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException
from shapely.geometry import shape

from app.result import FetchResult
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

_HERITAGE_PAD_DEG = 0.00018


@dataclass(frozen=True)
class DesignationData:
    present: bool
    detail: str


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


async def fetch_flood(
    client: httpx.AsyncClient, lat: float, lon: float
) -> FetchResult[DesignationData]:
    _SRC_FEMA = "FEMA NFHL"
    _SRC_SJ = "San Jose OPN Flood Hazard Area layer 439"

    try:
        attrs = await _attrs_point(client, FEMA_NFHL_QUERY_URL, lon, lat, stage="FEMA flood zone")
        if attrs:
            in_sfha, zone = _parse_flood_zone(attrs[0])
            return FetchResult.ok(
                DesignationData(present=in_sfha, detail=f"Zone: {zone} (FEMA NFHL)."),
                _SRC_FEMA,
            )
    except HTTPException as exc:
        logger.info("FEMA flood lookup failed, trying San Jose layer: %s", exc.detail)

    try:
        attrs = await _attrs_point(
            client, SAN_JOSE_FLOOD_QUERY_URL, lon, lat, stage="San Jose flood zone"
        )
    except HTTPException as exc:
        return FetchResult.failed(exc.detail, _SRC_SJ)

    if attrs:
        in_sfha, zone = _parse_flood_zone(attrs[0])
        return FetchResult.ok(
            DesignationData(present=in_sfha, detail=f"Zone: {zone} (San Jose Flood Hazard Area)."),
            _SRC_SJ,
        )
    return FetchResult.absent(_SRC_SJ)


async def fetch_geohazard(
    client: httpx.AsyncClient, lat: float, lon: float
) -> FetchResult[DesignationData]:
    _SRC = "San Jose PLN Land Designations layer 31"
    try:
        attrs = await _attrs_point(
            client, SAN_JOSE_GEOHAZARD_QUERY_URL, lon, lat, stage="San Jose geohazard"
        )
    except HTTPException as exc:
        return FetchResult.failed(exc.detail, _SRC)

    if attrs:
        name = attrs[0].get("NAME") or attrs[0].get("TYPE") or "Hazardous/geologic zone"
        return FetchResult.ok(
            DesignationData(present=True, detail=f"In designated area: {name}."),
            _SRC,
        )
    return FetchResult.absent(_SRC)


async def fetch_historic(
    client: httpx.AsyncClient, lat: float, lon: float, parcel_feature: dict[str, Any]
) -> FetchResult[DesignationData]:
    _SRC = "San Jose OPN HRI layer 406 / Historic Area layer 408"
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
        return FetchResult.failed(exc.detail, _SRC)

    if hri_points or historic_area:
        return FetchResult.ok(
            DesignationData(
                present=True,
                detail="Historic Resources Inventory point or Historic Area intersects this parcel.",
            ),
            _SRC,
        )
    return FetchResult.absent(_SRC)


async def fetch_wui(
    client: httpx.AsyncClient, lat: float, lon: float
) -> FetchResult[DesignationData]:
    _SRC_SJ = "San Jose OPN WUI layer 283"
    _SRC_USDA = "USDA WUI"

    try:
        attrs = await _attrs_point(client, SAN_JOSE_WUI_QUERY_URL, lon, lat, stage="San Jose WUI")
        if attrs:
            name = attrs[0].get("NAME") or attrs[0].get("TYPE") or "WUI"
            return FetchResult.ok(
                DesignationData(present=True, detail=f"In Fire Wildland-Urban Interface: {name}."),
                _SRC_SJ,
            )
        return FetchResult.absent(_SRC_SJ)
    except HTTPException as exc:
        logger.info("San Jose WUI lookup failed, trying USDA fallback: %s", exc.detail)

    try:
        attrs = await _attrs_point(client, USDA_WUI_QUERY_URL, lon, lat, stage="USDA WUI")
    except HTTPException as exc:
        return FetchResult.failed(exc.detail, _SRC_USDA)

    if not attrs:
        return FetchResult.absent(_SRC_USDA)
    wui_class = (
        attrs[0].get("Class_N") or attrs[0].get("WUI_CLASS") or attrs[0].get("CLASS") or "WUI"
    )
    return FetchResult.ok(
        DesignationData(present=True, detail=f"WUI class: {wui_class}."),
        _SRC_USDA,
    )


async def fetch_heritage_trees(
    client: httpx.AsyncClient, parcel_feature: dict[str, Any]
) -> FetchResult[DesignationData]:
    _SRC = "San Jose OPN Heritage Trees layer 511"
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
        return FetchResult.failed(exc.detail, _SRC)

    if attrs:
        return FetchResult.ok(
            DesignationData(
                present=True,
                detail=f"{len(attrs)} heritage tree record(s) found on or near this parcel.",
            ),
            _SRC,
        )
    return FetchResult.absent(_SRC)


async def fetch_all(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    parcel_feature: dict[str, Any],
) -> dict[str, FetchResult[DesignationData]]:
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
