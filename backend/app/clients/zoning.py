"""San Jose zoning + General Plan lookups for a point."""

from __future__ import annotations

from typing import Any

import httpx

from app.rules.zoning import zoning_full_name
from app.services import arcgis

SAN_JOSE_ZONING_QUERY_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/OPN/"
    "OPN_OpenDataService/MapServer/401/query"
)
SAN_JOSE_GENERAL_PLAN_QUERY_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/OPN/"
    "OPN_OpenDataService/MapServer/404/query"
)


async def fetch_zoning(
    client: httpx.AsyncClient, latitude: float, longitude: float
) -> dict[str, Any]:
    features = await arcgis.query_features(
        client,
        SAN_JOSE_ZONING_QUERY_URL,
        geometry=arcgis.point(longitude, latitude),
        geometry_type="esriGeometryPoint",
        return_geometry=False,
        out_fields=(
            "ZONING,ZONINGABBREV,FACILITYID,REZONINGFILE,PDUSE,PDDENSITY,"
            "DEVELOPEDASPD,APPROVALDATE,NOTES"
        ),
        stage="San Jose zoning",
    )
    attrs = (features[0].get("attributes") if features else {}) or {}
    zoning_code = attrs.get("ZONING") or attrs.get("ZONINGABBREV") or ""
    return {
        "zoning": zoning_code,
        "zoning_abbrev": attrs.get("ZONINGABBREV") or zoning_code,
        "zoning_full_name": zoning_full_name(zoning_code),
        "facility_id": attrs.get("FACILITYID"),
        "rezoning_file": attrs.get("REZONINGFILE"),
        "pd_use": attrs.get("PDUSE"),
        "pd_density": attrs.get("PDDENSITY"),
        "developed_as_pd": attrs.get("DEVELOPEDASPD"),
        "approval_date": attrs.get("APPROVALDATE"),
        "notes": attrs.get("NOTES"),
    }


async def fetch_general_plan(
    client: httpx.AsyncClient, latitude: float, longitude: float
) -> dict[str, Any]:
    features = await arcgis.query_features(
        client,
        SAN_JOSE_GENERAL_PLAN_QUERY_URL,
        geometry=arcgis.point(longitude, latitude),
        geometry_type="esriGeometryPoint",
        return_geometry=False,
        out_fields="GPDESIGNATION,GPABBREVIATION,NOTES,LASTUPDATE",
        stage="San Jose General Plan",
    )
    attrs = (features[0].get("attributes") if features else {}) or {}
    return {
        "gp_designation": attrs.get("GPDESIGNATION") or "",
        "gp_abbreviation": attrs.get("GPABBREVIATION") or "",
        "notes": attrs.get("NOTES"),
        "last_update": attrs.get("LASTUPDATE"),
    }
