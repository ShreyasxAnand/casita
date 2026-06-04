"""San Jose ZIP boundary lookup for contractor heatmap scans."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from app.services import arcgis
from app.services.arcgis_geometry import feature_to_geojson

SAN_JOSE_ZIP_BOUNDARIES_QUERY_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/OPN/"
    "OPN_OpenDataService/MapServer/181/query"
)
ZIP_BOUNDARY_SOURCE = "San Jose Zipcode Boundaries layer 181"


def normalize_zip_code(zip_code: str) -> str:
    zip_clean = (zip_code or "").strip()
    if not (len(zip_clean) == 5 and zip_clean.isdigit()):
        raise HTTPException(422, "Enter a valid 5-digit ZIP code.")
    return zip_clean


async def fetch_zip_boundary(
    client: httpx.AsyncClient,
    zip_code: str,
) -> dict[str, Any]:
    """Fetch the official San Jose ZIP polygon used to filter heatmap parcels."""
    zip_clean = normalize_zip_code(zip_code)
    data = await arcgis.fetch_json(
        client,
        SAN_JOSE_ZIP_BOUNDARIES_QUERY_URL,
        {
            "where": f"ZIPCODE = '{zip_clean}' AND SANJOSELIMITS = 'Yes'",
            "outFields": "ZIPCODE,SANJOSELIMITS",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
        },
        stage="San Jose ZIP boundary",
    )

    geoms = []
    for feature in data.get("features") or []:
        geojson = feature_to_geojson(feature)
        if not geojson or not geojson.get("geometry"):
            continue
        geom = shape(geojson["geometry"]).buffer(0)
        if not geom.is_empty:
            geoms.append(geom)

    if not geoms:
        raise HTTPException(
            404,
            f"ZIP {zip_clean} is outside San Jose coverage. "
            "This heatmap currently scores San Jose parcels only.",
        )

    boundary = unary_union(geoms).buffer(0)
    west, south, east, north = boundary.bounds
    centroid = boundary.representative_point()
    return {
        "zip": zip_clean,
        "center": {"lat": float(centroid.y), "lon": float(centroid.x)},
        "bbox": {
            "west": float(west),
            "south": float(south),
            "east": float(east),
            "north": float(north),
        },
        "geometry": mapping(boundary.simplify(0.00001, preserve_topology=True)),
        "source": ZIP_BOUNDARY_SOURCE,
    }
