"""End-to-end pipeline for `POST /api/site`.

City-agnostic. Composes the selected `CityAdapter`'s geocoder, parcel/building
clients, zoning + designation lookups, permits/code-enforcement, and the
HomeHarvest property data into one response. Each external fetch goes through
the adapter so swapping cities is a single dispatch decision in `main.py`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from typing import Any

import httpx
from fastapi import HTTPException
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import transform as shapely_transform, unary_union

import dataclasses

from app.cities.base import CityAdapter, GeocodeResult
from app.cities.san_jose.development_standards import get_constraints, normalize_property_type
from app.models import SiteRequest, stage, warn_stage
from app.property_data import (
    avg_year_built,
    build_financing,
    build_property_stats,
    build_zip_context,
    find_subject_in_zip,
    get_property_by_address,
    search_properties_by_zip,
)
from app.result import FetchResult
from app.services.arcgis import TO_UTM
from app.site_model import M_TO_FT, build_site_model, parcel_area_ft2_from_fc

logger = logging.getLogger(__name__)


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _collect_data_warnings(
    zoning_result: FetchResult[Any],
    gp_result: FetchResult[Any],
    typed_designations: dict[str, FetchResult[Any]],
    permits_result: FetchResult[Any] | None,
    ce_result: FetchResult[Any] | None,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for field, result in [("zoning", zoning_result), ("general_plan", gp_result)]:
        if result.is_failed:
            warnings.append({"field": field, "source": result.source, "error": result.error})
    for field, result in typed_designations.items():
        if result.is_failed:
            warnings.append({"field": field, "source": result.source, "error": result.error})
    if permits_result and permits_result.is_failed:
        warnings.append({
            "field": "permits",
            "source": permits_result.source,
            "error": permits_result.error,
        })
    if ce_result and ce_result.is_failed:
        warnings.append({
            "field": "code_enforcement",
            "source": ce_result.source,
            "error": ce_result.error,
        })
    return warnings


async def _property_data_block(
    req: SiteRequest, geocode: GeocodeResult,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run HomeHarvest lookups in worker threads, then build pro-forma."""
    prop_task = asyncio.create_task(
        asyncio.to_thread(get_property_by_address, geocode.matched_address)
    )
    zip_task = (
        asyncio.create_task(asyncio.to_thread(search_properties_by_zip, geocode.zip_code, 30))
        if geocode.zip_code else None
    )

    start = time.perf_counter()
    try:
        prop_data = await prop_task
    except Exception as exc:
        logger.warning("HomeHarvest property fetch failed: %s", exc)
        prop_data = None
    try:
        zip_props = await zip_task if zip_task else []
    except Exception as exc:
        logger.warning("HomeHarvest zip fetch failed: %s", exc)
        zip_props = []
    if not prop_data and zip_props:
        prop_data = find_subject_in_zip(geocode.matched_address, zip_props)

    property_stats = build_property_stats(
        prop_data,
        address=geocode.matched_address,
        city=geocode.city,
        state=geocode.state,
        zip_code=geocode.zip_code,
        latitude=geocode.latitude,
        longitude=geocode.longitude,
        neighborhood_avg_year_built=avg_year_built(zip_props),
    )
    zip_context = build_zip_context(geocode.zip_code, geocode.city, geocode.state, zip_props)
    financing = build_financing(
        req.adu_width_ft,
        req.adu_depth_ft,
        zip_context,
        build_cost_per_sqft=req.build_cost_per_sqft,
        down_payment_pct=req.down_payment_pct,
        interest_rate_pct=req.interest_rate_pct,
        loan_term_years=req.loan_term_years,
    )
    stage_entry = stage(
        "fetch_property_data", start,
        f"HomeHarvest: subject {'matched' if property_stats.get('found') else 'not found'}, "
        f"{zip_context.get('total_listings', 0)} zip listings.",
        {
            "subject_found": property_stats.get("found", False),
            "zip_listings": zip_context.get("total_listings", 0),
            "zip_rentals": zip_context.get("rental_listings", 0),
            "zip_avg_rent": zip_context.get("average_rent"),
        },
    )
    return property_stats, zip_context, financing, stage_entry


