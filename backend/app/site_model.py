"""Parcel-first site model for the ADU 3D and solar simulator.

Produces a parcel-local geometry payload the frontend can render directly:
parcel/building rings in UTM-relative metres, an eroded buildable zone, a
suggested ADU placement, and a satellite-imagery descriptor whose four
corners line up with the geometry exactly.

T1 correctness change: the legacy code synthesised a fake 5.5 × 7 m
"existing house" at the parcel centroid whenever no building outline was
found. That made downstream setback / clearance / rear-yard math look
plausible while being entirely invented. This module instead returns an
empty `buildings` list and lets the buildable zone equal the setback-eroded
parcel — the frontend surfaces a clear "no building data" empty state.
"""

from __future__ import annotations

import logging
import math
from typing import Any
from urllib.parse import urlencode

from shapely.affinity import rotate
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Point, Polygon, box, mapping, shape
from shapely.ops import transform as shapely_transform, unary_union

from app.services.arcgis import (
    FROM_WEBMERC,
    TO_UTM,
    TO_WEBMERC,
    TO_WGS84,
    UTM_EPSG,
)

logger = logging.getLogger(__name__)

M_TO_FT = 3.28084
M2_TO_FT2 = 10.7639104167

# How far beyond the parcel bounds to include in the satellite imagery plane.
# Wider context lets users verify alignment against neighbouring rooflines.
IMAGERY_PAD_M = 14.0
# Longest edge of the imagery bitmap in pixels. Aspect ratio is preserved so
# the texture maps 1:1 onto the rectangular ground plane (no UV distortion).
IMAGERY_MAX_PX = 1024

ARCGIS_WORLD_IMAGERY_EXPORT = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/export"
)
ARCGIS_WORLD_STREET_EXPORT = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/"
    "World_Street_Map/MapServer/export"
)

# Setback / clearance defaults applied to every parcel.
_DEFAULT_SETBACK_FT = 4.0
_FRONT_SETBACK_FT = 45.0   # detached ADU must be >= 45 ft from front property line
_CLEARANCE_FROM_PRIMARY_FT = 6.0
_DEFAULT_BUILDING_HEIGHT_FT = 18.0
_DEFAULT_ADU_HEIGHT_FT = 16.0

# OBJECTID intentionally excluded — it is not stable across ArcGIS republishes.
_PARCEL_ID_KEYS = (
    "APN", "ApN", "apn", "ApnLabel", "APN_LABEL", "ApnNumber",
    "PARCELID", "ParcelID", "PARCEL_ID",
)
_PARCEL_ADDRESS_KEYS = (
    "SITEADDRESS", "SiteAddress", "SITUSADDRESS", "PROPADDR",
    "PropertyAddress", "STREETADDRESS",
)


# ── Geometry helpers ─────────────────────────────────────────────────────────
def _largest_polygon(geom) -> Polygon:
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda p: p.area)
    polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    if not polys:
        raise ValueError("Expected a polygon geometry.")
    return max(polys, key=lambda p: p.area)


def _fc_to_polygons(fc: dict[str, Any]) -> list[Polygon]:
    return [
        _largest_polygon(shape(geom))
        for feature in fc.get("features", [])
        if (geom := feature.get("geometry"))
    ]


def _fc_to_features(fc: dict[str, Any]) -> list[tuple[Polygon, dict[str, Any]]]:
    """Return (polygon, properties) pairs from a GeoJSON FeatureCollection."""
    out: list[tuple[Polygon, dict[str, Any]]] = []
    for feature in fc.get("features", []):
        geom = feature.get("geometry")
        if not geom:
            continue
        try:
            out.append((_largest_polygon(shape(geom)), feature.get("properties") or {}))
        except (GEOSException, ValueError, TypeError) as exc:
            logger.debug("Skipping malformed feature: %s", exc)
    return out


