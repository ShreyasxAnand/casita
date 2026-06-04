"""Thin async wrappers around ArcGIS REST query/export endpoints.

This module consolidates the four near-duplicate `_query_arcgis_*` helpers
that used to live in `main.py` into a single parameterised entry point,
and hoists the `pyproj` transformers to module level so they are built once
per process instead of once per request.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx
from fastapi import HTTPException
from pyproj import Transformer

logger = logging.getLogger(__name__)

# San Jose sits in UTM zone 10N. Module-level transformers are reused across
# every request — building them is non-trivial and they are stateless.
UTM_EPSG = 26910
TO_UTM = Transformer.from_crs("EPSG:4326", f"EPSG:{UTM_EPSG}", always_xy=True).transform
TO_WGS84 = Transformer.from_crs(f"EPSG:{UTM_EPSG}", "EPSG:4326", always_xy=True).transform
TO_WEBMERC = Transformer.from_crs(f"EPSG:{UTM_EPSG}", "EPSG:3857", always_xy=True).transform
FROM_WEBMERC = Transformer.from_crs("EPSG:3857", f"EPSG:{UTM_EPSG}", always_xy=True).transform


GeometryType = Literal["esriGeometryPoint", "esriGeometryEnvelope"]


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
    *,
    stage: str,
) -> dict[str, Any]:
    """GET an ArcGIS REST endpoint and return parsed JSON.

    Raises HTTPException(502) on transport, parse, or server-side errors so
    callers can decide whether the failure is fatal or recoverable.
    """
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"{stage} request failed: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(502, f"{stage} returned invalid JSON.") from exc

    if data.get("error"):
        message = data["error"].get("message") or data["error"]
        raise HTTPException(502, f"{stage} error: {message}")
    return data


async def query_features(
    client: httpx.AsyncClient,
    url: str,
    *,
    geometry: str,
    geometry_type: GeometryType,
    where: str = "1=1",
    out_fields: str = "*",
    return_geometry: bool = True,
    max_records: int = 100,
    result_offset: int | None = None,
    order_by_fields: str | None = None,
    stage: str = "ArcGIS query",
) -> list[dict[str, Any]]:
    """Query an ArcGIS MapServer/FeatureServer layer with a consistent shape.

    Replaces the four `_query_arcgis_point` / `_query_arcgis_envelope` /
    `_query_arcgis_attrs_*` helpers from the original `main.py`.
    """
    params: dict[str, Any] = {
        "where": where,
        "geometry": geometry,
        "geometryType": geometry_type,
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "true" if return_geometry else "false",
        "f": "json",
    }
    if return_geometry:
        params["outSR"] = "4326"
    if max_records:
        params["resultRecordCount"] = str(max_records)
    if result_offset is not None:
        params["resultOffset"] = str(result_offset)
    if order_by_fields:
        params["orderByFields"] = order_by_fields

    data = await fetch_json(client, url, params, stage=stage)
    return data.get("features") or []


def point(lon: float, lat: float) -> str:
    """Format a longitude/latitude pair as an ArcGIS point geometry string."""
    return f"{lon},{lat}"


def envelope(west: float, south: float, east: float, north: float) -> str:
    """Format four corners as an ArcGIS envelope geometry string."""
    return f"{west},{south},{east},{north}"
