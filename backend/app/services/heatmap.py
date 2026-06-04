"""Batch processing for contractor ADU lead scores and heatmap data."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform, unary_union
from shapely.strtree import STRtree

from app.cities.san_jose.zoning import (
    SAN_JOSE_GENERAL_PLAN_QUERY_URL,
    SAN_JOSE_ZONING_QUERY_URL,
    zoning_full_name,
    zoning_ordinance_reference,
)
from app.cities.san_jose.permits import is_adu_permit_text, normalize_apn
from app.services import arcgis
from app.services.arcgis import TO_UTM
from app.services.arcgis_geometry import feature_to_geojson

logger = logging.getLogger(__name__)

# San Jose layers
PARCELS_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/OPN/"
    "OPN_OpenDataService/MapServer/270/query"
)
BUILDINGS_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/DPW/"
    "DPW_BasemapServiceWGS/MapServer/21/query"
)
PERMITS_ACTIVE_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/PLN/"
    "PLN_PermitsAndComplaints/MapServer/8/query"
)
PERMITS_EXPIRED_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/PLN/"
    "PLN_PermitsAndComplaints/MapServer/9/query"
)

M2_TO_FT2 = 10.7639104167
ARCGIS_PAGE_SIZE = 2000
MAX_HEATMAP_FEATURES = 50000
MIN_PRIMARY_BUILDING_FT2 = 300.0

# ADU capacity cap: CA §66310 limits a detached ADU to 1,200 sq ft. We score
# buildable area up to 2,500 sq ft (enough to site the legal max plus clearance).
# Any raw buildable beyond this adds no ADU siting value and inflates scores.
ADU_BUILDABLE_SCORING_CAP_FT2 = 2500.0

# Openness cap: normalize building coverage against a typical SFR lot ceiling
# rather than the raw parcel area. Without this, a 1M sq ft parcel with 0.1%
# coverage gets a near-perfect openness score despite being an outlier parcel
# (farm, institutional property, large PD) rather than a residential lot.
LOT_OPENNESS_AREA_CAP_FT2 = 15000.0

# Confidence threshold above which we flag the parcel as an oversized outlier.
# 43,560 sq ft = 1 acre; typical San Jose SFR lots are 4,000–12,000 sq ft.
OVERSIZED_PARCEL_THRESHOLD_FT2 = 43560.0
PARCEL_OUT_FIELDS = "OBJECTID,PARCELID,APN,PARCELTYPE,FEATURECLASS"
PERMIT_OUT_FIELDS = "WORKDESC,SUBDESC,FINALDATE,APN"
ZONING_OUT_FIELDS = "ZONING,ZONINGABBREV,PDUSE,DEVELOPEDASPD,NOTES"
GENERAL_PLAN_OUT_FIELDS = "GPDESIGNATION,GPABBREVIATION"

_RESIDENTIAL_PD_HINTS = (
    "RESIDENTIAL",
    "RESIDENCE",
    "SINGLE FAMILY",
    "MULTI-FAMILY",
    "MULTIFAMILY",
    "DWELLING",
)
_NON_LEAD_PD_HINTS = (
    "SCHOOL",
    "PUBLIC",
    "PARK",
    "OPEN SPACE",
    "COMMERCIAL",
    "INDUSTRIAL",
    "OFFICE",
    "CIVIC",
)
_RESIDENTIAL_PD_PATTERNS = tuple(
    re.compile(rf"(?<![A-Z0-9]){re.escape(phrase)}(?![A-Z0-9])")
    for phrase in _RESIDENTIAL_PD_HINTS
)
_NON_LEAD_PD_PATTERNS = tuple(
    re.compile(rf"(?<![A-Z0-9]){re.escape(phrase)}(?![A-Z0-9])")
    for phrase in _NON_LEAD_PD_HINTS
)


async def _query_all_features(
    client: httpx.AsyncClient,
    url: str,
    *,
    geometry: str,
    geometry_type: arcgis.GeometryType,
    out_fields: str = "*",
    return_geometry: bool = True,
    where: str = "1=1",
    order_by_fields: str = "OBJECTID",
    page_size: int | None = None,
    max_features: int = MAX_HEATMAP_FEATURES,
    stage: str,
) -> list[dict[str, Any]]:
    """Page through an ArcGIS layer so ZIP scans do not stop at one record page."""
    features: list[dict[str, Any]] = []
    offset = 0
    page_limit = page_size or ARCGIS_PAGE_SIZE
    while len(features) < max_features:
        page = await arcgis.query_features(
            client,
            url,
            geometry=geometry,
            geometry_type=geometry_type,
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            max_records=min(page_limit, max_features - len(features)),
            result_offset=offset,
            order_by_fields=order_by_fields,
            stage=stage,
        )
        if not page:
            break
        features.extend(page)
        if len(page) < page_limit:
            break
        offset += len(page)
    return features


def _is_adu_permit(attrs: dict[str, Any]) -> bool:
    return is_adu_permit_text(attrs.get("WORKDESC"), attrs.get("SUBDESC"))


def _permit_status(active: bool, expired: bool, finalized: bool) -> str:
    if finalized:
        return "finalized"
    if active:
        return "active"
    if expired:
        return "expired"
    return "none"


def _score_color_bucket(score: float) -> str:
    if score >= 80:
        return "high"
    if score >= 60:
        return "medium"
    if score > 0:
        return "low"
    return "blocked"


def _geojson_geom(feature: dict[str, Any]) -> Any | None:
    feat = feature_to_geojson(feature)
    return feat.get("geometry") if feat else None


def _feature_records(features: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], STRtree | None]:
    records: list[dict[str, Any]] = []
    geoms = []
    for raw in features:
        geom_json = _geojson_geom(raw)
        if not geom_json:
            continue
        try:
            geom = shape(geom_json).buffer(0)
        except Exception:
            continue
        if geom.is_empty:
            continue
        records.append({"geometry": geom, "attributes": raw.get("attributes") or {}})
        geoms.append(geom)
    return records, STRtree(geoms) if geoms else None


def _best_attrs_for_geom(
    geom,
    records: list[dict[str, Any]],
    index: STRtree | None,
) -> dict[str, Any]:
    if not index or not records:
        return {}

    point = geom.representative_point()
    for i in index.query(point):
        record = records[int(i)]
        if record["geometry"].covers(point):
            return record["attributes"]

    best_attrs: dict[str, Any] = {}
    best_area = 0.0
    for i in index.query(geom):
        record = records[int(i)]
        try:
            area = record["geometry"].intersection(geom).area
        except Exception:
            continue
        if area > best_area:
            best_area = area
            best_attrs = record["attributes"]
    return best_attrs


def _zoning_code(attrs: dict[str, Any]) -> str:
    return str(attrs.get("ZONING") or attrs.get("ZONINGABBREV") or "").strip().upper()


def _pd_text(attrs: dict[str, Any]) -> str:
    return " ".join(
        str(attrs.get(key) or "") for key in ("PDUSE", "DEVELOPEDASPD", "NOTES")
    ).upper()


def _contains_any_pattern(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _is_residential_pd(zoning_attrs: dict[str, Any]) -> bool:
    text = _pd_text(zoning_attrs)
    if _contains_any_pattern(text, _NON_LEAD_PD_PATTERNS):
        return False
    return _contains_any_pattern(text, _RESIDENTIAL_PD_PATTERNS)


# San Jose mixed-use zone prefixes that permit residential use and are therefore
# ADU-eligible under CA Gov. Code §66310 (formerly §65852.2). We treat MU-* and
# DC-* as "eligible with verification" rather than excluding them.
_MIXED_USE_ZONE_PREFIXES = ("MU", "DC")

# GP designation substrings that indicate residential or mixed-use land use.
# Mirrors _ELIGIBLE_GP_TOKENS in zoning.py; kept here so heatmap.py can use it
# independently without importing from the single-site pipeline.
_RESIDENTIAL_GP_TOKENS = (
    "RESIDENTIAL NEIGHBORHOOD",
    "MIXED-USE NEIGHBORHOOD",
    "URBAN VILLAGE",
    "URBAN RESIDENTIAL",
    "TRANSIT RESIDENTIAL",
    "RURAL RESIDENTIAL",
    "DOWNTOWN",
    "MIXED-USE COMMERCIAL",
)


def _gp_is_residential(gp: str) -> bool:
    gp_upper = gp.upper()
    return any(token in gp_upper for token in _RESIDENTIAL_GP_TOKENS)


def _eligibility_from_zoning(
    zoning_attrs: dict[str, Any],
    gp_attrs: dict[str, Any],
    *,
    has_primary_building: bool,
) -> tuple[bool, str, str, str, float]:
    """Return eligibility, reason, zoning code/name, and zoning opportunity score.

    has_primary_building=False is NOT a hard gate here — it degrades the zoning
    score (fewer points available) and lowers confidence (handled by _confidence),
    but zoning eligibility is assessed independently. This correctly treats a
    missing footprint as a data gap rather than a legal verdict.
    """
    code = _zoning_code(zoning_attrs)
    name = zoning_full_name(code) if code else "Unknown"
    gp = str(gp_attrs.get("GPDESIGNATION") or "").strip()

    # --- Clear residential zones (R-1, R-2, R-M, R-MH) ---
    if code.startswith("R-1"):
        if not has_primary_building:
            return (True,
                    f"R-1 zone ({code}); building footprint not detected in batch layer — verify.",
                    code, name, 4.0)
        return True, f"Residential zoning candidate: {code}.", code, name, 8.0

    if code.startswith(("R-2", "R-M", "R-MH")):
        if not has_primary_building:
            return (True,
                    f"{code} zone; building footprint not detected in batch layer — verify.",
                    code, name, 3.5)
        return True, f"Residential zoning candidate: {code}.", code, name, 7.0

    # --- Planned Development ---
    if code.startswith("PD") or "(PD)" in code:
        if _is_residential_pd(zoning_attrs):
            if not has_primary_building:
                return (True,
                        f"Residential PD zone ({code}); building footprint not detected — verify.",
                        code, name, 2.5)
            return True, f"Residential planned-development candidate: {code}.", code, name, 4.5
        return False, f"PD zoning is not clearly residential: {code or 'unknown'}.", code, name, 0.0

    # --- Mixed-use zones (MU-N, DC, etc.) ---
    # CA §66310 allows ADUs on any lot in a zone that permits residential use,
    # including mixed-use zones. We pass these through at lower confidence.
    if code.startswith(_MIXED_USE_ZONE_PREFIXES):
        if not has_primary_building:
            return (True,
                    f"Mixed-use zone ({code}); residential use and building presence require on-site verification.",
                    code, name, 2.0)
        return (True,
                f"Mixed-use zone ({code}) — residential ADU permitted under CA §66310; verify use table.",
                code, name, 5.0)

    # --- Known non-residential code, but GP suggests residential land use ---
    # This surfaces rezoning-in-progress or data-lag situations honestly.
    if code and _gp_is_residential(gp):
        return (True,
                f"Zone {code} appears non-residential but General Plan '{gp}' indicates residential land use — verify.",
                code, name, 2.0)

    # --- Definite non-residential: exclude ---
    if code:
        return False, f"Non-residential zoning excluded: {code}.", code, name, 0.0

    # --- No zoning code: fall back to General Plan ---
    if gp:
        if _gp_is_residential(gp):
            if not has_primary_building:
                return (True,
                        f"No zoning code; General Plan '{gp}' suggests residential — verify parcel.",
                        code, name, 1.5)
            return (True,
                    f"No zoning code; General Plan '{gp}' indicates residential eligibility.",
                    code, name, 3.0)
        return False, f"No zoning code; General Plan '{gp}' is non-residential.", code, name, 0.0

    return False, "No zoning or General Plan designation found.", code, name, 0.0


def _score_component(
    label: str,
    score: float,
    max_score: float,
    detail: str,
) -> dict[str, Any]:
    return {
        "label": label,
        "score": round(score, 1),
        "max": max_score,
        "detail": detail,
    }


def _score_group(
    score: float,
    max_score: float,
    components: list[dict[str, Any]],
    *,
    note: str | None = None,
) -> dict[str, Any]:
    group = {
        "score": round(score, 1),
        "max": max_score,
        "components": components,
    }
    if note:
        group["note"] = note
    return group


def _ramp_score(value: float, *, start: float, full: float, max_score: float) -> float:
    if value <= start:
        return 0.0
    if value >= full:
        return max_score
    return ((value - start) / (full - start)) * max_score


def _lot_fit_score(parcel_area_ft2: float) -> float:
    """Score the lot-size band contractors can repeatedly sell and build."""
    if parcel_area_ft2 < 2500.0:
        return 0.5
    if parcel_area_ft2 < 4500.0:
        return 1.5 + ((parcel_area_ft2 - 2500.0) / 2000.0) * 1.5
    if parcel_area_ft2 <= 9000.0:
        return 4.0
    if parcel_area_ft2 <= 16000.0:
        return 4.0 - ((parcel_area_ft2 - 9000.0) / 7000.0) * 2.0
    return 1.5


def _physical_score_breakdown(
    *,
    buildable_area_ft2: float,
    parcel_area_ft2: float,
    existing_coverage_ft2: float,
    has_primary_building: bool,
) -> tuple[float, float, dict[str, Any]]:
    # Raw coverage ratio for honest display.
    coverage_ratio = existing_coverage_ft2 / parcel_area_ft2 if parcel_area_ft2 > 0 else 1.0

    # Buildable area capped at the ADU legal envelope for scoring.
    # Buildable space beyond this point adds no additional ADU siting value.
    scored_buildable = min(buildable_area_ft2, ADU_BUILDABLE_SCORING_CAP_FT2)
    space_score = min(28.0, (scored_buildable / 1000.0) * 28.0)
    buildable_cap_note = (
        f" (scored at {round(ADU_BUILDABLE_SCORING_CAP_FT2):,} sq ft cap; CA max detached ADU is 1,200 sq ft)"
        if buildable_area_ft2 > ADU_BUILDABLE_SCORING_CAP_FT2 else ""
    )

    # Openness scored against a typical SFR lot ceiling, not raw parcel area.
    # Prevents huge outlier parcels (>1 acre) from earning near-perfect openness
    # scores via near-zero coverage ratios that are irrelevant to ADU siting.
    openness_denom = min(parcel_area_ft2, LOT_OPENNESS_AREA_CAP_FT2)
    scored_coverage = existing_coverage_ft2 / openness_denom if openness_denom > 0 else 1.0
    openness_score = max(0.0, min(18.0, (1.0 - scored_coverage) * 18.0))

    # Lot size: ramp up through the contractor sweet-spot, then penalize outlier
    # large lots (mirrors _lot_fit_score in opportunity scoring).
    if parcel_area_ft2 <= 6000.0:
        lot_score = min(8.0, (parcel_area_ft2 / 6000.0) * 8.0)
    elif parcel_area_ft2 <= 12000.0:
        lot_score = 8.0
    elif parcel_area_ft2 <= 30000.0:
        lot_score = 8.0 - ((parcel_area_ft2 - 12000.0) / 18000.0) * 4.0
    else:
        lot_score = 2.0  # >30k sqft: likely not a standard residential lot

    primary_score = 6.0 if has_primary_building else 0.0
    total = space_score + openness_score + lot_score + primary_score
    return coverage_ratio, total, _score_group(total, 60.0, [
        _score_component(
            "Buildable area",
            space_score,
            28.0,
            f"{round(buildable_area_ft2):,} sq ft after batch setback screen{buildable_cap_note}.",
        ),
        _score_component(
            "Open lot area",
            openness_score,
            18.0,
            f"{coverage_ratio:.0%} existing building coverage"
            + (f" (scored against {round(LOT_OPENNESS_AREA_CAP_FT2):,} sq ft ceiling)" if parcel_area_ft2 > LOT_OPENNESS_AREA_CAP_FT2 else "") + ".",
        ),
        _score_component(
            "Lot size",
            lot_score,
            8.0,
            f"{round(parcel_area_ft2):,} sq ft parcel.",
        ),
        _score_component(
            "Primary building",
            primary_score,
            6.0,
            "Primary building footprint found." if has_primary_building
            else "Primary building footprint not confirmed.",
        ),
    ])


def _opportunity_score_breakdown(
    *,
    zoning_score: float,
    zone_code: str,
    adu_status: str,
    buildable_area_ft2: float,
    parcel_area_ft2: float,
    coverage_ratio: float,
) -> tuple[float, dict[str, Any]]:
    if adu_status in ("active", "finalized"):
        permit_score = 0.0
    else:
        permit_score = 10.0 if adu_status == "none" else 3.0
    capacity_score = _ramp_score(
        buildable_area_ft2,
        start=450.0,
        full=2250.0,
        max_score=9.0,
    )
    openness_score = max(0.0, min(3.5, (1.0 - coverage_ratio) * 3.5))
    lot_fit_score = _lot_fit_score(parcel_area_ft2)
    total = zoning_score + permit_score + capacity_score + openness_score + lot_fit_score
    return total, _score_group(total, 40.0, [
        _score_component(
            "Zoning fit",
            zoning_score,
            10.0,
            f"{zone_code or 'Unknown'} zoning screen; batch scoring reserves manual-review headroom.",
        ),
        _score_component(
            "Permit signal",
            permit_score,
            12.0,
            f"ADU permit status from ZIP scan: {adu_status}; APN-level lookup still appears in the sidebar.",
        ),
        _score_component(
            "Capacity",
            capacity_score,
            10.0,
            f"{round(buildable_area_ft2):,} sq ft batch buildable area; exact frontage and utility constraints are unknown.",
        ),
        _score_component(
            "Open space",
            openness_score,
            4.0,
            f"{coverage_ratio:.0%} building coverage.",
        ),
        _score_component(
            "Lot fit",
            lot_fit_score,
            4.0,
            "Lot size is in the repeatable contractor target band." if lot_fit_score == 4.0
            else "Lot size is outside the preferred repeatable target band.",
        ),
    ], note="A batch lead should rarely score 40/40; owner intent, frontage, utilities, and permit details still need verification.")


def _excluded_opportunity_breakdown(reason: str) -> dict[str, Any]:
    return _score_group(
        0.0,
        40.0,
        [_score_component("Qualification gate", 0.0, 40.0, reason)],
        note="Excluded parcels are kept for audit visibility but are not scored as contractor targets.",
    )


def _confidence(
    *,
    zone_code: str,
    gp_attrs: dict[str, Any],
    has_primary_building: bool,
    adu_status: str,
    parcel_area_ft2: float = 0.0,
) -> dict[str, Any]:
    score = 85.0
    reasons = [
        "Batch screen only; frontage and exact front setback are not inferred.",
    ]
    if not zone_code:
        score -= 25.0
        reasons.append("Zoning code was not found in the ZIP scan.")
    if not gp_attrs.get("GPDESIGNATION"):
        score -= 5.0
        reasons.append("General Plan designation was not found.")
    if zone_code.startswith("PD") or "(PD)" in zone_code:
        score -= 15.0
        reasons.append("Planned Development zoning requires manual standard review.")
    if not has_primary_building:
        score -= 20.0
        reasons.append("Primary residential building was not confirmed from footprint data.")
    if adu_status == "expired":
        score -= 5.0
        reasons.append("Expired ADU permit text needs APN-level review.")
    if parcel_area_ft2 > OVERSIZED_PARCEL_THRESHOLD_FT2:
        score -= 20.0
        reasons.append(
            f"Oversized parcel ({round(parcel_area_ft2 / 43560, 1)} acres); "
            "verify this is a standard residential lot, not a farm or institutional property."
        )

    score = max(0.0, min(100.0, score))
    if score >= 80.0:
        level = "high"
    elif score >= 60.0:
        level = "medium"
    else:
        level = "low"
    return {
        "score": round(score),
        "level": level,
        "reasons": reasons,
    }


async def get_heatmap_data(
    client: httpx.AsyncClient,
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    boundary_geometry: dict[str, Any] | None = None,
    include_excluded: bool = False,
) -> list[dict[str, Any]]:
    """Fetch and score returned San Jose parcels inside the requested area.

    Layer queries use the area's bounding box for server-side performance. If
    ``boundary_geometry`` is supplied, each parcel is then filtered by that
    polygon so ZIP scans do not include adjacent parcels from the bounding box.
    """
    envelope = arcgis.envelope(west, south, east, north)
    boundary_wgs = shape(boundary_geometry).buffer(0) if boundary_geometry else None

    parcel_task = _query_all_features(
        client,
        PARCELS_URL,
        geometry=envelope,
        geometry_type="esriGeometryEnvelope",
        out_fields=PARCEL_OUT_FIELDS,
        where="APN IS NOT NULL",
        stage="heatmap parcels",
    )
    building_task = _query_all_features(
        client,
        BUILDINGS_URL,
        geometry=envelope,
        geometry_type="esriGeometryEnvelope",
        stage="heatmap buildings",
    )
    permits_active_task = _query_all_features(
        client,
        PERMITS_ACTIVE_URL,
        geometry=envelope,
        geometry_type="esriGeometryEnvelope",
        out_fields=PERMIT_OUT_FIELDS,
        return_geometry=False,
        order_by_fields="APN",
        stage="heatmap active permits",
    )
    permits_expired_task = _query_all_features(
        client,
        PERMITS_EXPIRED_URL,
        geometry=envelope,
        geometry_type="esriGeometryEnvelope",
        out_fields=PERMIT_OUT_FIELDS,
        return_geometry=False,
        order_by_fields="APN",
        stage="heatmap expired permits",
    )
    zoning_task = _query_all_features(
        client,
        SAN_JOSE_ZONING_QUERY_URL,
        geometry=envelope,
        geometry_type="esriGeometryEnvelope",
        out_fields=ZONING_OUT_FIELDS,
        stage="heatmap zoning",
    )
    gp_task = _query_all_features(
        client,
        SAN_JOSE_GENERAL_PLAN_QUERY_URL,
        geometry=envelope,
        geometry_type="esriGeometryEnvelope",
        out_fields=GENERAL_PLAN_OUT_FIELDS,
        stage="heatmap general plan",
    )

    (
        parcels_raw,
        buildings_raw,
        permits_active,
        permits_expired,
        zoning_raw,
        gp_raw,
    ) = await asyncio.gather(
        parcel_task,
        building_task,
        permits_active_task,
        permits_expired_task,
        zoning_task,
        gp_task,
    )

    active_adu_apns: set[str] = set()
    expired_adu_apns: set[str] = set()
    finalized_adu_apns: set[str] = set()
    for permit in permits_active:
        attrs = permit.get("attributes") or {}
        apn = normalize_apn(attrs.get("APN"))
        if apn and _is_adu_permit(attrs):
            active_adu_apns.add(apn)

    for permit in permits_expired:
        attrs = permit.get("attributes") or {}
        apn = normalize_apn(attrs.get("APN"))
        if apn and _is_adu_permit(attrs):
            expired_adu_apns.add(apn)
            if attrs.get("FINALDATE"):
                finalized_adu_apns.add(apn)

    building_geoms = []
    for raw in buildings_raw:
        geom_json = _geojson_geom(raw)
        if not geom_json:
            continue
        try:
            geom = shape(geom_json).buffer(0)
        except Exception:
            continue
        if not geom.is_empty:
            building_geoms.append(geom)
    building_index = STRtree(building_geoms) if building_geoms else None
    zoning_records, zoning_index = _feature_records(zoning_raw)
    gp_records, gp_index = _feature_records(gp_raw)

    results = []
    for raw in parcels_raw:
        attrs = raw.get("attributes") or {}
        apn = normalize_apn(attrs.get("APN"))
        if not apn:
            continue

        geom_json = _geojson_geom(raw)
        if not geom_json:
            continue

        try:
            parcel_wgs = shape(geom_json).buffer(0)
            if parcel_wgs.is_empty:
                continue
            if boundary_wgs is not None and not boundary_wgs.covers(
                parcel_wgs.representative_point()
            ):
                continue

            parcel_utm = shapely_transform(TO_UTM, parcel_wgs)
            parcel_area_ft2 = parcel_utm.area * M2_TO_FT2

            if building_index is not None:
                candidate_indices = building_index.query(parcel_wgs)
                intersecting_buildings = [
                    building_geoms[int(i)]
                    for i in candidate_indices
                    if building_geoms[int(i)].intersects(parcel_wgs)
                ]
            else:
                intersecting_buildings = []

            existing_coverage_ft2 = 0.0
            if intersecting_buildings:
                building_union_wgs = unary_union(intersecting_buildings)
                clipped_buildings = building_union_wgs.intersection(parcel_wgs)
                building_union_utm = shapely_transform(TO_UTM, clipped_buildings)
                existing_coverage_ft2 = building_union_utm.area * M2_TO_FT2

            # Front-yard siting cannot be inferred without knowing the street
            # frontage. This 4 ft / 6 ft screen is intentionally a lead score,
            # not a permit-ready compliance verdict.
            setback_m = 4.0 / 3.28084
            clearance_m = 6.0 / 3.28084
            parcel_eroded = parcel_utm.buffer(-setback_m)

            buildable_area_ft2 = 0.0
            if not parcel_eroded.is_empty:
                if intersecting_buildings:
                    buildings_utm = shapely_transform(TO_UTM, unary_union(intersecting_buildings))
                    buildable = parcel_eroded.difference(buildings_utm.buffer(clearance_m))
                else:
                    buildable = parcel_eroded
                buildable_area_ft2 = max(0.0, buildable.area * M2_TO_FT2)

            has_primary_building = existing_coverage_ft2 >= MIN_PRIMARY_BUILDING_FT2
            zoning_attrs = _best_attrs_for_geom(parcel_wgs, zoning_records, zoning_index)
            gp_attrs = _best_attrs_for_geom(parcel_wgs, gp_records, gp_index)
            eligible, eligibility_reason, zone_code, zone_name, zoning_score = _eligibility_from_zoning(
                zoning_attrs,
                gp_attrs,
                has_primary_building=has_primary_building,
            )

            coverage_ratio, physical_score, physical_breakdown = _physical_score_breakdown(
                buildable_area_ft2=buildable_area_ft2,
                parcel_area_ft2=parcel_area_ft2,
                existing_coverage_ft2=existing_coverage_ft2,
                has_primary_building=has_primary_building,
            )

            active_adu = apn in active_adu_apns
            expired_adu = apn in expired_adu_apns
            finalized_adu = apn in finalized_adu_apns
            adu_status = _permit_status(active_adu, expired_adu, finalized_adu)
            raw_opportunity_score, raw_opportunity_breakdown = _opportunity_score_breakdown(
                zoning_score=zoning_score,
                zone_code=zone_code,
                adu_status=adu_status,
                buildable_area_ft2=buildable_area_ft2,
                parcel_area_ft2=parcel_area_ft2,
                coverage_ratio=coverage_ratio,
            )
            confidence = _confidence(
                zone_code=zone_code,
                gp_attrs=gp_attrs,
                has_primary_building=has_primary_building,
                adu_status=adu_status,
                parcel_area_ft2=parcel_area_ft2,
            )

            exclusion_reason = ""
            if not eligible:
                exclusion_reason = eligibility_reason
            elif adu_status == "active":
                exclusion_reason = "Active ADU permit found in ZIP permit scan."
            elif adu_status == "finalized":
                exclusion_reason = "Finalized ADU permit found in ZIP permit scan."

            is_excluded = bool(exclusion_reason)
            if is_excluded:
                logger.debug(
                    "Skipping heatmap parcel %s: %s permit_status=%s",
                    apn,
                    exclusion_reason,
                    adu_status,
                )
                total_score = 0.0
                opportunity_score = 0.0
                opportunity_breakdown = _excluded_opportunity_breakdown(exclusion_reason)
                score_bucket = "blocked"
            else:
                opportunity_score = raw_opportunity_score
                opportunity_breakdown = raw_opportunity_breakdown
                total_score = physical_score + opportunity_score
                score_bucket = _score_color_bucket(total_score)

            if is_excluded and not include_excluded:
                continue

            centroid = parcel_wgs.centroid
            display_geometry = parcel_wgs.simplify(0.000001, preserve_topology=True)
            results.append({
                "apn": apn,
                "address": f"APN {apn}",
                "latitude": float(centroid.y),
                "longitude": float(centroid.x),
                "score": round(total_score, 1),
                "score_bucket": score_bucket,
                "lead_status": "excluded" if is_excluded else "qualified",
                "exclusion_reason": exclusion_reason,
                "eligibility_status": "excluded" if is_excluded else "eligible",
                "compliance_score": round(physical_score, 1),
                "opportunity_score": round(opportunity_score, 1),
                "score_breakdown": {
                    "physical": physical_breakdown,
                    "opportunity": opportunity_breakdown,
                },
                "confidence": confidence,
                "buildable_area_ft2": round(buildable_area_ft2),
                "parcel_area_ft2": round(parcel_area_ft2),
                "existing_building_area_ft2": round(existing_coverage_ft2),
                "has_primary_building": has_primary_building,
                "is_eligible": eligible,
                "eligibility_reason": eligibility_reason,
                "zoning": zone_code,
                "zoning_name": zone_name,
                "zoning_ordinance": zoning_ordinance_reference(zone_code, zone_name),
                "general_plan": gp_attrs.get("GPDESIGNATION") or "",
                "adu_permit_status": adu_status,
                "adu_permit_source": "San Jose permit layers 8+9 ZIP-extent scan",
                "geometry": mapping(display_geometry),
            })
        except Exception as exc:
            logger.warning("Failed to score parcel %s: %s", apn, exc)
            continue

    return sorted(results, key=lambda lead: lead["score"], reverse=True)
