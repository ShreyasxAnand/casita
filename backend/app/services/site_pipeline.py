"""End-to-end pipeline for `POST /api/site`.

Composes the geocoder, parcel/building clients, zoning + designation
lookups, and the HomeHarvest property data into one response. Keeping this
out of `main.py` lets routes stay thin and lets the pipeline be exercised
in tests without spinning up FastAPI.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

import httpx
from fastapi import HTTPException

from app.clients import designations, geocoder
from app.clients.buildings import fetch_buildings_for_parcel
from app.clients.parcels import fetch_parcel_at_point, parcel_apn
from app.clients.zoning import fetch_general_plan, fetch_zoning
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
from app.rules import build_checklist
from app.site_model import build_site_model

logger = logging.getLogger(__name__)


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


async def _zoning_block(
    client: httpx.AsyncClient, latitude: float, longitude: float
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Fetch zoning + GP concurrently and return both plus stage entries."""
    start = time.perf_counter()
    zoning, general_plan = await asyncio.gather(
        fetch_zoning(client, latitude, longitude),
        fetch_general_plan(client, latitude, longitude),
    )
    return zoning, general_plan, [
        stage(
            "fetch_zoning",
            start,
            f"Loaded zoning district {zoning.get('zoning') or 'unknown'} and "
            f"General Plan {general_plan.get('gp_designation') or 'unknown'}.",
            {"zoning": zoning.get("zoning"), "gp": general_plan.get("gp_designation")},
        ),
    ]


