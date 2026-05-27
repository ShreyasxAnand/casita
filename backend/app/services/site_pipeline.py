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
from app.clients.code_enforcement import CodeEnforcementData, fetch_code_enforcement
from app.clients.designations import DesignationData
from app.clients.geocoder import GeocodeResult
from app.clients.parcels import fetch_parcel_at_point, parcel_apn
from app.clients.permits import PermitsData, fetch_permits
from app.clients.zoning import fetch_general_plan, fetch_zoning
from app.rules.zoning import GeneralPlanData, ZoningData
from app.models import SiteRequest, stage, warn_stage
from app.result import FetchResult
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


def _serialise_designation(r: FetchResult[DesignationData]) -> dict[str, Any]:
    d: dict[str, Any] = {"status": r.status.value, "source": r.source}
    if r.data is not None:
        d["present"] = r.data.present
        d["detail"] = r.data.detail
    if r.error is not None:
        d["error"] = r.error
    return d


def _serialise_zoning_result(r: FetchResult[ZoningData]) -> dict[str, Any]:
    d: dict[str, Any] = {"status": r.status.value, "source": r.source}
    if r.data is not None:
        d.update({
            "zoning": r.data.zoning,
            "zoning_abbrev": r.data.zoning_abbrev,
            "zoning_full_name": r.data.zoning_full_name,
            "facility_id": r.data.facility_id,
            "rezoning_file": r.data.rezoning_file,
            "pd_use": r.data.pd_use,
            "pd_density": r.data.pd_density,
            "developed_as_pd": r.data.developed_as_pd,
            "approval_date": r.data.approval_date,
            "notes": r.data.notes,
        })
    if r.error is not None:
        d["error"] = r.error
    return d


def _serialise_gp_result(r: FetchResult[GeneralPlanData]) -> dict[str, Any]:
    d: dict[str, Any] = {"status": r.status.value, "source": r.source}
    if r.data is not None:
        d.update({
            "gp_designation": r.data.gp_designation,
            "gp_abbreviation": r.data.gp_abbreviation,
            "notes": r.data.notes,
            "last_update": r.data.last_update,
        })
    if r.error is not None:
        d["error"] = r.error
    return d


