"""Zoning lookup, property type inference, and ADU eligibility rules."""

from __future__ import annotations

from typing import Any

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


def zoning_full_name(zoning_code: str) -> str:
    """Return the human-readable name for a San Jose zoning code."""
    base = (zoning_code or "").split("(")[0]
    return _ZONING_FULL_NAMES.get(base, zoning_code or "Unknown")


def property_type_from_style(style: str | None) -> str:
    """Map a HomeHarvest `style` value to a coarse property-type bucket."""
    if not style:
        return "Unknown"
    s = str(style).upper().replace("_", " ")
    if "DUPLEX" in s or "TWO FAMILY" in s or "2 FAMILY" in s:
        return "Duplex"
    if "MULTI" in s or "APARTMENT" in s or "TRIPLEX" in s or "FOURPLEX" in s:
        return "Multi-Family"
    if "TOWNHOUSE" in s or "TOWN HOUSE" in s or "ROW" in s:
        return "Townhouse"
    if "CONDO" in s:
        return "Condo"
    if "SINGLE" in s or "SFR" in s or "1 FAMILY" in s or "ONE FAMILY" in s or "DETACHED" in s:
        return "Single-Family"
    if "FAMILY" in s and "TWO" not in s and "MULTI" not in s:
        return "Single-Family"
    if s in ("RESIDENTIAL", "RES"):
        return "Single-Family"
    return "Unknown"


def adu_eligibility(
    zoning: dict[str, Any],
    general_plan: dict[str, Any],
    property_type: str,
) -> tuple[bool, str]:
    """Decide whether an ADU is allowed on the parcel.

    Mirrors `backend/app/services/compliance_service.py::_check_adu_eligibility`
    in the root project; kept self-contained here so the MVP can be tested in
    isolation.
    """
    code = str(zoning.get("zoning") or "").upper()
    gp = str(general_plan.get("gp_designation") or "").upper()
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
                f"ADU allowed: General Plan '{general_plan.get('gp_designation')}' "
                "with single-family residence.",
            )
        return (
            False,
            f"General Plan '{general_plan.get('gp_designation')}' allows ADUs "
            f"but property type is {property_type}.",
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
        f"{zoning.get('zoning') or 'unknown'}.",
    )
