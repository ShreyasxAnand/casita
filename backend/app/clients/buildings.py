"""Building-outline lookup for a parcel envelope.

T1 correctness change: when no real building outline is found, the legacy
`site_model.build_site_model` used to fabricate a 5.5 × 7 m box at the
parcel centroid and present it as the "existing house". That made downstream
setback math, rear-yard coverage, and the buildable-zone overlay look
plausible while being entirely fictional.

This module instead returns an empty FeatureCollection plus an explicit
`not_found` source. `site_model.build_site_model` skips building-derived
geometry in that case and the frontend can surface a "no building data"
empty state.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException
from shapely.errors import GEOSException
from shapely.geometry import mapping, shape

from app.clients.arcgis_geometry import feature_to_geojson
from app.services import arcgis

logger = logging.getLogger(__name__)

SAN_JOSE_BUILDINGS_QUERY_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/DPW/"
    "DPW_BasemapServiceWGS/MapServer/21/query"
)
SCC_BUILDINGS_QUERY_URL = (
    "https://mapservices.sccgov.org/arcgis/rest/services/basic/"
    "SCCBuildings/MapServer/0/query"
)


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


async def _query_layer(
    client: httpx.AsyncClient, url: str, west: float, south: float, east: float, north: float
) -> list[dict[str, Any]]:
    return await arcgis.query_features(
        client,
        url,
        geometry=arcgis.envelope(west, south, east, north),
        geometry_type="esriGeometryEnvelope",
        max_records=50,
        stage="Building outlines",
    )


async def fetch_buildings_for_parcel(
    client: httpx.AsyncClient,
    parcel_feature: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Return building outlines that intersect the parcel, plus a source tag.

    Source tag is one of:
      - `san_jose_dpw`: primary layer succeeded with >=1 intersecting building.
      - `scc_fallback`: primary failed; SCC LiDAR-derived layer was used.
      - `not_found`: both layers returned no features intersecting the parcel.
    """
    parcel_geom = shape(parcel_feature["geometry"]).buffer(0)
    west, south, east, north = parcel_geom.bounds

    primary_source = "san_jose_dpw"
    try:
        raw = await _query_layer(client, SAN_JOSE_BUILDINGS_QUERY_URL, west, south, east, north)
    except HTTPException as exc:
        logger.warning("San Jose DPW building layer failed: %s", exc.detail)
        raw = []
        primary_source = "scc_fallback"

    if not raw and primary_source == "scc_fallback":
        try:
            raw = await _query_layer(client, SCC_BUILDINGS_QUERY_URL, west, south, east, north)
        except HTTPException as exc:
            logger.warning("SCC building layer failed: %s", exc.detail)
            raw = []

    features: list[dict[str, Any]] = []
    for raw_feature in raw:
        feature = feature_to_geojson(raw_feature)
        if not feature:
            continue
        try:
            building_geom = shape(feature["geometry"]).buffer(0)
        except (GEOSException, ValueError) as exc:
            logger.debug("Skipping malformed building geometry: %s", exc)
            continue
        if building_geom.is_empty or not building_geom.intersects(parcel_geom):
            continue
        clipped = building_geom.intersection(parcel_geom).buffer(0)
        feature["geometry"] = mapping(clipped)
        features.append(feature)

    if not features:
        return _feature_collection([]), "not_found"
    return _feature_collection(features), primary_source