def _rings(poly: Polygon, cx: float, cy: float) -> list[list[list[float]]]:
    out: list[list[list[float]]] = []
    out.append([[float(x - cx), float(y - cy)] for x, y in poly.exterior.coords])
    for hole in poly.interiors:
        out.append([[float(x - cx), float(y - cy)] for x, y in hole.coords])
    return out


def _local_geojson(geom) -> dict[str, Any]:
    return mapping(shapely_transform(TO_WGS84, geom))


def _split_polygons(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [p for p in geom.geoms if isinstance(p, Polygon)]


# ── Building height inference ────────────────────────────────────────────────
def _building_height_ft(props: dict[str, Any], default_ft: float = _DEFAULT_BUILDING_HEIGHT_FT) -> float:
    """Extract building height (ft) from ArcGIS feature properties.

    Source priority:
      1. SCC LiDAR absolute elevation fields (`Building_H` − `Base_Heigh`).
      2. Direct height fields in feet (`HEIGHT`, `HT_FT`, `BLDG_HT`, …).
      3. Story-count fields × 10 ft per story.
      4. Hardcoded default (caller-supplied).
    """
    roof = props.get("Building_H") or props.get("ROOF_ELEV") or props.get("ROOFMAX")
    base = props.get("Base_Heigh") or props.get("BASE_ELEV") or props.get("GROUNDELEV")
    if roof is not None and base is not None:
        try:
            h = float(roof) - float(base)
            if 5.0 <= h <= 200.0:
                return round(h, 1)
        except (TypeError, ValueError):
            pass

    for key in ("HEIGHT", "HT_FT", "BLDG_HT", "BLDG_HEIGHT", "BLDGHEIGHT", "HEIGHTROOF"):
        val = props.get(key)
        if val is None:
            continue
        try:
            h = float(val)
            if 5.0 <= h <= 200.0:
                return round(h, 1)
        except (TypeError, ValueError):
            pass

    for key in ("STORIES", "NUMFLOORS", "FLOORS", "NUM_FLOORS", "NUM_STORIES"):
        val = props.get(key)
        if val is None:
            continue
        try:
            stories = int(val)
            if stories > 0:
                return float(stories) * 10.0
        except (TypeError, ValueError):
            pass

    return default_ft


def _height_source(props: dict[str, Any]) -> str:
    if props.get("Building_H") and props.get("Base_Heigh"):
        return "lidar_scc"
    for key in ("HEIGHT", "HT_FT", "BLDG_HT", "BLDG_HEIGHT", "BLDGHEIGHT", "HEIGHTROOF"):
        if props.get(key) is not None:
            return "feature_attribute"
    for key in ("STORIES", "NUMFLOORS", "FLOORS", "NUM_FLOORS", "NUM_STORIES"):
        if props.get(key) is not None:
            return "story_count"
    return "default_ft"


# ── Imagery descriptor ───────────────────────────────────────────────────────
def _basemap_urls(export_url: str, common: dict[str, str]) -> dict[str, str]:
    direct = f"{export_url}?{urlencode({**common, 'f': 'image'})}"
    return {
        "url_image": f"/api/basemap?{urlencode({'src': direct})}",
        "url_json": f"{export_url}?{urlencode({**common, 'f': 'json'})}",
    }


def _build_imagery(parcel_utm: Polygon, cx: float, cy: float) -> dict[str, Any]:
    """Build a 4-corner satellite imagery descriptor the viewer can place 1:1.

    ArcGIS World_Imagery only reliably reprojects requests in EPSG:3857 or
    EPSG:4326. We therefore:
      1. Pad the parcel bbox in UTM and project its 4 corners → 3857.
      2. Request a 3857 image whose bbox covers those corners.
      3. Project the 3857 bbox corners back to UTM, shifted into the parcel-
         local frame. The frontend renders a quad with these vertices + UVs
         (0,0) (1,0) (1,1) (0,1). At residential scales the quad is rectangular
         (sub-mm distortion), so the imagery aligns with the geometry.
    """
    minx, miny, maxx, maxy = parcel_utm.bounds
    pad = IMAGERY_PAD_M
    utm_minx, utm_miny = minx - pad, miny - pad
    utm_maxx, utm_maxy = maxx + pad, maxy + pad
    if utm_maxx <= utm_minx or utm_maxy <= utm_miny:
        return {}

    utm_corners = [
        (utm_minx, utm_miny),
        (utm_maxx, utm_miny),
        (utm_maxx, utm_maxy),
        (utm_minx, utm_maxy),
    ]
    merc_corners = [TO_WEBMERC(x, y) for x, y in utm_corners]
    merc_xs = [p[0] for p in merc_corners]
    merc_ys = [p[1] for p in merc_corners]
    merc_minx, merc_maxx = min(merc_xs), max(merc_xs)
    merc_miny, merc_maxy = min(merc_ys), max(merc_ys)

    width_m = merc_maxx - merc_minx
    height_m = merc_maxy - merc_miny
    if width_m >= height_m:
        width_px = IMAGERY_MAX_PX
        height_px = max(64, int(round(IMAGERY_MAX_PX * height_m / width_m)))
    else:
        height_px = IMAGERY_MAX_PX
        width_px = max(64, int(round(IMAGERY_MAX_PX * width_m / height_m)))

    common = {
        "bbox": f"{merc_minx},{merc_miny},{merc_maxx},{merc_maxy}",
        "bboxSR": "3857",
        "imageSR": "3857",
        "size": f"{width_px},{height_px}",
        "format": "png",
        "transparent": "false",
    }

    satellite = _basemap_urls(ARCGIS_WORLD_IMAGERY_EXPORT, common)
    streets = _basemap_urls(ARCGIS_WORLD_STREET_EXPORT, common)

    # 4 corners (SW, SE, NE, NW) so UVs map (0,0)(1,0)(1,1)(0,1) cleanly.
    merc_box_corners = [
        (merc_minx, merc_miny),
        (merc_maxx, merc_miny),
        (merc_maxx, merc_maxy),
        (merc_minx, merc_maxy),
    ]
    placement_corners = []
    for mx, my in merc_box_corners:
        ux, uy = FROM_WEBMERC(mx, my)
        placement_corners.append([ux - cx, uy - cy])

    sw_wgs = shapely_transform(TO_WGS84, Point(utm_minx, utm_miny))
    ne_wgs = shapely_transform(TO_WGS84, Point(utm_maxx, utm_maxy))

    return {
        "provider": "ArcGIS World_Imagery",
        "crs_geometry": f"EPSG:{UTM_EPSG}",
        "crs_image": "EPSG:3857",
        "bbox_3857": {
            "minX": merc_minx, "minY": merc_miny,
            "maxX": merc_maxx, "maxY": merc_maxy,
        },
        "corners_local_m": placement_corners,
        "bbox_wgs84": {
            "west": sw_wgs.x, "south": sw_wgs.y,
            "east": ne_wgs.x, "north": ne_wgs.y,
        },
        "width_px": width_px,
        "height_px": height_px,
        "pad_m": pad,
        "url_image": satellite["url_image"],
        "url_json": satellite["url_json"],
        "basemaps": {
            "satellite": {"label": "Satellite", "provider": "ArcGIS World_Imagery", **satellite},
            "streets": {"label": "Street map", "provider": "ArcGIS World_Street_Map", **streets},
        },
    }


# ── Front setback ────────────────────────────────────────────────────────────
def _front_setback_zone(parcel: Polygon, front_edge_index: int, setback_m: float) -> Polygon:
    """Return a polygon covering the parcel area within setback_m of the front edge.

    The caller subtracts this from the buildable zone so only land behind the
    45 ft front setback line is considered for ADU placement.
    """
    coords = list(parcel.exterior.coords)
    n = len(coords) - 1  # number of edges; coords has n+1 entries (closed ring)
    if not (0 <= front_edge_index < n):
        return Polygon()

    ax, ay = coords[front_edge_index]
    bx, by = coords[front_edge_index + 1]

    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return Polygon()

    ux, uy = dx / length, dy / length  # unit vector along the edge
    # Two candidate inward normals (90° rotations of the edge direction).
    n1x, n1y = -uy, ux
    n2x, n2y = uy, -ux
    pcx, pcy = parcel.centroid.x, parcel.centroid.y
    mx, my = (ax + bx) / 2, (ay + by) / 2
    inx, iny = (n1x, n1y) if (pcx - mx) * n1x + (pcy - my) * n1y > 0 else (n2x, n2y)

    # Extend the edge endpoints well past the parcel so the slab spans the full width.
    ext = parcel.length + setback_m
    p1 = (ax - ux * ext, ay - uy * ext)
    p2 = (bx + ux * ext, by + uy * ext)
    p3 = (p2[0] + inx * setback_m, p2[1] + iny * setback_m)
    p4 = (p1[0] + inx * setback_m, p1[1] + iny * setback_m)
    return Polygon([p1, p2, p3, p4])


def _front_depth_axis_angle(parcel: Polygon, front_edge_index: int) -> float | None:
    """Return the front-to-back inward axis implied by a selected front edge."""
    coords = list(parcel.exterior.coords)
    n = len(coords) - 1
    if not (0 <= front_edge_index < n):
        return None

    ax, ay = coords[front_edge_index]
    bx, by = coords[front_edge_index + 1]
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None

    ux, uy = dx / length, dy / length
    n1x, n1y = -uy, ux
    n2x, n2y = uy, -ux
    pcx, pcy = parcel.centroid.x, parcel.centroid.y
    mx, my = (ax + bx) / 2, (ay + by) / 2
    inx, iny = (n1x, n1y) if (pcx - mx) * n1x + (pcy - my) * n1y > 0 else (n2x, n2y)
    return _normalize_angle_deg(math.degrees(math.atan2(iny, inx)))


# ── ADU placement search ─────────────────────────────────────────────────────
def _rect_at(cx: float, cy: float, width_m: float, depth_m: float, angle_deg: float) -> Polygon:
    rect = box(cx - width_m / 2, cy - depth_m / 2, cx + width_m / 2, cy + depth_m / 2)
    return rotate(rect, angle_deg, origin=(cx, cy), use_radians=False)


def _normalize_angle_deg(angle_deg: float) -> float:
    return ((angle_deg + 180) % 360) - 180


def _dominant_angle(poly: Polygon) -> float:
    """Return the long-axis angle of the parcel/buildable polygon."""
    coords = list(poly.minimum_rotated_rectangle.exterior.coords)
    if len(coords) < 2:
        return 0.0

    best_angle = 0.0
    best_len = 0.0
    for p0, p1 in zip(coords, coords[1:]):
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        length = math.hypot(dx, dy)
        if length > best_len:
            best_len = length
            best_angle = math.degrees(math.atan2(dy, dx))
    return _normalize_angle_deg(best_angle)


def _adu_rotation_for_axis(axis_angle_deg: float, width_m: float, depth_m: float) -> float:
    # `rotation_deg` rotates the ADU local width axis. When the ADU is deeper
    # than wide, align its local depth axis with the property axis instead.
    return _normalize_angle_deg(axis_angle_deg - (90 if depth_m > width_m else 0))


def _candidate_angles(parcel_angle_deg: float, width_m: float, depth_m: float) -> list[float]:
    angles: list[float] = []
    for axis in (parcel_angle_deg, parcel_angle_deg + 90):
        normalized = _adu_rotation_for_axis(axis, width_m, depth_m)
        if all(abs(normalized - existing) > 1 for existing in angles):
            angles.append(normalized)
    return angles


def _candidate_placements(
    buildable: Polygon | MultiPolygon,
    width_m: float,
    depth_m: float,
    angle_deg: float,
) -> list[dict[str, Any]]:
    if buildable.is_empty:
        return []
    polys = [buildable] if isinstance(buildable, Polygon) else list(buildable.geoms)
    angles = _candidate_angles(angle_deg, width_m, depth_m)
    candidates: list[dict[str, Any]] = []
    for poly in sorted(polys, key=lambda p: p.area, reverse=True)[:4]:
        minx, miny, maxx, maxy = poly.bounds
        steps_x = max(5, min(16, int((maxx - minx) / max(width_m * 0.35, 0.8))))
        steps_y = max(5, min(16, int((maxy - miny) / max(depth_m * 0.35, 0.8))))
        for candidate_angle in angles:
            for ix in range(steps_x):
                for iy in range(steps_y):
                    x = minx + (ix + 0.5) * (maxx - minx) / steps_x
                    y = miny + (iy + 0.5) * (maxy - miny) / steps_y
                    point = Point(x, y)
                    if not poly.contains(point):
                        continue
                    rect = _rect_at(x, y, width_m, depth_m, candidate_angle)
                    if poly.contains(rect):
                        candidates.append({
                            "center_local": [x, y],
                            "rotation_deg": candidate_angle,
                            "score": float(poly.boundary.distance(point)),
                        })
    preferred_angle = angles[0] if angles else None
    candidates.sort(
        key=lambda c: (c["rotation_deg"] == preferred_angle, c["score"]),
        reverse=True,
    )
    return candidates[:8]


# ── Parcel identifiers ───────────────────────────────────────────────────────
def _first_attr(props: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = props.get(k)
        if v not in (None, "", 0):
            return str(v)
    return None


def _parcel_identifier(parcel_fc: dict[str, Any]) -> dict[str, Any]:
    features = parcel_fc.get("features") or []
    if not features:
        return {}
    props = features[0].get("properties") or {}
    return {
        "apn": _first_attr(props, _PARCEL_ID_KEYS),
        "site_address": _first_attr(props, _PARCEL_ADDRESS_KEYS),
        "raw_attribute_count": len(props),
    }


# ── Public entry points ──────────────────────────────────────────────────────
def parcel_area_ft2_from_fc(parcel_fc: dict[str, Any]) -> float:
    """Return parcel area in sq ft from a GeoJSON FeatureCollection. Returns 0.0 on error."""
    try:
        poly = _largest_polygon(unary_union(_fc_to_polygons(parcel_fc)))
        return _largest_polygon(shapely_transform(TO_UTM, poly)).area * M2_TO_FT2
    except Exception:
        return 0.0


def build_site_model(
    address: str,
    latitude: float,
    longitude: float,
    parcel_fc: dict[str, Any],
    building_fc: dict[str, Any],
    adu_width_ft: float = 24.0,
    adu_depth_ft: float = 32.0,
    adu_height_ft: float = 16.0,
    side_rear_setback_ft: float = _DEFAULT_SETBACK_FT,
    front_offset_ft: float = _FRONT_SETBACK_FT,
    clearance_from_existing_ft: float = _CLEARANCE_FROM_PRIMARY_FT,
    building_height_ft: float = _DEFAULT_BUILDING_HEIGHT_FT,
    front_edge_index: int | None = None,
) -> dict[str, Any]:
    parcel_wgs = _largest_polygon(unary_union(_fc_to_polygons(parcel_fc)))
    parcel = _largest_polygon(shapely_transform(TO_UTM, parcel_wgs))

    buildings_with_props: list[tuple[Polygon, dict[str, Any]]] = [
        (_largest_polygon(shapely_transform(TO_UTM, poly)), props)
        for poly, props in _fc_to_features(building_fc)
    ]
    buildings = [b for b, _ in buildings_with_props]

    setback_m = side_rear_setback_ft / M_TO_FT
    clearance_m = clearance_from_existing_ft / M_TO_FT
    parcel_eroded = parcel.buffer(-setback_m, join_style=2).buffer(0)

    front_edge_applied = False
    if front_edge_index is not None and front_offset_ft > 0:
        front_zone = _front_setback_zone(parcel, front_edge_index, front_offset_ft / M_TO_FT)
        if not front_zone.is_empty:
            parcel_eroded = parcel_eroded.difference(front_zone).buffer(0)
            front_edge_applied = True

    if buildings:
        building_union = unary_union(buildings)
        buildable = parcel_eroded.difference(
            building_union.buffer(clearance_m, join_style=2)
        ).buffer(0)
    else:
        # No existing buildings → the entire setback-eroded parcel is buildable.
        # Frontend should still surface that no primary-residence outline was
        # available so the user can sanity-check before relying on the result.
        buildable = parcel_eroded

    centroid = parcel.centroid
    cx, cy = float(centroid.x), float(centroid.y)
    parcel_angle = _dominant_angle(parcel)
    adu_width_m = adu_width_ft / M_TO_FT
    adu_depth_m = adu_depth_ft / M_TO_FT
    placements = _candidate_placements(buildable, adu_width_m, adu_depth_m, parcel_angle)
    for p in placements:
        p["center_local"] = [
            float(p["center_local"][0] - cx),
            float(p["center_local"][1] - cy),
        ]

    buildable_polys = _split_polygons(buildable)
    parcel_eroded_polys = _split_polygons(parcel_eroded)

    building_items = []
    for idx, (building, props) in enumerate(buildings_with_props):
        height_ft = _building_height_ft(props, default_ft=float(building_height_ft))
        inflated = building.buffer(clearance_m, join_style=2)
        building_items.append({
            "id": f"building_{idx}",
            "rings_local": _rings(building, cx, cy),
            "rings_local_inflated": _rings(_largest_polygon(inflated), cx, cy),
            "height_m": height_ft / M_TO_FT,
            "height_ft": height_ft,
            "area_ft2": building.area * M2_TO_FT2,
            "geojson": _local_geojson(building),
            "height_source": _height_source(props),
        })

    imagery = _build_imagery(parcel, cx, cy)
    parcel_id = _parcel_identifier(parcel_fc)

    return {
        "address": address,
        "latitude": latitude,
        "longitude": longitude,
        "crs": f"EPSG:{UTM_EPSG}",
        "units": "meters",
        "origin_utm": {"x": cx, "y": cy},
        "imagery": imagery,
        "parcel": {
            "rings_local": _rings(parcel, cx, cy),
            "area_ft2": parcel.area * M2_TO_FT2,
            "perimeter_ft": parcel.length * M_TO_FT,
            "apn": parcel_id.get("apn"),
            "site_address": parcel_id.get("site_address"),
            "geojson": _local_geojson(parcel),
        },
        "buildings": building_items,
        "buildable_zone": {
            "setback_ft": side_rear_setback_ft,
            "setback_m": setback_m,
            "front_setback_ft": front_offset_ft if front_edge_applied else None,
            "front_edge_index": front_edge_index if front_edge_applied else None,
            "clearance_from_existing_ft": clearance_from_existing_ft,
            "clearance_from_existing_m": clearance_m,
            "area_ft2": sum(p.area for p in buildable_polys) * M2_TO_FT2,
            "polygons": [
                {"rings_local": _rings(p, cx, cy), "area_ft2": p.area * M2_TO_FT2}
                for p in buildable_polys
            ],
            "parcel_eroded_polygons": [
                {"rings_local": _rings(p, cx, cy)} for p in parcel_eroded_polys
            ],
        },
        "adu": {
            "width_ft": adu_width_ft,
            "depth_ft": adu_depth_ft,
            "height_ft": adu_height_ft,
            "suggested_rotation_deg": parcel_angle,
            "placements": placements,
            "fits_requested_size": bool(placements),
        },
        "solar_defaults": {
            "roof_panel_area_m2": max(20.0, min(55.0, sum(b.area for b in buildings) * 0.32)),
            "panel_efficiency": 0.20,
            "performance_ratio": 0.78,
            "annual_irradiance_kwh_m2": 1850.0,
        },
    }