def _make_job_id(prefix: str, parcel_id: str | None, address: str, lat: float, lon: float) -> str:
    """Derive a stable job ID from the parcel APN (or equivalent), falling back
    to a short hash of the address + coordinates when no parcel id is available.
    """
    if parcel_id:
        return f"{prefix}-{parcel_id}"
    digest = hashlib.sha1(f"{address}|{lat}|{lon}".encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _site_model_stage(building_source: str, adu_type: str) -> dict[str, Any]:
    """Synthetic stage entry that reports on the local 3D-geometry build."""
    if building_source != "not_found":
        detail = "Generated parcel-local 3D geometry from live outlines."
    elif adu_type == "jadu":
        detail = (
            "Generated parcel-local geometry. No primary-residence outline found — "
            "JADU footprint capacity cannot be verified."
        )
    else:
        detail = (
            "Generated parcel-local geometry. No primary-residence outline found — "
            "buildable zone = full setback-eroded parcel and checklist items are marked verify."
        )
    return {
        "name": "site_model",
        "status": "ok",
        "duration_ms": 0,
        "detail": detail,
        "data": {"building_source": building_source},
        "log_tail": None,
    }


def _largest_polygon(geom) -> Polygon:
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda p: p.area)
    polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    if not polys:
        raise ValueError("Expected polygon geometry.")
    return max(polys, key=lambda p: p.area)


def _feature_polygons_utm(fc: dict[str, Any]) -> list[Polygon]:
    polygons: list[Polygon] = []
    for feature in fc.get("features") or []:
        geom = feature.get("geometry")
        if not geom:
            continue
        try:
            polygons.append(_largest_polygon(shapely_transform(TO_UTM, shape(geom))).buffer(0))
        except (GEOSException, TypeError, ValueError) as exc:
            logger.debug("Skipping geometry while deriving state-fit inputs: %s", exc)
    return [p for p in polygons if not p.is_empty]


def _front_frame_state_fit_inputs(
    parcel_fc: dict[str, Any],
    building_fc: dict[str, Any],
    front_edge_index: int | None,
) -> dict[str, Any]:
    """Approximate State Standards 800 sf fit inputs from real parcel geometry.

    San Jose's State Standards allow front-setback encroachment only when no
    other siting enables an 800 sf ADU. The standards engine evaluates a
    front-oriented rectangle model, so we derive that model only when the user
    has selected a front edge and a primary-building footprint exists.
    """
    if front_edge_index is None:
        return {}

    parcels = _feature_polygons_utm(parcel_fc)
    buildings = _feature_polygons_utm(building_fc)
    if not parcels or not buildings:
        return {}

    parcel = _largest_polygon(unary_union(parcels)).buffer(0)
    primary = max(buildings, key=lambda p: p.area).intersection(parcel).buffer(0)
    if parcel.is_empty or primary.is_empty:
        return {}

    coords = list(parcel.exterior.coords)
    edge_count = len(coords) - 1
    if not (0 <= front_edge_index < edge_count):
        return {}

    ax, ay = coords[front_edge_index]
    bx, by = coords[front_edge_index + 1]
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return {}

    ux, uy = dx / length, dy / length
    n1x, n1y = -uy, ux
    n2x, n2y = uy, -ux
    pcx, pcy = parcel.centroid.x, parcel.centroid.y
    mx, my = (ax + bx) / 2, (ay + by) / 2
    inx, iny = (n1x, n1y) if (pcx - mx) * n1x + (pcy - my) * n1y > 0 else (n2x, n2y)

    def project(point: tuple[float, float]) -> tuple[float, float]:
        vx = point[0] - ax
        vy = point[1] - ay
        return vx * ux + vy * uy, vx * inx + vy * iny

    parcel_pts = [project((x, y)) for x, y in list(parcel.exterior.coords)[:-1]]
    home_pts = [project((x, y)) for x, y in list(_largest_polygon(primary).exterior.coords)[:-1]]
    if not parcel_pts or not home_pts:
        return {}

    min_px = min(x for x, _ in parcel_pts)
    max_px = max(x for x, _ in parcel_pts)
    min_py = min(y for _, y in parcel_pts)
    max_py = max(y for _, y in parcel_pts)
    min_hx = min(x for x, _ in home_pts)
    max_hx = max(x for x, _ in home_pts)
    min_hy = min(y for _, y in home_pts)
    max_hy = max(y for _, y in home_pts)

    lot_width_m = max_px - min_px
    lot_depth_m = max_py - min_py
    home_width_m = max_hx - min_hx
    home_depth_m = max_hy - min_hy
    if min(lot_width_m, lot_depth_m, home_width_m, home_depth_m) <= 0:
        return {}

    return {
        "lot_width_ft": lot_width_m * M_TO_FT,
        "lot_depth_ft": lot_depth_m * M_TO_FT,
        "home_footprint": {
            "x": (min_hx - min_px) * M_TO_FT,
            "y": (min_hy - min_py) * M_TO_FT,
            "width": home_width_m * M_TO_FT,
            "depth": home_depth_m * M_TO_FT,
        },
    }


