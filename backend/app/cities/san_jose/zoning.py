"""San Jose zoning lookup, dataclasses, and ADU eligibility rules.

Combines the former `app.clients.zoning` (fetch functions hitting the OPN
ArcGIS layers) and `app.rules.zoning` (typed dataclasses + eligibility
decisioning) into one module — they were tightly coupled and only ever used
together.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

import httpx
from fastapi import HTTPException

from app.result import FetchResult
from app.rules_common.property_type import property_type_from_style as _shared_property_type
from app.services import arcgis

# Re-export so existing callers (e.g. checklist.py) can keep importing it from
# the SJ zoning module while the canonical definition lives in rules_common.
property_type_from_style = _shared_property_type


@dataclass(frozen=True)
class ZoningData:
    zoning: str
    zoning_abbrev: str
    zoning_full_name: str
    facility_id: str | None
    rezoning_file: str | None
    pd_use: str | None
    pd_density: str | None
    developed_as_pd: str | None
    approval_date: str | None
    notes: str | None


@dataclass(frozen=True)
class GeneralPlanData:
    gp_designation: str
    gp_abbreviation: str
    notes: str | None
    last_update: str | None

# Static zoning code → human label map. Lifted from the legacy
# `_zoning_full_name` table in `main.py`; live here so it can be unit-tested
# without spinning up FastAPI.
_ZONING_FULL_NAMES: dict[str, str] = {
    "R-1-1": "Single-Family Residential (Up to One Dwelling Unit per Acre)",
    "R-1-2": "Single-Family Residential (Up to Two Dwelling Units per Acre)",
    "R-1-5": "Single-Family Residential (Up to Five Dwelling Units per Acre)",
    "R-1-8": "Single-Family Residential (Up to Eight Dwelling Units per Acre)",
    "R-2": "Two-Family Residential",
    "R-M": "Multiple Residence District",
    "PD": "Planned Development",
    "A": "Agriculture",
    "CG": "Commercial General",
    "CN": "Commercial Neighborhood",
    "DC": "Downtown Primary Commercial",
    # Mixed-use zones that permit residential (CA §66310-eligible)
    "MU-N": "Mixed Use Neighborhood",
    "MU-C": "Mixed Use Community",
    "DC-NT": "Downtown Neighborhood Transition",
}

_ELIGIBLE_GP_TOKENS = (
    "RESIDENTIAL NEIGHBORHOOD",
    "MIXED-USE NEIGHBORHOOD",
    "URBAN VILLAGE",
    "URBAN RESIDENTIAL",
    "TRANSIT RESIDENTIAL",
    "RURAL RESIDENTIAL",
    "DOWNTOWN",
    "MIXED-USE COMMERCIAL",
)

SAN_JOSE_ADU_PAGE_URL = (
    "https://www.sanjoseca.gov/business/development-services-permit-center/"
    "accessory-dwelling-units-adus"
)
SAN_JOSE_MUNICIPAL_CODE_URL = (
    "https://library.municode.com/ca/san_jose/codes/code_of_ordinances"
)


def zoning_full_name(zoning_code: str) -> str:
    """Return the human-readable name for a San Jose zoning code."""
    base = (zoning_code or "").split("(")[0]
    return _ZONING_FULL_NAMES.get(base, zoning_code or "Unknown")


def zoning_ordinance_reference(
    zoning_code: str,
    zoning_name: str,
) -> dict[str, Any]:
    """Return the ordinance references relevant to a heatmap lead's zone."""
    code = (zoning_code or "").strip().upper()
    zone_label = zoning_name or zoning_full_name(code)
    if code.startswith(("R-1", "R-2", "R-M", "R-MH")):
        zoning_standard = "Chapter 20.30 Residential Zoning Districts, Table 20-60"
    elif code.startswith("PD") or "(PD)" in code:
        zoning_standard = (
            "Planned Development zoning standards, plus the residential ADU sections"
        )
    elif code.startswith(("MU", "DC")):
        zoning_standard = (
            "Mixed-use/Downtown zoning standards; ADU permitted where residential use is allowed "
            "(CA Gov. Code §66310)"
        )
    else:
        zoning_standard = "Applicable Title 20 zoning district standards"

    return {
        "jurisdiction": "City of San Jose",
        "zoning_code": code,
        "zoning_name": zone_label,
        "title": "San Jose Municipal Code Title 20 - Zoning",
        "zoning_standard": zoning_standard,
        "adu_sections": [
            "20.80.175 General ADU standards",
            "20.80.176 Streamlined/state-standard ADU approval",
        ],
        "summary": (
            f"{code or 'Unknown zoning'} ({zone_label}) should be checked against "
            f"{zoning_standard}; ADU review uses SJMC 20.80.175 and 20.80.176."
        ),
        "code_url": SAN_JOSE_MUNICIPAL_CODE_URL,
        "adu_url": SAN_JOSE_ADU_PAGE_URL,
    }


