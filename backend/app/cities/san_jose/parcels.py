"""San Jose parcel lookup at a geographic point.

T1 correctness change: the legacy `_fetch_parcel_at_point` used to return
the *nearest* parcel when the geocoded point fell on a street centerline
(`nearby_nearest`). That silently produced wrong-parcel results for any
address whose centroid landed in the right-of-way. This module returns a
match only when the point is actually contained in (or directly intersects)
a parcel polygon; otherwise it raises a 404 with the candidate count.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException
from shapely.errors import GEOSException
from shapely.geometry import Point, shape

from app.services import arcgis
from app.services.arcgis_geometry import feature_to_geojson

logger = logging.getLogger(__name__)

SAN_JOSE_PARCELS_QUERY_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/OPN/"
    "OPN_OpenDataService/MapServer/270/query"
)

# Small envelope used to widen the parcel search when the geocoded point
# lands on the street centerline rather than inside the parcel polygon.
# Approximately 50 m east-west / 40 m north-south at San Jose latitude — wide
# enough to cover sidewalks and front yards but not so wide that a single
# query matches an entire block.
_CENTERLINE_PAD_LON = 0.00045
_CENTERLINE_PAD_LAT = 0.00035


def _covers(feature: dict[str, Any], point: Point) -> bool:
    try:
        return shape(feature["geometry"]).covers(point)
    except (GEOSException, ValueError, KeyError) as exc:
        logger.debug("Parcel containment check failed: %s", exc)
        return False


async def fetch_parcel_at_point(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
) -> tuple[dict[str, Any], str]:
    """Return the parcel whose polygon covers `(longitude, latitude)`.

    Match strategy (in order):
      1. Point-in-polygon over features returned by an ArcGIS point query.
      2. Point-in-polygon over features returned by a small envelope query
         around the point (the geocoded centroid often falls on the street).

    Raises HTTPException(404) when no parcel actually contains the point.
    No "nearest-parcel" fallback — see module docstring.
    """
    point = Point(longitude, latitude)

    point_features = await arcgis.query_features(
        client,
        SAN_JOSE_PARCELS_QUERY_URL,
        geometry=arcgis.point(longitude, latitude),
        geometry_type="esriGeometryPoint",
        stage="San Jose parcel point query",
    )
    point_candidates = [f for f in (feature_to_geojson(f) for f in point_features) if f]
    for feature in point_candidates:
        if _covers(feature, point):
            return feature, "point_contains"

    envelope_features = await arcgis.query_features(
        client,
        SAN_JOSE_PARCELS_QUERY_URL,
        geometry=arcgis.envelope(
            longitude - _CENTERLINE_PAD_LON,
            latitude - _CENTERLINE_PAD_LAT,
            longitude + _CENTERLINE_PAD_LON,
            latitude + _CENTERLINE_PAD_LAT,
        ),
        geometry_type="esriGeometryEnvelope",
        max_records=20,
        stage="San Jose parcel envelope query",
    )
    envelope_candidates = [f for f in (feature_to_geojson(f) for f in envelope_features) if f]
    for feature in envelope_candidates:
        if _covers(feature, point):
            return feature, "envelope_contains"

    raise HTTPException(
        404,
        f"Geocoded point did not fall inside any San Jose parcel "
        f"(checked {len(point_candidates)} direct and {len(envelope_candidates)} nearby parcels). "
        "Try a more specific street address.",
    )


PARCEL_ID_KEYS = ("APN", "apn", "APN_LABEL", "PARCELID", "ParcelID")
# Note: OBJECTID intentionally excluded — it is not stable across ArcGIS
# republishes and would change the job_id for the same parcel over time.


def parcel_apn(parcel_fc: dict[str, Any]) -> str | None:
    """Best-effort APN extraction for use as a stable identifier."""
    features = parcel_fc.get("features") or []
    if not features:
        return None
    props = features[0].get("properties") or {}
    for key in PARCEL_ID_KEYS:
        value = props.get(key)
        if value not in (None, "", 0):
            return str(value)
    return None