def _apply_jadu_buildable_zone(site_model: dict[str, Any]) -> None:
    """For JADUs, the only candidate footprint is the existing primary structure.

    The generic site-model builder computes outdoor parcel buildable area.
    JADUs are different: they must be inside the existing single-family home
    or attached garage, so expose the largest loaded building footprint as the
    model's buildable zone. If no building outline exists, expose an empty
    zone so downstream UI/checklist code cannot treat the parcel envelope as
    JADU-ready.
    """
    buildable = site_model.setdefault("buildable_zone", {})
    adu = site_model.setdefault("adu", {})
    buildings = site_model.get("buildings") or []
    if not buildings:
        adu["placements"] = []
        adu["fits_requested_size"] = False
        buildable.update({
            "setback_ft": 0.0,
            "setback_m": 0.0,
            "front_setback_ft": None,
            "front_edge_index": None,
            "clearance_from_existing_ft": 0.0,
            "clearance_from_existing_m": 0.0,
            "area_ft2": 0.0,
            "polygons": [],
            "parcel_eroded_polygons": [],
        })
        return

    primary = max(buildings, key=lambda b: float(b.get("area_ft2") or 0.0))
    primary_area = float(primary.get("area_ft2") or 0.0)
    primary_rings = primary.get("rings_local") or []
    adu["placements"] = []
    adu["fits_requested_size"] = False
    primary_poly = [{"rings_local": primary_rings, "area_ft2": primary_area}] if primary_rings else []
    buildable.update({
        "setback_ft": 0.0,
        "setback_m": 0.0,
        "front_setback_ft": None,
        "front_edge_index": None,
        "clearance_from_existing_ft": 0.0,
        "clearance_from_existing_m": 0.0,
        "area_ft2": primary_area,
        "polygons": primary_poly,
        "parcel_eroded_polygons": [{"rings_local": primary_rings}] if primary_rings else [],
    })