def adu_eligibility(
    zoning: ZoningData | None,
    general_plan: GeneralPlanData | None,
    property_type: str,
) -> tuple[bool, str]:
    """Decide whether an ADU is allowed on the parcel.

    Mirrors `backend/app/services/compliance_service.py::_check_adu_eligibility`
    in the root project; kept self-contained here so the MVP can be tested in
    isolation.
    """
    code = str(zoning.zoning if zoning else "").upper()
    gp = str(general_plan.gp_designation if general_plan else "").upper()
    gp_label = general_plan.gp_designation if general_plan else "unknown"
    is_sf = property_type == "Single-Family"
    is_multi = property_type in ("Duplex", "Multi-Family")
    # R-1 + Unknown ⇒ treat as single-family for eligibility.
    eff_sf = is_sf or (property_type == "Unknown" and code.startswith("R-1"))

    if code.startswith("R-1") and eff_sf:
        return True, f"ADU allowed: {code} zone with single-family residence."
    if code.startswith(("R-2", "R-M")) and (is_sf or is_multi):
        return True, f"ADU allowed: {code} residential zone."
    if is_multi:
        return True, f"ADU allowed: duplex/multifamily property (type: {property_type})."

    if any(token in gp for token in _ELIGIBLE_GP_TOKENS):
        if eff_sf:
            return (
                True,
                f"ADU allowed: General Plan '{gp_label}' with single-family residence.",
            )
        return (
            False,
            f"General Plan '{gp_label}' allows ADUs but property type is {property_type}.",
        )

    if code.startswith("PD") or "(PD)" in code:
        if eff_sf or property_type == "Unknown":
            return (
                True,
                f"ADU likely allowed: {code} with single-family residence "
                "(verify PD standards comply with R-1 or ADU conforms to PD).",
            )
        return (
            False,
            f"{code} allows ADUs only with single-family residence (current: {property_type}).",
        )

    return (
        False,
        f"No automatic residential/PD/eligible General Plan path for zoning "
        f"{zoning.zoning if zoning else 'unknown'}.",
    )


# ── ArcGIS fetch clients ─────────────────────────────────────────────────────
SAN_JOSE_ZONING_QUERY_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/OPN/"
    "OPN_OpenDataService/MapServer/401/query"
)
SAN_JOSE_GENERAL_PLAN_QUERY_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/OPN/"
    "OPN_OpenDataService/MapServer/404/query"
)

_SRC_ZONING = "San Jose Zoning layer 401"
_SRC_GP = "San Jose General Plan layer 404"


async def fetch_zoning(
    client: httpx.AsyncClient, latitude: float, longitude: float
) -> FetchResult[ZoningData]:
    try:
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
    except HTTPException as exc:
        return FetchResult.failed(exc.detail, _SRC_ZONING)

    if not features:
        return FetchResult.absent(_SRC_ZONING)

    attrs = features[0].get("attributes") or {}
    zoning_code = attrs.get("ZONING") or attrs.get("ZONINGABBREV") or ""
    if not zoning_code:
        logger.warning(
            "Zoning feature at (%.5f, %.5f) has no ZONING or ZONINGABBREV field — "
            "ArcGIS schema may have changed",
            latitude,
            longitude,
        )
    return FetchResult.ok(
        ZoningData(
            zoning=zoning_code,
            zoning_abbrev=attrs.get("ZONINGABBREV") or zoning_code,
            zoning_full_name=zoning_full_name(zoning_code),
            facility_id=attrs.get("FACILITYID"),
            rezoning_file=attrs.get("REZONINGFILE"),
            pd_use=attrs.get("PDUSE"),
            pd_density=attrs.get("PDDENSITY"),
            developed_as_pd=attrs.get("DEVELOPEDASPD"),
            approval_date=attrs.get("APPROVALDATE"),
            notes=attrs.get("NOTES"),
        ),
        _SRC_ZONING,
    )


async def fetch_general_plan(
    client: httpx.AsyncClient, latitude: float, longitude: float
) -> FetchResult[GeneralPlanData]:
    try:
        features = await arcgis.query_features(
            client,
            SAN_JOSE_GENERAL_PLAN_QUERY_URL,
            geometry=arcgis.point(longitude, latitude),
            geometry_type="esriGeometryPoint",
            return_geometry=False,
            out_fields="GPDESIGNATION,GPABBREVIATION,NOTES,LASTUPDATE",
            stage="San Jose General Plan",
        )
    except HTTPException as exc:
        return FetchResult.failed(exc.detail, _SRC_GP)

    if not features:
        return FetchResult.absent(_SRC_GP)

    attrs = features[0].get("attributes") or {}
    return FetchResult.ok(
        GeneralPlanData(
            gp_designation=attrs.get("GPDESIGNATION") or "",
            gp_abbreviation=attrs.get("GPABBREVIATION") or "",
            notes=attrs.get("NOTES"),
            last_update=attrs.get("LASTUPDATE"),
        ),
        _SRC_GP,
    )
