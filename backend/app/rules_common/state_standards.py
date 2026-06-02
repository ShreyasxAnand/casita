"""California state ADU baseline (Gov Code §§66310-66342).

Two kinds of exports live here:

  Constants — numeric values cities must honor under State Standards (GC
  §66321). An ADU may always be built within these limits even if a
  city's stricter local rules would otherwise block it.

  Checklist-item functions — return a single checklist dict for a rule that
  is identical across every CA city. Each function accepts `part` and `number`
  as keyword arguments so callers control their own bulletin numbering; state
  law says nothing about how items should be ordered.

Statute references use the post-SB 477 renumbered sections and the 2026 HCD
ADU Handbook updates.
"""

from __future__ import annotations

from typing import Any

# ── numeric constants ─────────────────────────────────────────────────────────

# State Standards detached ADU size cap (GC §66321).
STATE_DETACHED_MAX_SQFT: float = 800.0

# A pitched-roof detached ADU may reach 20 ft instead of 18 ft.
STATE_MAX_HEIGHT_FT: float = 18.0
STATE_DETACHED_MAX_SQFT_PITCHED_ROOF: float = 800.0  # size cap unchanged with pitched roof

# Side / rear setback under State Standards.
STATE_SIDE_REAR_SETBACK_FT: float = 4.0

# Parking exemption: no replacement parking required for an ADU when the
# property is within this distance of a qualifying public transit stop.
STATE_PARKING_TRANSIT_EXEMPTION_MILES: float = 0.5

# Impact-fee exemption threshold: ADUs strictly below this size are exempt
# from school impact fees and proportionate development impact fees
# (GC §§66313, 66324; SB 13; Education Code §17620).
STATE_IMPACT_FEE_SQFT_THRESHOLD: float = 750.0


# ── internal helper ───────────────────────────────────────────────────────────

def _item(
    *,
    part: int,
    number: float,
    status: str,
    question: str,
    detail: str,
    source: str,
) -> dict[str, Any]:
    return {
        "part": part,
        "number": number,
        "status": status,
        "question": question,
        "detail": detail,
        "source": source,
    }


# ── checklist-item functions ──────────────────────────────────────────────────

def ca_parking(*, part: int, number: float) -> dict[str, Any]:
    """No parking required in most circumstances (GC §§66314, 66322).

    Cities may not require off-street parking for an ADU when any of these
    apply: within ½ mile of public transit, conversion of an existing
    permitted structure, location in a historic district, within one block
    of a car-share vehicle, or garage-to-ADU conversion (no replacement
    spaces required).
    """
    return _item(
        part=part,
        number=number,
        status="pass",
        question="Parking requirements",
        detail=(
            "No parking required — state law exempts ADUs from off-street parking mandates "
            f"when within {STATE_PARKING_TRANSIT_EXEMPTION_MILES} mi of public transit, "
            "when converting an existing permitted structure, in a historic district, or "
            "within one block of a car-share vehicle. "
            "A garage converted to an ADU does not require replacement parking spaces."
        ),
        source="GC §§66314(d)(10)-(11), 66322(a) / HCD ADU Handbook March 2026",
    )


def ca_owner_occupancy(adu_type: str, *, part: int, number: float) -> dict[str, Any]:
    """Owner-occupancy rules under current CA state law.

    Standard ADUs — local agencies generally cannot impose owner-occupancy
    requirements, except for separately sold ADUs under GC §66341(c)(3).

    JADUs — under 2026 HCD guidance, owner occupancy depends on sanitation:
    shared sanitation with the primary structure requires owner occupancy;
    independent sanitation does not.
    """
    if adu_type == "jadu":
        detail = (
            "JADU owner-occupancy depends on sanitation: if the JADU has shared sanitation "
            "facilities with the primary structure, owner occupancy is required; if it has "
            "independent sanitation facilities, owner occupancy is not required. JADUs "
            "cannot be used as short-term rentals and, if rented, must be rented for longer "
            "than 30 days."
        )
    else:
        detail = (
            "No owner-occupancy requirement for standard ADUs, except for separately sold "
            "ADUs allowed under Government Code §66341(c)(3)."
        )
    return _item(
        part=part,
        number=number,
        status="info",
        question="Owner-occupancy requirement",
        detail=detail,
        source="GC §66315 / GC §66333 / HCD ADU Handbook March 2026",
    )


def ca_ministerial_review(city_adu_url: str, *, part: int, number: float) -> dict[str, Any]:
    """Ministerial (by-right) approval pathway (GC §66317).

    Cities must approve ADUs meeting all objective development standards
    without a discretionary hearing or public notice. No design review,
    no conditional use permit, no neighborhood notification.

    `city_adu_url` is shown in the detail and source so users know exactly
    where to submit for the city they selected.
    """
    return _item(
        part=part,
        number=number,
        status="info",
        question="Approval pathway",
        detail=(
            "Ministerial (by-right) review — if the ADU meets all objective development "
            "standards, the city must approve it without a discretionary hearing, design "
            "review, or public notice (GC §66317). "
            f"Submit your application at {city_adu_url}"
        ),
        source=f"GC §66317 / HCD ADU Handbook March 2026 / {city_adu_url}",
    )


def ca_impact_fees(
    adu_area_ft2: float,
    *,
    part: int,
    number: float,
    city_fees_url: str | None = None,
) -> dict[str, Any]:
    """School and development impact fee rules (GC §§66313, 66324; Ed. Code §17620).

    ADUs strictly below STATE_IMPACT_FEE_SQFT_THRESHOLD sq ft are exempt
    from school impact fees and proportionate development impact fees.
    ADUs at or above the threshold are subject to fees, which must be paid
    before the building permit is issued.
    """
    exempt = adu_area_ft2 < STATE_IMPACT_FEE_SQFT_THRESHOLD
    threshold = int(STATE_IMPACT_FEE_SQFT_THRESHOLD)
    if exempt:
        detail = (
            f"ADU is {adu_area_ft2:,.0f} sf (below {threshold} sf) — "
            "exempt from school impact fees and proportionate development impact fees "
            "under state law."
        )
        status = "pass"
    else:
        fee_ref = f" See {city_fees_url} for the fee schedule." if city_fees_url else ""
        detail = (
            f"ADU is {adu_area_ft2:,.0f} sf (≥ {threshold} sf) — "
            "school impact fees and proportionate development impact fees apply. "
            f"Fees must be paid before the building permit is issued.{fee_ref}"
        )
        status = "verify"
    source = "GC §§66313, 66324 / SB 13 / Education Code §17620"
    if city_fees_url:
        source += f" / {city_fees_url}"
    return _item(
        part=part,
        number=number,
        status=status,
        question=f"Impact fees — ADU ≥ {threshold} sf?",
        detail=detail,
        source=source,
    )
