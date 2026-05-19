"""Convert ArcGIS ring/feature JSON to GeoJSON, robustly.

ArcGIS REST returns polygon geometry as a list of rings without explicit
shell/hole semantics. This module normalises them into GeoJSON features
that downstream `shapely` code can rely on.
"""

from __future__ import annotations

import logging
from typing import Any

from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon, mapping

logger = logging.getLogger(__name__)


def _closed_ring(ring: list[Any]) -> list[list[float]]:
    coords = [[float(p[0]), float(p[1])] for p in ring if len(p) >= 2]
    if coords and coords[0] != coords[-1]:
        coords.append(coords[0][:])
    return coords


def rings_to_geojson(rings: list[Any]) -> dict[str, Any] | None:
    """Convert a list of ArcGIS rings into a GeoJSON Polygon / MultiPolygon.

    ArcGIS may emit multiple exterior rings; we resolve shell vs hole by
    point-in-polygon containment rather than assuming "first ring exterior,
    rest holes".
    """
    if not rings:
        return None

    ring_items: list[dict[str, Any]] = []
    for raw_ring in rings:
        coords = _closed_ring(raw_ring)
        if len(coords) < 4:
            continue
        poly = Polygon(coords)
        if poly.is_valid and not poly.is_empty and poly.area > 0:
            ring_items.append({"coords": coords, "poly": poly, "area": abs(poly.area)})

    if not ring_items:
        return None

    shells: list[dict[str, Any]] = []
    for item in sorted(ring_items, key=lambda i: i["area"], reverse=True):
        point = item["poly"].representative_point()
        parent = next((shell for shell in shells if shell["poly"].contains(point)), None)
        if parent:
            parent["holes"].append(item["coords"])
        else:
            shells.append({"coords": item["coords"], "holes": [], "poly": item["poly"]})

    polygons: list[Polygon] = []
    for shell in shells:
        try:
            polygon = Polygon(shell["coords"], shell["holes"]).buffer(0)
        except GEOSException as exc:
            logger.warning("Skipping invalid ArcGIS ring: %s", exc)
            continue
        if isinstance(polygon, Polygon) and not polygon.is_empty:
            polygons.append(polygon)
        elif isinstance(polygon, MultiPolygon):
            polygons.extend([p for p in polygon.geoms if not p.is_empty])

    if not polygons:
        return None
    geom = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
    return mapping(geom)


def feature_to_geojson(feature: dict[str, Any]) -> dict[str, Any] | None:
    """Convert one ArcGIS feature (rings + attributes) to a GeoJSON Feature."""
    geometry = feature.get("geometry") or {}
    geojson = rings_to_geojson(geometry.get("rings") or [])
    if not geojson:
        return None
    return {
        "type": "Feature",
        "geometry": geojson,
        "properties": feature.get("attributes") or {},
    }