async def _designations_block(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    parcel_feature: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    start = time.perf_counter()
    result = await designations.fetch_all(client, latitude, longitude, parcel_feature)
    return result, stage(
        "fetch_designations", start,
        "Loaded flood, geohazard, historic, WUI, and heritage-tree designation layers.",
        result,
    )


async def _property_data_block(
    req: SiteRequest, geocode: dict[str, Any], zip_code: str, lat: float, lon: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run HomeHarvest lookups in worker threads, then build pro-forma."""
    prop_task = asyncio.create_task(
        asyncio.to_thread(get_property_by_address, geocode["matched_address"])
    )
    zip_task = (
        asyncio.create_task(asyncio.to_thread(search_properties_by_zip, zip_code, 30))
        if zip_code else None
    )

    start = time.perf_counter()
    try:
        prop_data = await prop_task
    except Exception as exc:  # HomeHarvest raises a wide variety of errors
        logger.warning("HomeHarvest property fetch failed: %s", exc)
        prop_data = None
    try:
        zip_props = await zip_task if zip_task else []
    except Exception as exc:
        logger.warning("HomeHarvest zip fetch failed: %s", exc)
        zip_props = []
    if not prop_data and zip_props:
        prop_data = find_subject_in_zip(geocode["matched_address"], zip_props)

    attrs = geocode.get("attributes") or {}
    city = str(attrs.get("City") or "San Jose")
    state = str(attrs.get("Region") or "CA")
    property_stats = build_property_stats(
        prop_data,
        address=geocode["matched_address"],
        city=city, state=state, zip_code=zip_code,
        latitude=lat, longitude=lon,
        neighborhood_avg_year_built=avg_year_built(zip_props),
    )
    zip_context = build_zip_context(zip_code, city, state, zip_props)
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


def _make_job_id(prefix: str, parcel_fc: dict[str, Any], address: str, lat: float, lon: float) -> str:
    """Derive a stable job ID from the parcel APN, falling back to a short
    hash of the address + coordinates when no APN is available.
    """
    apn = parcel_apn(parcel_fc)
    if apn:
        return f"{prefix}-{apn}"
    digest = hashlib.sha1(f"{address}|{lat}|{lon}".encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _site_model_stage(building_source: str) -> dict[str, Any]:
    """Synthetic stage entry that reports on the local 3D-geometry build."""
    detail = (
        "Generated parcel-local 3D geometry from live outlines."
        if building_source != "not_found"
        else "Generated parcel-local geometry. No primary-residence outline found — "
             "buildable zone = full setback-eroded parcel."
    )
    return {
        "name": "site_model",
        "status": "ok",
        "duration_ms": 0,
        "detail": detail,
        "data": {"building_source": building_source},
        "log_tail": None,
    }


async def run_site_pipeline(
    client: httpx.AsyncClient, req: SiteRequest
) -> dict[str, Any]:
    """Full live-address pipeline used by `POST /api/site`.

    Reads top-to-bottom as five phases:
      1. Geocode the address.
      2. Kick HomeHarvest lookups off in worker threads (overlap with GIS).
      3. Fetch parcel + building outlines from San Jose GIS.
      4. Fetch zoning, General Plan, and designation layers.
      5. Build the site model, derive job id + checklist, assemble response.
    """
    stages: list[dict[str, Any]] = []

    # 1. Geocode ─────────────────────────────────────────────────────────
    start = time.perf_counter()
    geocode = await geocoder.geocode_san_jose_address(client, req.address)
    lat = float(geocode["latitude"])
    lon = float(geocode["longitude"])
    address_label = geocode["matched_address"]
    zip_code = str((geocode.get("attributes") or {}).get("Postal") or "").strip()
    stages.append(stage(
        "geocode_address", start,
        f"Matched address to {address_label}.",
        {"score": geocode.get("score"), "latitude": lat, "longitude": lon},
    ))

    # 2. HomeHarvest (overlapped with GIS calls below) ───────────────────
    prop_data_task = asyncio.create_task(
        _property_data_block(req, geocode, zip_code, lat, lon)
    )

    # 3. Parcel + buildings ──────────────────────────────────────────────
    start = time.perf_counter()
    parcel_feature, parcel_source = await fetch_parcel_at_point(client, lat, lon)
    parcel_fc = _feature_collection([parcel_feature])
    stages.append(stage(
        "fetch_san_jose_parcel", start,
        f"Loaded parcel from San Jose GIS using {parcel_source}.",
        {"feature_count": 1, "source": parcel_source},
    ))

    start = time.perf_counter()
    building_fc, building_source = await fetch_buildings_for_parcel(client, parcel_feature)
    feature_count = len(building_fc["features"])
    stages.append(stage(
        "fetch_building_outlines", start,
        (
            f"Loaded {feature_count} building outline(s) from {building_source}."
            if feature_count > 0
            else "No building outlines found — buildable zone will use the full eroded parcel."
        ),
        {"feature_count": feature_count, "source": building_source},
    ))

    # 4. Zoning + designations ───────────────────────────────────────────
    try:
        zoning, general_plan, zoning_stages = await _zoning_block(client, lat, lon)
        stages.extend(zoning_stages)
    except HTTPException as exc:
        zoning, general_plan = {}, {}
        stages.append(warn_stage("fetch_zoning", f"Zoning lookup failed: {exc.detail}"))

    try:
        designations_payload, dstage = await _designations_block(client, lat, lon, parcel_feature)
        stages.append(dstage)
    except HTTPException as exc:
        designations_payload = {}
        stages.append(warn_stage("fetch_designations", f"Designation lookup failed: {exc.detail}"))

    property_stats, zip_context, financing, prop_stage = await prop_data_task
    stages.append(prop_stage)

    # 5. Site model, checklist, response ─────────────────────────────────
    site_model = build_site_model(
        address=address_label,
        latitude=lat,
        longitude=lon,
        parcel_fc=parcel_fc,
        building_fc=building_fc,
        adu_width_ft=req.adu_width_ft,
        adu_depth_ft=req.adu_depth_ft,
    )
    checklist = build_checklist(
        site_model,
        zoning=zoning,
        general_plan=general_plan,
        designations=designations_payload,
        property_stats=property_stats,
        adu_type=req.adu_type,
    )
    stages.append(_site_model_stage(building_source))

    return {
        "job_id": _make_job_id("san-jose", parcel_fc, address_label, lat, lon),
        "address": site_model["address"],
        "latitude": lat,
        "longitude": lon,
        "parcel_geojson": parcel_fc,
        "building_geojson": building_fc,
        "site_model": site_model,
        "site_model_url": None,
        "zoning": {
            "district": zoning,
            "general_plan": general_plan,
            "designations": designations_payload,
        },
        "checklist": {"san_jose_checklist": checklist},
        "property_stats": property_stats,
        "zip_context": zip_context,
        "financing": financing,
        "stages": stages,
        "debug": {
            "mode": "live_san_jose_address",
            "address_input": req.address,
            "address_normalized": geocode["normalized"],
            "address_matched": address_label,
            "geocode_score": geocode.get("score"),
            "parcel_source": parcel_source,
            "building_source": building_source,
        },
    }
