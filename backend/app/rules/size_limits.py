"""ADU size limits and setback descriptions per Bulletin #210 (03/05/2026).

Source: SAN_JOSE_ADU_RULES.md, Bulletin #210 City Development Standards,
San Jose Municipal Code 20.80 Part 2.75.
"""

from __future__ import annotations

from typing import Any

# Lot-tier caps for single-family detached ADUs.
_SMALL_LOT_FT2 = 9000
_SMALL_LOT_CAP_SQFT = 1000
_LARGE_LOT_CAP_SQFT = 1200
_JADU_MAX_SQFT = 500.0
_DUPLEX_CAP_SQFT = 800.0
_ATTACHED_PRIMARY_FRACTION = 0.5


def adu_size_limits(
    parcel_area_ft2: float,
    primary_sqft: float | None,
    property_type: str,
    adu_type: str = "detached",
) -> dict[str, Any]:
    """Maximum ADU size for the requested type, given parcel and primary sizes.

    Returns a dict with `tier`, `max_this_type`, `max_detached`, `max_attached`,
    `max_jadu`, `lot_basis`, and `notes` so callers can render the rationale
    alongside the cap.
    """
    adu_type = (adu_type or "detached").lower().strip()
    is_multi = property_type in ("Duplex", "Multi-Family")

    if adu_type == "jadu":
        return {
            "tier": "JADU — within existing primary footprint",
            "max_this_type": _JADU_MAX_SQFT,
            "max_detached": None,
            "max_attached": None,
            "max_jadu": _JADU_MAX_SQFT,
            "lot_basis": parcel_area_ft2,
            "notes": (
                "JADU max 500 sf. Must be within the existing footprint of the single-family home "
                "(including attached garage). No owner-occupancy required if the JADU has its own "
                "sanitation facilities."
            ),
        }

    if is_multi:
        tier = "Duplex / Multifamily — Attached" if adu_type == "attached" else "Duplex / Multifamily — Detached"
        flavor = "attached" if adu_type == "attached" else "detached"
        return {
            "tier": tier,
            "max_this_type": _DUPLEX_CAP_SQFT,
            "max_detached": _DUPLEX_CAP_SQFT,
            "max_attached": _DUPLEX_CAP_SQFT,
            "max_jadu": None,
            "lot_basis": parcel_area_ft2,
            "notes": f"Duplex/multifamily {flavor} ADU: 800 sf max. JADUs not allowed.",
        }

    if parcel_area_ft2 <= 0:
        lot_cap = _LARGE_LOT_CAP_SQFT
        tier_label = "Lot size unknown (assumed ≥ 9,000 sf)"
    elif parcel_area_ft2 < _SMALL_LOT_FT2:
        lot_cap = _SMALL_LOT_CAP_SQFT
        tier_label = f"Lot {parcel_area_ft2:,.0f} sf (< 9,000 sf)"
    else:
        lot_cap = _LARGE_LOT_CAP_SQFT
        tier_label = f"Lot {parcel_area_ft2:,.0f} sf (>= 9,000 sf)"

    if adu_type == "attached":
        if primary_sqft and primary_sqft > 0:
            max_attached = min(primary_sqft * _ATTACHED_PRIMARY_FRACTION, float(lot_cap))
            primary_note = (
                f"50% of {primary_sqft:,.0f} sf primary = "
                f"{primary_sqft * _ATTACHED_PRIMARY_FRACTION:,.0f} sf; "
                f"capped at {lot_cap:,} sf = {max_attached:,.0f} sf max."
            )
        else:
            max_attached = float(lot_cap)
            primary_note = "Primary living area unknown; full lot-tier cap used."

        return {
            "tier": f"{tier_label} — Attached ADU",
            "max_this_type": max_attached,
            "max_detached": float(lot_cap),
            "max_attached": max_attached,
            "max_jadu": _JADU_MAX_SQFT,
            "lot_basis": parcel_area_ft2,
            "notes": (
                f"Attached ADU: up to 50% of main home living area, max {lot_cap:,} sf. "
                f"{primary_note} "
                "Front door must be on a different facade from the main home. "
                "No siting restriction (can be anywhere on the parcel)."
            ),
        }

    return {
        "tier": f"{tier_label} — Detached ADU",
        "max_this_type": float(lot_cap),
        "max_detached": float(lot_cap),
        "max_attached": float(lot_cap),
        "max_jadu": _JADU_MAX_SQFT,
        "lot_basis": parcel_area_ft2,
        "notes": (
            f"Detached ADU: {lot_cap:,} sf max. "
            "Must be behind main home or set back >= 45 ft from front property line. "
            "Max 40% rear yard coverage. Min 6 ft separation from main home."
        ),
    }


def setback_description(adu_type: str = "detached") -> str:
    """Plain-English summary of side, rear, and front setback rules."""
    adu_type = (adu_type or "detached").lower()
    if adu_type == "attached":
        return (
            "Attached ADU — City Standards: side/rear setbacks must meet Building & Fire codes "
            "minimum (no separate zoning setback required from property line). "
            "Front setback: per zoning district Table 20-60. "
            "State Standards (if chosen): 4 ft side/rear. "
            "Front setback may be encroached if no other option enables a minimum 800 sf ADU."
        )
    if adu_type == "jadu":
        return (
            "JADU — built within the existing primary footprint; setbacks are those of the existing "
            "structure. Up to 150 sf may be added for ingress/egress."
        )
    return (
        "Detached ADU — City Standards: 1st story 0 ft side/rear; 2nd story 4 ft side/rear. "
        "Front setback: per zoning district Table 20-60 (generally >= 45 ft for detached in rear yard). "
        "Min 6 ft building separation from main home. "
        "State Standards (if chosen): 4 ft side/rear; front may be reduced if needed for >= 800 sf."
    )