def _collect_data_warnings(
    zoning_result: FetchResult[ZoningData],
    gp_result: FetchResult[GeneralPlanData],
    typed_designations: dict[str, FetchResult[DesignationData]],
    permits_result: FetchResult[PermitsData] | None = None,
    ce_result: FetchResult[CodeEnforcementData] | None = None,
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


def _serialise_permits_result(r: FetchResult[PermitsData]) -> dict[str, Any]:
    d: dict[str, Any] = {"status": r.status.value, "source": r.source}
    if r.error:
        d["error"] = r.error
    if r.data:
        d["active_count"] = r.data.active_count
        d["finalized_count"] = r.data.finalized_count
        d["total_count"] = len(r.data.records)
        d["has_pool_permit"] = r.data.has_pool_permit
        d["pool_permits"] = [
            {
                "folder_num": p.folder_num,
                "work_desc": p.work_desc,
                "sub_desc": p.sub_desc,
                "status": p.status,
                "issue_date": p.issue_date,
                "final_date": p.final_date,
            }
            for p in r.data.pool_permits
        ]
    return d


def _serialise_ce_result(r: FetchResult[CodeEnforcementData]) -> dict[str, Any]:
    d: dict[str, Any] = {"status": r.status.value, "source": r.source}
    if r.error:
        d["error"] = r.error
    if r.data:
        d["complaint_count"] = r.data.complaint_count
        d["investigation_count"] = r.data.investigation_count
        d["total_count"] = r.data.total_count
        d["issues"] = [
            {
                "issue_type": i.issue_type,
                "identifier": i.identifier,
                "description": i.description,
                "open_date": i.open_date,
                "status": i.status,
                "program": i.program,
            }
            for i in r.data.issues
        ]
    return d


async def _permits_and_enforcement_block(
    client: httpx.AsyncClient,
    apn: str | None,
    lat: float,
    lon: float,
) -> tuple[FetchResult[PermitsData], FetchResult[CodeEnforcementData], list[dict[str, Any]]]:
    """Fetch permits (pool check) and code-enforcement data concurrently."""
    start = time.perf_counter()
    permits_result, ce_result = await asyncio.gather(
        fetch_permits(client, apn or ""),
        fetch_code_enforcement(client, apn or "", lat, lon),
    )
    permit_summary = (
        f"{permits_result.data.active_count} active, "
        f"{permits_result.data.finalized_count} finalized."
        if permits_result.is_ok and permits_result.data
        else permits_result.error or permits_result.status.value
    )
    ce_summary = (
        f"{ce_result.data.total_count} issue(s) "
        f"({ce_result.data.complaint_count} complaint(s), "
        f"{ce_result.data.investigation_count} investigation(s))."
        if ce_result.is_ok and ce_result.data
        else "none" if ce_result.is_absent
        else ce_result.error or ce_result.status.value
    )
    any_failed = permits_result.is_failed or ce_result.is_failed
    return permits_result, ce_result, [
        stage(
            "fetch_permits_enforcement", start,
            f"Permits: {permit_summary} Code enforcement: {ce_summary}",
            {
                "permits_status": permits_result.status.value,
                "ce_status": ce_result.status.value,
                "permit_active": permits_result.data.active_count if permits_result.data else None,
                "permit_finalized": permits_result.data.finalized_count if permits_result.data else None,
                "ce_total": ce_result.data.total_count if ce_result.data else None,
                "ce_complaints": ce_result.data.complaint_count if ce_result.data else None,
                "ce_investigations": ce_result.data.investigation_count if ce_result.data else None,
            },
            status="warn" if any_failed else "ok",
        ),
    ]


async def _zoning_block(
    client: httpx.AsyncClient, latitude: float, longitude: float
) -> tuple[FetchResult[ZoningData], FetchResult[GeneralPlanData], list[dict[str, Any]]]:
    """Fetch zoning + GP concurrently; failures are captured in FetchResult, not raised."""
    start = time.perf_counter()
    zoning_result, gp_result = await asyncio.gather(
        fetch_zoning(client, latitude, longitude),
        fetch_general_plan(client, latitude, longitude),
    )
    zoning_code = zoning_result.data.zoning if zoning_result.data else None
    gp_desig = gp_result.data.gp_designation if gp_result.data else None
    any_failed = zoning_result.is_failed or gp_result.is_failed
    if any_failed:
        parts = []
        if zoning_result.is_failed:
            parts.append(f"Zoning failed: {zoning_result.error}")
        else:
            parts.append(f"Zoning: {zoning_code or 'unknown'}")
        if gp_result.is_failed:
            parts.append(f"GP failed: {gp_result.error}")
        else:
            parts.append(f"GP: {gp_desig or 'unknown'}")
        detail = ". ".join(parts) + "."
    else:
        detail = (
            f"Loaded zoning district {zoning_code or 'unknown'} and "
            f"General Plan {gp_desig or 'unknown'}."
        )
    return zoning_result, gp_result, [
        stage(
            "fetch_zoning", start, detail,
            {
                "zoning": zoning_code,
                "gp": gp_desig,
                "zoning_status": zoning_result.status.value,
                "gp_status": gp_result.status.value,
            },
            status="warn" if any_failed else "ok",
        ),
    ]


async def _designations_block(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    parcel_feature: dict[str, Any],
) -> tuple[dict[str, FetchResult[DesignationData]], dict[str, Any]]:
    start = time.perf_counter()
    typed = await designations.fetch_all(client, latitude, longitude, parcel_feature)
    serialised = {k: _serialise_designation(v) for k, v in typed.items()}
    return typed, stage(
        "fetch_designations", start,
        "Loaded flood, geohazard, historic, WUI, and heritage-tree designation layers.",
        serialised,
    )


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
    lat, lon = geocode.latitude, geocode.longitude
    stages.append(stage(
        "geocode_address", start,
        f"Matched '{geocode.matched_address}' (score {geocode.score:.0f}/100).",
        {"score": geocode.score, "latitude": lat, "longitude": lon},
    ))

    # 2. HomeHarvest (overlapped with GIS calls below) ───────────────────
    prop_data_task = asyncio.create_task(
        _property_data_block(req, geocode)
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
    zoning_result, gp_result, zoning_stages = await _zoning_block(client, lat, lon)
    stages.extend(zoning_stages)

    try:
        typed_designations, dstage = await _designations_block(client, lat, lon, parcel_feature)
        stages.append(dstage)
    except HTTPException as exc:
        typed_designations: dict[str, FetchResult[DesignationData]] = {}
        stages.append(warn_stage("fetch_designations", f"Designation lookup failed: {exc.detail}"))

    apn = parcel_apn(parcel_fc)
    permits_result, ce_result, pe_stages = await _permits_and_enforcement_block(
        client, apn, lat, lon
    )
    stages.extend(pe_stages)

    property_stats, zip_context, financing, prop_stage = await prop_data_task
    stages.append(prop_stage)

    # 5. Site model, checklist, response ─────────────────────────────────
    site_model = build_site_model(
        address=geocode.matched_address,
        latitude=lat,
        longitude=lon,
        parcel_fc=parcel_fc,
        building_fc=building_fc,
        adu_width_ft=req.adu_width_ft,
        adu_depth_ft=req.adu_depth_ft,
    )
    checklist = build_checklist(
        site_model,
        zoning=zoning_result,
        general_plan=gp_result,
        designations=typed_designations,
        property_stats=property_stats,
        adu_type=req.adu_type,
        permits=permits_result,
        code_enforcement=ce_result,
    )
    stages.append(_site_model_stage(building_source))

    data_warnings = _collect_data_warnings(
        zoning_result, gp_result, typed_designations, permits_result, ce_result
    )

    return {
        "job_id": _make_job_id("san-jose", parcel_fc, geocode.matched_address, lat, lon),
        "address": site_model["address"],
        "latitude": lat,
        "longitude": lon,
        "parcel_geojson": parcel_fc,
        "building_geojson": building_fc,
        "site_model": site_model,
        "site_model_url": None,
        "data_warnings": data_warnings,
        "zoning": {
            "district": _serialise_zoning_result(zoning_result),
            "general_plan": _serialise_gp_result(gp_result),
            "designations": {k: _serialise_designation(v) for k, v in typed_designations.items()},
        },
        "permits": _serialise_permits_result(permits_result),
        "code_enforcement": _serialise_ce_result(ce_result),
        "checklist": {"san_jose_checklist": checklist},
        "property_stats": property_stats,
        "zip_context": zip_context,
        "financing": financing,
        "stages": stages,
        "debug": {
            "mode": "live_san_jose_address",
            "address_input": req.address,
            "address_normalized": geocode.normalized_input,
            "address_matched": geocode.matched_address,
            "geocode_score": geocode.score,
            "parcel_source": parcel_source,
            "building_source": building_source,
        },
    }