async def run_site_pipeline(
    client: httpx.AsyncClient, req: SiteRequest, adapter: CityAdapter,
) -> dict[str, Any]:
    """Full live-address pipeline used by `POST /api/site`.

    Reads top-to-bottom as five phases:
      1. Geocode the address (adapter validates the address belongs to its city).
      2. Kick HomeHarvest lookups off in worker threads (overlap with GIS).
      3. Fetch parcel + building outlines via the adapter.
      4. Fetch zoning, General Plan, designations, permits, code enforcement.
      5. Build the site model, derive job id + checklist, assemble response.
    """
    stages: list[dict[str, Any]] = []

    # 1. Geocode ─────────────────────────────────────────────────────────
    start = time.perf_counter()
    geocode = await adapter.geocode(client, req.address)
    lat, lon = geocode.latitude, geocode.longitude
    address = geocode.matched_address
    stages.append(stage(
        "geocode_address", start,
        f"Matched '{geocode.matched_address}' (score {geocode.score:.0f}/100).",
        {"score": geocode.score, "latitude": lat, "longitude": lon},
    ))

    # 2. HomeHarvest (overlapped with GIS calls below) ───────────────────
    prop_data_task = asyncio.create_task(_property_data_block(req, geocode))

    # 3. Parcel + buildings ──────────────────────────────────────────────
    start = time.perf_counter()
    parcel_feature, parcel_source = await adapter.fetch_parcel(client, lat, lon)
    parcel_fc = _feature_collection([parcel_feature])
    stages.append(stage(
        f"fetch_{adapter.name}_parcel", start,
        f"Loaded parcel from {adapter.display_name} GIS using {parcel_source}.",
        {"feature_count": 1, "source": parcel_source},
    ))

    start = time.perf_counter()
    building_fc, building_source = await adapter.fetch_buildings(client, parcel_feature)
    feature_count = len(building_fc["features"])
    req_adu_type = (req.adu_type or "detached").lower().strip()
    stages.append(stage(
        "fetch_building_outlines", start,
        (
            f"Loaded {feature_count} building outline(s) from {building_source}."
            if feature_count > 0
            else "No building outlines found — JADU footprint capacity cannot be verified."
            if req_adu_type == "jadu"
            else "No building outlines found — buildable zone will use the full eroded parcel."
        ),
        {"feature_count": feature_count, "source": building_source},
    ))

    # 4. Zoning + designations + permits + code enforcement ─────────────
    zoning_result, gp_result, zoning_stages = await adapter.fetch_zoning_and_gp(client, lat, lon)
    stages.extend(zoning_stages)

    try:
        typed_designations, dstage = await adapter.fetch_designations(
            client, lat, lon, parcel_feature,
        )
        stages.append(dstage)
    except HTTPException as exc:
        typed_designations = {}
        stages.append(warn_stage("fetch_designations", f"Designation lookup failed: {exc.detail}"))

    parcel_id = adapter.parcel_id(parcel_fc)
    permits_result, ce_result, pe_stages = await adapter.fetch_permits_and_enforcement(
        client, parcel_id, lat, lon,
    )
    stages.extend(pe_stages)

    property_stats, zip_context, financing, prop_stage = await prop_data_task
    stages.append(prop_stage)

    # 5. Resolve development-standards constraints ────────────────────────
    parcel_area_ft2 = parcel_area_ft2_from_fc(parcel_fc)
    zone = zoning_result.data.zoning if zoning_result.data else ""
    adu_type_key = (req.adu_type or "detached").lower().strip()
    if adu_type_key not in ("detached", "attached", "jadu"):
        adu_type_key = "detached"
    prop_type_key = normalize_property_type(
        property_stats.get("style") or "" if property_stats.get("found") else ""
    )
    primary_sqft: float | None = (
        float(property_stats["sqft"])
        if property_stats.get("found") and property_stats.get("sqft")
        else None
    )
    state_fit_inputs = (
        _front_frame_state_fit_inputs(parcel_fc, building_fc, req.front_edge_index)
        if req.standards == "state"
        else {}
    )
    constraints = get_constraints(
        req.standards, prop_type_key, adu_type_key, req.adu_stories, zone,
        lot_size_sf=parcel_area_ft2,
        main_home_livable_sf=primary_sqft,
        lot_width_ft=state_fit_inputs.get("lot_width_ft"),
        lot_depth_ft=state_fit_inputs.get("lot_depth_ft"),
        home_footprint=state_fit_inputs.get("home_footprint"),
    )
    # Effective front offset: siting rule (city detached = 45 ft) takes priority;
    # otherwise use the zone-based front setback from the standards.
    effective_front_offset_ft = (
        constraints.siting_min_front_offset_ft
        if constraints.siting_min_front_offset_ft is not None
        else constraints.front_setback_ft
    )

    # 6. Site model, checklist, response ─────────────────────────────────
    site_model = build_site_model(
        address=address,
        latitude=lat,
        longitude=lon,
        parcel_fc=parcel_fc,
        building_fc=building_fc,
        adu_width_ft=req.adu_width_ft,
        adu_depth_ft=req.adu_depth_ft,
        adu_height_ft=req.adu_height_ft,
        side_rear_setback_ft=constraints.min_side_setback_ft,
        front_offset_ft=effective_front_offset_ft,
        clearance_from_existing_ft=constraints.min_building_separation_ft or 0.0,
        front_edge_index=req.front_edge_index,
    )
    if adu_type_key == "jadu":
        _apply_jadu_buildable_zone(site_model)
    # Embed constraints so the checklist and frontend both read the resolved values.
    site_model["applied_constraints"] = dataclasses.asdict(constraints)
    site_model["standards"] = req.standards
    site_model["adu_type"] = adu_type_key
    site_model["adu_stories"] = req.adu_stories
    if state_fit_inputs:
        site_model["state_fit_inputs"] = state_fit_inputs

    checklist = adapter.build_checklist(
        site_model,
        zoning=zoning_result,
        general_plan=gp_result,
        designations=typed_designations,
        property_stats=property_stats,
        adu_type=req.adu_type,
        permits=permits_result,
        code_enforcement=ce_result,
        standards=req.standards,
        adu_stories=req.adu_stories,
    )
    stages.append(_site_model_stage(building_source, adu_type_key))

    data_warnings = _collect_data_warnings(
        zoning_result, gp_result, typed_designations, permits_result, ce_result,
    )

    return {
        "job_id": _make_job_id(adapter.name, parcel_id, geocode.matched_address, lat, lon),
        "city": adapter.name,
        "city_display_name": adapter.display_name,
        "address": site_model["address"],
        "latitude": lat,
        "longitude": lon,
        "parcel_geojson": parcel_fc,
        "building_geojson": building_fc,
        "site_model": site_model,
        "site_model_url": None,
        "data_warnings": data_warnings,
        "zoning": {
            "district": adapter.serialize_zoning(zoning_result),
            "general_plan": adapter.serialize_general_plan(gp_result),
            "designations": {
                k: adapter.serialize_designation(v) for k, v in typed_designations.items()
            },
        },
        "permits": adapter.serialize_permits(permits_result),
        "code_enforcement": adapter.serialize_code_enforcement(ce_result),
        "checklist": {"items": checklist, "city": adapter.name},
        "property_stats": property_stats,
        "zip_context": zip_context,
        "financing": financing,
        "stages": stages,
        "debug": {
            "mode": f"live_{adapter.name}_address",
            "city": adapter.name,
            "address_input": req.address,
            "address_normalized": geocode.normalized_input,
            "address_matched": geocode.matched_address,
            "geocode_score": geocode.score,
            "parcel_source": parcel_source,
            "building_source": building_source,
        },
    }
