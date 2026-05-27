"""San Jose ADU Universal Checklist (Bulletin #210, 03/05/2026).

The original `_full_checklist_for_site` function was 488 lines and had a
`# noqa: C901` complexity waiver. It is split here into five Part-functions
that each consume a single `ChecklistContext` dataclass, so each piece is
small enough to unit-test independently.

Question numbering matches Bulletin #210 verbatim. Items 24+ are supplemental
informational items not in the Bulletin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.clients.code_enforcement import CodeEnforcementData, CodeIssue
from app.clients.designations import DesignationData
from app.clients.permits import PermitRecord, PermitsData
from app.result import FetchResult
from app.rules.size_limits import adu_size_limits, setback_description
from app.rules.zoning import (
    GeneralPlanData,
    ZoningData,
    adu_eligibility,
    property_type_from_style,
)

ADU_TYPE_LABELS = {
    "detached": "Detached ADU",
    "attached": "Attached ADU",
    "jadu": "JADU",
}
_IMPACT_FEE_THRESHOLD_SQFT = 750
_REAR_YARD_MAX_COVERAGE_PCT = 40.0


def _unknown_designation() -> FetchResult[DesignationData]:
    return FetchResult.failed("not loaded", "unknown")


def _unknown_zoning() -> FetchResult[ZoningData]:
    return FetchResult.failed("not loaded", "unknown")


def _unknown_gp() -> FetchResult[GeneralPlanData]:
    return FetchResult.failed("not loaded", "unknown")


def _unknown_permits() -> FetchResult[PermitsData]:
    return FetchResult.failed("not loaded", "unknown")


def _unknown_code_enforcement() -> FetchResult[CodeEnforcementData]:
    return FetchResult.failed("not loaded", "unknown")


def _designation_status(
    result: FetchResult[DesignationData], *, true_status: str = "fail", false_status: str = "pass"
) -> str:
    if result.is_failed:
        return "unavailable"
    present = result.is_ok and result.data is not None and result.data.present
    return true_status if present else false_status


def _designation_detail(result: FetchResult[DesignationData], fallback: str) -> str:
    if result.is_failed:
        return f"Lookup unavailable — {result.error or 'service error'}. {fallback}"
    if result.data and result.data.detail:
        return result.data.detail
    return fallback


@dataclass(frozen=True)
class ChecklistContext:
    """Pre-computed inputs shared across all checklist parts.

    Building one of these from raw `site_model` / `zoning` / `designations`
    dicts is the only place rule-derived numbers (areas, eligibility, size
    tiers) are computed. Each part-function reads from the context and emits
    pure-data checklist items.
    """

    adu_type: str
    adu_type_label: str
    parcel: dict[str, Any]
    buildable: dict[str, Any]
    adu: dict[str, Any]
    designations: dict[str, Any]
    property_stats: dict[str, Any]

    # Typed zoning fetch results — FAILED means the service was unreachable.
    zoning_result: FetchResult[ZoningData]
    gp_result: FetchResult[GeneralPlanData]

    # Derived scalars
    parcel_area_ft2: float
    buildable_area_ft2: float
    adu_width_ft: float
    adu_depth_ft: float
    adu_area_ft2: float
    existing_footprint_ft2: float
    rear_yard_coverage_pct: float
    fits_requested_size: bool
    property_type: str
    property_type_source: str
    primary_sqft: float | None
    allowed: bool | None  # None when zoning/GP data was unavailable
    allowed_reason: str
    size_limits: dict[str, Any]
    max_this_type: float

    # Typed designation results — FAILED means the service was unreachable.
    flood: FetchResult[DesignationData] = field(default_factory=_unknown_designation)
    geohazard: FetchResult[DesignationData] = field(default_factory=_unknown_designation)
    historic: FetchResult[DesignationData] = field(default_factory=_unknown_designation)
    wui: FetchResult[DesignationData] = field(default_factory=_unknown_designation)
    heritage: FetchResult[DesignationData] = field(default_factory=_unknown_designation)

    # Permit + code-enforcement lookups — FAILED means the service was unreachable.
    permits_result: FetchResult[PermitsData] = field(default_factory=_unknown_permits)
    code_enforcement_result: FetchResult[CodeEnforcementData] = field(
        default_factory=_unknown_code_enforcement
    )

    @property
    def is_detached(self) -> bool:
        return self.adu_type == "detached"

    @property
    def is_attached(self) -> bool:
        return self.adu_type == "attached"

    @property
    def is_jadu(self) -> bool:
        return self.adu_type == "jadu"

    @classmethod
    def from_site_model(
        cls,
        site_model: dict[str, Any],
        *,
        zoning: FetchResult[ZoningData] | None,
        general_plan: FetchResult[GeneralPlanData] | None,
        designations: dict[str, FetchResult[DesignationData]] | None,
        property_stats: dict[str, Any] | None,
        adu_type: str = "detached",
        permits: FetchResult[PermitsData] | None = None,
        code_enforcement: FetchResult[CodeEnforcementData] | None = None,
    ) -> "ChecklistContext":
        parcel = site_model.get("parcel") or {}
        buildable = site_model.get("buildable_zone") or {}
        adu = site_model.get("adu") or {}
        zoning_result = zoning if zoning is not None else _unknown_zoning()
        gp_result = general_plan if general_plan is not None else _unknown_gp()
        designations = designations or {}
        property_stats = property_stats or {}
        _no_data = _unknown_designation()

        adu_type_key = (adu_type or "detached").lower().strip()
        if adu_type_key not in ADU_TYPE_LABELS:
            adu_type_key = "detached"

        parcel_area = float(parcel.get("area_ft2") or 0)
        buildable_area = float(buildable.get("area_ft2") or 0)
        adu_w = float(adu.get("width_ft") or 0)
        adu_d = float(adu.get("depth_ft") or 0)
        adu_area = adu_w * adu_d
        existing_footprint = sum(
            float(b.get("area_ft2") or 0) for b in site_model.get("buildings") or []
        )
        rear_coverage = (
            (existing_footprint + adu_area) / parcel_area * 100 if parcel_area > 0 else 0.0
        )

        style = property_stats.get("style") if property_stats.get("found") else None
        property_type = property_type_from_style(style)
        zoning_code_hint = zoning_result.data.zoning if zoning_result.data else ""
        if property_type == "Unknown" and str(zoning_code_hint).upper().startswith("R-1"):
            property_type = "Single-Family"
            pt_source = "R-1 zoning inference"
        else:
            pt_source = "HomeHarvest listing" if property_stats.get("found") else "unknown"

        primary_sqft: float | None = None
        if property_stats.get("found") and property_stats.get("sqft"):
            primary_sqft = float(property_stats["sqft"])

        if zoning_result.is_failed or gp_result.is_failed:
            allowed: bool | None = None
            allowed_reason = "Zoning or General Plan data could not be fetched."
        else:
            allowed, allowed_reason = adu_eligibility(
                zoning_result.data, gp_result.data, property_type
            )
        limits = adu_size_limits(parcel_area, primary_sqft, property_type, adu_type_key)

        return cls(
            adu_type=adu_type_key,
            adu_type_label=ADU_TYPE_LABELS[adu_type_key],
            parcel=parcel,
            buildable=buildable,
            adu=adu,
            zoning_result=zoning_result,
            gp_result=gp_result,
            designations=designations,
            property_stats=property_stats,
            parcel_area_ft2=parcel_area,
            buildable_area_ft2=buildable_area,
            adu_width_ft=adu_w,
            adu_depth_ft=adu_d,
            adu_area_ft2=adu_area,
            existing_footprint_ft2=existing_footprint,
            rear_yard_coverage_pct=rear_coverage,
            fits_requested_size=bool(adu.get("fits_requested_size")),
            property_type=property_type,
            property_type_source=pt_source,
            primary_sqft=primary_sqft,
            allowed=allowed,
            allowed_reason=allowed_reason,
            size_limits=limits,
            max_this_type=float(limits.get("max_this_type") or 0),
            flood=designations.get("flood") or _no_data,
            geohazard=designations.get("geohazard") or _no_data,
            historic=designations.get("historic") or _no_data,
            wui=designations.get("wui") or _no_data,
            heritage=designations.get("heritage_trees") or _no_data,
            permits_result=permits if permits is not None else _unknown_permits(),
            code_enforcement_result=(
                code_enforcement if code_enforcement is not None
                else _unknown_code_enforcement()
            ),
        )


def _item(
    *, part: int, number: float, status: str, question: str, detail: str, source: str
) -> dict[str, Any]:
    return {
        "part": part,
        "number": number,
        "status": status,
        "question": question,
        "detail": detail,
        "source": source,
    }


def _tristate_status(
    flag: bool | None, *, true_status: str = "fail", false_status: str = "pass"
) -> str:
    if flag is True:
        return true_status
    if flag is False:
        return false_status
    return "verify"


# ── Part 1: property qualification (Q1–Q3) ───────────────────────────────────

def _q2_home_permitted(ctx: ChecklistContext) -> dict[str, Any]:
    return _item(
        part=1, number=2, status="verify",
        question="Q2. Is the main home permitted?",
        detail=(
            "ADUs require a legally-built main residence (single-family, duplex, or multifamily) "
            "with approved permits. "
            f"Detected property type: {ctx.property_type} (via {ctx.property_type_source}). "
            "San Jose's digital permit records only cover ~2011 onward — most residential "
            "properties predate them. Confirm at SJPermits.org (search by APN or address)."
        ),
        source="Bulletin #210 Q2 / SJPermits.org",
    )


def _q3_code_enforcement(ctx: ChecklistContext) -> dict[str, Any]:
    ce = ctx.code_enforcement_result
    if ce.is_failed:
        return _item(
            part=1, number=3, status="verify",
            question="Q3. Is there an active code enforcement issue on the property?",
            detail=(
                f"Code enforcement lookup unavailable — {ce.error or 'service error'}. "
                "Check the Code Complaints Map at SJPermits.org."
            ),
            source=ce.source or "SJPermits.org Code Complaints Map",
        )
    if ce.is_absent or (ce.is_ok and ce.data is not None and not ce.data.has_issues):
        return _item(
            part=1, number=3, status="pass",
            question="Q3. Is there an active code enforcement issue on the property?",
            detail=(
                "No open code complaints and no active code-investigation work orders found "
                "for this property."
            ),
            source=ce.source or "San Jose PLN_PermitsAndComplaints layers 1+8",
        )
    data = ce.data
    assert data is not None
    lines: list[str] = []
    for issue in data.issues[:3]:
        if issue.issue_type == "complaint":
            line = f"Complaint {issue.identifier}"
        else:
            line = f"Code Investigation {issue.identifier}"
        if issue.open_date:
            line += f" (opened {issue.open_date})"
        if issue.description:
            line += f": {issue.description[:80]}"
        lines.append(line)
    summary = "; ".join(lines)
    if data.total_count > 3:
        summary += f" (and {data.total_count - 3} more)"
    parts = []
    if data.complaint_count:
        parts.append(f"{data.complaint_count} open complaint(s)")
    if data.investigation_count:
        parts.append(f"{data.investigation_count} active code investigation(s)")
    return _item(
        part=1, number=3, status="fail",
        question="Q3. Is there an active code enforcement issue on the property?",
        detail=(
            f"{' and '.join(parts)}: {summary}. "
            "Resolve all active issues before ADU plans will be accepted."
        ),
        source=ce.source or "San Jose PLN_PermitsAndComplaints layers 1+8",
    )


def _part1_property_qualification(ctx: ChecklistContext) -> list[dict[str, Any]]:
    apn = ctx.parcel.get("apn") or "unknown"
    return [
        _item(
            part=1, number=1, status="pass",
            question="Q1. Is the property in San Jose?",
            detail=(
                f"APN {apn} loaded from the City parcel GIS layer. "
                "Confirm at SJPermits.org ('Incorporated' = yes)."
            ),
            source="San Jose Parcels ArcGIS layer 270 / SJPermits.org",
        ),
        _q2_home_permitted(ctx),
        _q3_code_enforcement(ctx),
    ]


def _q9_pool_check(ctx: ChecklistContext) -> dict[str, Any]:
    p = ctx.permits_result
    base_note = (
        "If a pool was demolished, submittal must include pool demolition documents "
        "(plot plan per Bulletin #289) or a geotech report + foundation design."
    )
    if p.is_failed:
        return _item(
            part=2, number=9, status="verify",
            question="Q9. Nonbuildable area — demolished pool or other nonbuildable area at the ADU location?",
            detail=(
                f"Pool permit lookup unavailable — {p.error or 'service error'}. "
                f"Check pool permits at SJPermits.org. {base_note}"
            ),
            source=p.source or "SJPermits.org permit history",
        )
    pool_permits = (p.data.pool_permits if p.data else []) if p.is_ok else []
    if not pool_permits:
        return _item(
            part=2, number=9, status="verify",
            question="Q9. Nonbuildable area — demolished pool or other nonbuildable area at the ADU location?",
            detail=(
                "No pool, spa, or swimming-related permits found in the GIS layer for this APN. "
                "Digital permit records only go back ~10 years — a pool demolished earlier would "
                "not appear. Confirm visually and at SJPermits.org."
            ),
            source=p.source or "SJPermits.org permit history",
        )
    lines: list[str] = []
    for r in pool_permits[:3]:
        line = r.folder_num or "permit"
        desc = r.work_desc or r.sub_desc
        if desc:
            line += f": {desc[:60]}"
        if r.issue_date:
            line += f" (issued {r.issue_date})"
        lines.append(line)
    summary = "; ".join(lines)
    if len(pool_permits) > 3:
        summary += f" (and {len(pool_permits) - 3} more)"
    return _item(
        part=2, number=9, status="verify",
        question="Q9. Nonbuildable area — demolished pool or other nonbuildable area at the ADU location?",
        detail=(
            f"Pool or spa permit(s) found: {summary}. "
            f"Confirm current status — if demolished, include demolition documents. {base_note}"
        ),
        source=p.source or "SJPermits.org permit history",
    )


# ── Part 2: property designations (Q4–Q9) ────────────────────────────────────
def _part2_designations(ctx: ChecklistContext) -> list[dict[str, Any]]:
    return [
        _item(
            part=2, number=4,
            status=_designation_status(ctx.flood),
            question="Q4. Flood zones A, AE, AH, or AO?",
            detail=_designation_detail(
                ctx.flood,
                "Check SJPermits.org. If yes, plans must follow Bulletin #211. "
                "(Does not apply to zones D and X.)",
            ),
            source=ctx.flood.source or "FEMA NFHL / San Jose Flood Hazard layer / SJPermits.org",
        ),
        _item(
            part=2, number=5,
            status=_designation_status(ctx.geohazard),
            question="Q5. Geohazard or seismic hazards — geohazard, liquefaction, or landslide zone?",
            detail=_designation_detail(
                ctx.geohazard,
                "Check SJPermits.org ('Geohazard Zone' and 'Seismic Hazards'). "
                "If yes/landslide: Geologic Hazard Clearance required. "
                "If liquefaction + 2 or more units: Geologic Clearance required.",
            ),
            source=ctx.geohazard.source or "San Jose PLN Land Designations layer 31",
        ),
        _item(
            part=2, number=6,
            status=_designation_status(ctx.historic),
            question="Q6. Historic property — on City Historic Resources Inventory or CA Historical Resources list?",
            detail=_designation_detail(
                ctx.historic,
                "If yes + City Development Standards: simplified design standards per 20.80.175(E). "
                "If yes + State Standards: check with Planning — historic review may still apply.",
            ),
            source=ctx.historic.source or "San Jose HRI layers 406 + 408",
        ),
        _item(
            part=2, number=7,
            status=_designation_status(ctx.wui),
            question="Q7. Wildland-Urban Interface (WUI) zone?",
            detail=_designation_detail(
                ctx.wui,
                "If yes, construction must comply with all WUI Fire Conformance Policy requirements.",
            ),
            source=ctx.wui.source or "San Jose WUI layer / USDA WUI",
        ),
        _item(
            part=2, number=8, status="verify",
            question="Q8. Easements — dedicated easement on the property?",
            detail=(
                "Check the title report. Easements often prohibit construction within them. "
                "GIS parcel geometry does not confirm build rights inside easements."
            ),
            source="Title report / County Surveyor Record Index",
        ),
        _q9_pool_check(ctx),
    ]


# ── Part 3: development standards (Q10–Q15+) ─────────────────────────────────
_SITING_DETAILS = {
    "detached": (
        "Detached ADU (City Standards): must be behind the main home OR have a front setback "
        ">= 45 ft from the front property line. Min 6 ft building separation from the main home "
        "is required. Front yard placement is NOT permitted for detached ADUs (unless the 45-ft "
        "setback rule is met). Front setback = per zoning Table 20-60. Confirm via site plan. "
        "Note: under State Development Standards (§20.80.176) there is no siting restriction — "
        "the detached ADU may be placed anywhere on the parcel."
    ),
    "attached": (
        "Attached ADU (City Standards): NO siting restriction — may be located anywhere on the "
        "parcel, INCLUDING the front yard. Front door must be on a DIFFERENT facade from the main "
        "home entry. Front setback applies to the ADU facade the same as the primary dwelling "
        "(per zoning Table 20-60). Prohibited if there is already an existing or proposed "
        "conversion ADU on the property."
    ),
    "jadu": (
        "JADU: must remain within the existing footprint of the single-family home "
        "(including an attached garage). Up to 150 sf may be added for ingress/egress only. "
        "Front setback may be encroached if needed to enable a minimum 800 sf unit."
    ),
}

_TYPE_SELECTOR_DETAILS = {
    "detached": (
        "Detached ADU — a standalone structure separate from the primary home. "
        "City Standards: must be sited in the rear yard or >= 45 ft from the front property line. "
        "Min 6 ft separation from main home. Max 40% rear yard coverage. "
        "State Standards (§20.80.176): no siting restriction."
    ),
    "attached": (
        "Attached ADU — shares a wall or structural element with the primary home. "
        "NO siting restriction — can be located anywhere on the parcel, including front yard. "
        "Front door must be on a DIFFERENT facade from the main home entry. "
        "Note: prohibited if an existing or proposed conversion ADU is already on the property."
    ),
    "jadu": (
        "JADU (Junior ADU) — built entirely within the existing footprint of the single-family "
        "home (including attached garage), or within a proposed new SFR. Max 500 sf. "
        "Up to 150 sf may be added for ingress/egress only. "
        "Owner-occupancy required (unless JADU has its own sanitation facilities)."
    ),
}

_HEIGHT_DETAILS = {
    "detached": (
        "Detached ADU — City Standards: 1st story max 18 ft; 2nd story max 25 ft "
        "(up to 2 additional ft for a pitched roof). "
        "State Standards: max 18 ft for new detached (up to 20 ft for pitched roof)."
    ),
    "attached": (
        "Attached ADU — City Standards: max 25 ft (2 stories allowed). "
        "State Standards: max 25 ft attached."
    ),
    "jadu": (
        "JADU: no independent height limit — height is that of the existing primary structure."
    ),
}


def _size_status(ctx: ChecklistContext) -> tuple[str, float]:
    if ctx.parcel_area_ft2 <= 0:
        return "verify", 0.0
    overage = max(0.0, ctx.adu_area_ft2 - ctx.max_this_type)
    return ("pass" if overage == 0 else "fail"), overage


def _size_detail(ctx: ChecklistContext) -> str:
    detail = (
        f"Requested: {ctx.adu_area_ft2:,.0f} sf ({ctx.adu_width_ft:.0f} x {ctx.adu_depth_ft:.0f} ft). "
        f"Tier: {ctx.size_limits['tier']}. "
        f"Max for {ctx.adu_type_label}: {ctx.max_this_type:,.0f} sf."
    )
    _, overage = _size_status(ctx)
    if overage > 0:
        detail += f" OVER by {overage:,.0f} sf — reduce footprint or switch to a smaller type."
    if ctx.primary_sqft and ctx.is_attached:
        detail += (
            f" Attached cap = 50% of {ctx.primary_sqft:,.0f} sf primary = "
            f"{ctx.primary_sqft * 0.5:,.0f} sf "
            f"(capped at lot-tier max {ctx.max_this_type:,.0f} sf)."
        )
    if ctx.is_jadu:
        detail += " JADU must remain within the existing primary footprint."
    return f"{detail} {ctx.size_limits['notes']}"


def _part3_development_standards(ctx: ChecklistContext) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    zoning_code = ctx.zoning_result.data.zoning if ctx.zoning_result.data else "unknown"
    gp_desig = ctx.gp_result.data.gp_designation if ctx.gp_result.data else "unknown"
    if ctx.allowed is None:
        q10_status = "unavailable"
        q10_detail = (
            "Zoning or General Plan data could not be fetched — verify at SJPermits.org. "
            + (f"Zoning error: {ctx.zoning_result.error}. " if ctx.zoning_result.is_failed and ctx.zoning_result.error else "")
            + (f"GP error: {ctx.gp_result.error}." if ctx.gp_result.is_failed and ctx.gp_result.error else "")
        ).strip()
    else:
        q10_status = "pass" if ctx.allowed else "fail"
        q10_detail = (
            f"{ctx.allowed_reason} "
            f"Zoning: {zoning_code}; GP: {gp_desig}."
        )
    items.append(_item(
        part=3, number=10,
        status=q10_status,
        question="Q10. Zoning / General Plan permits an ADU here",
        detail=q10_detail,
        source=f"{ctx.zoning_result.source} + {ctx.gp_result.source}",
    ))

    items.append(_item(
        part=3, number=10.5, status="info",
        question=f"ADU type selected: {ctx.adu_type_label}",
        detail=_TYPE_SELECTOR_DETAILS.get(ctx.adu_type, "Unknown type selected."),
        source="Bulletin #210 pp. 3-4 City Development Standards",
    ))

    size_status, _ = _size_status(ctx)
    items.append(_item(
        part=3, number=11, status=size_status,
        question="ADU maximum size (Bulletin #210 City Development Standards)",
        detail=_size_detail(ctx),
        source="Bulletin #210 pp.3-4 / San Jose Municipal Code 20.80 Part 2.75",
    ))

    siting_status = "pass" if ctx.is_attached else ("info" if ctx.is_jadu else "verify")
    items.append(_item(
        part=3, number=12, status=siting_status,
        question=f"ADU siting — where can the {ctx.adu_type_label} be located on the parcel?",
        detail=_SITING_DETAILS[ctx.adu_type],
        source="Bulletin #210 p.3 City Development Standards table",
    ))

    setback_status = (
        "pass" if ctx.fits_requested_size
        else ("verify" if ctx.buildable_area_ft2 <= 0 else "fail")
    )
    fits_msg = (
        f"At {ctx.adu_width_ft:.0f} x {ctx.adu_depth_ft:.0f} ft, the ADU fits inside the computed "
        "buildable zone." if ctx.fits_requested_size
        else "ADU footprint does not fit the computed buildable zone — reduce size or relocate."
    )
    items.append(_item(
        part=3, number=13, status=setback_status,
        question="Minimum setbacks",
        detail=f"{setback_description(ctx.adu_type)} {fits_msg}",
        source="Bulletin #210 p.3 + parcel/building geometry",
    ))

    if ctx.is_detached:
        rear_ok = ctx.rear_yard_coverage_pct <= _REAR_YARD_MAX_COVERAGE_PCT
        rear_status = (
            "pass" if (rear_ok and ctx.parcel_area_ft2 > 0)
            else ("verify" if ctx.parcel_area_ft2 <= 0 else "fail")
        )
        items.append(_item(
            part=3, number=14, status=rear_status,
            question="Rear yard coverage — max 40% of rear yard covered by structures (footnote 5, detached only)",
            detail=(
                f"Estimated coverage: {ctx.rear_yard_coverage_pct:.1f}% "
                f"(existing {ctx.existing_footprint_ft2:,.0f} sf + ADU {ctx.adu_area_ft2:,.0f} sf "
                f"over parcel {ctx.parcel_area_ft2:,.0f} sf — parcel used as proxy; actual rear "
                "yard is smaller so real % may be higher). "
                "Not more than 40% of rear yard may be covered by structures (excluding pools)."
            ),
            source="Bulletin #210 footnote 5",
        ))

    items.append(_item(
        part=3, number=14.5,
        status="pass" if ctx.buildable_area_ft2 > 0 else ("fail" if not ctx.is_jadu else "info"),
        question="Buildable area after setbacks",
        detail=(
            f"Computed buildable zone: {ctx.buildable_area_ft2:,.0f} sf "
            "(parcel minus setback buffers and primary-residence clearance)."
            if ctx.buildable_area_ft2 > 0 else
            "No buildable area detected — parcel may be too small or fully covered by the primary."
        ),
        source="Parcel / building geometry model",
    ))

    items.append(_item(
        part=3, number=15, status="verify",
        question="ADU height within limits",
        detail=f"{_HEIGHT_DETAILS[ctx.adu_type]} Confirm final design height before submittal.",
        source="Bulletin #210 p.3 Development Standards table",
    ))

    return items


# ── Part 4: fire safety (Q10–Q15 in Bulletin numbering) ──────────────────────
def _part4_fire_safety(ctx: ChecklistContext) -> list[dict[str, Any]]:
    items = [
        _item(
            part=4, number=16, status="verify",
            question="Q10 (Fire). ADU address legible and visible from the street?",
            detail=(
                "Show both the primary and ADU address on the Site Plan. "
                "ADU gets a unit number visible from the street and near the ADU entry. "
                "Obtain ADU address via Form #302 at addressing@sanjoseca.gov."
            ),
            source="Bulletin #210 Q10 / Form #302",
        ),
        _item(
            part=4, number=17, status="verify",
            question="Q11 (Fire). ADU access: distance from street curb to farthest side of ADU <= 150 ft along a min 4-ft clear path?",
            detail=(
                "Show the distance on the Site Plan along a minimum 4-ft clear path from the front "
                "property line to the ADU's farthest exterior point (including eaves). "
                "If > 150 ft, a Fire Variance may be required (call 408-535-7750)."
            ),
            source="Bulletin #210 Q11 / San Jose Fire",
        ),
        _item(
            part=4, number=18, status="verify",
            question="Q12 (Fire). Hydrant proximity: farthest exterior wall within 600 ft of a fire hydrant?",
            detail=(
                "Mark nearest hydrant(s) on the Site Plan Vicinity Map and show travel distance "
                "(4-ft clear path). If no hydrant within 600 ft, a Fire Variance may be required."
            ),
            source="Bulletin #210 Q12 / SJFD hydrant map",
        ),
        _item(
            part=4, number=19, status="verify",
            question="Q13 (Fire). Hydrant water flow: min 1,000 gpm at 20 psi available?",
            detail=(
                "Request a flow letter from your water company. Submit it with the building permit "
                "application — missing this letter is a leading cause of permit delays. "
                "Email water company with subject 'ADU Water Flow Request'."
            ),
            source="Bulletin #210 Q13 / ADU Fire Requirements webpage",
        ),
        _item(
            part=4, number=20, status="verify",
            question="Q14 (Fire). Is the primary residence protected by fire sprinklers?",
            detail=(
                "If yes, the ADU must also have a fire sprinkler system. "
                "If no, the ADU does not require sprinklers (unless Q15 applies)."
            ),
            source="Bulletin #210 Q14",
        ),
    ]

    q15_applies = ctx.is_attached and ctx.adu_area_ft2 > 500
    items.append(_item(
        part=4, number=21,
        status="verify" if q15_applies else "pass",
        question="Q15 (Fire). Attached ADU > 500 sf AND combined gross floor area with main unit > 3,600 sf?",
        detail=(
            f"Requested ADU: {ctx.adu_area_ft2:,.0f} sf ({ctx.adu_type_label}). "
            + (
                "This is an attached ADU > 500 sf — verify if combined area (primary + ADU) exceeds "
                "3,600 sf. If yes, the entire house + ADU must be fire-sprinklered."
                if q15_applies else
                "Not an attached ADU > 500 sf — this combined-area sprinkler trigger does not apply."
            )
        ),
        source="Bulletin #210 Q15",
    ))
    return items


# ── Part 5: miscellaneous (Q16–Q17) + supplemental info items ────────────────
def _part5_misc(ctx: ChecklistContext) -> list[dict[str, Any]]:
    over_impact_fee = ctx.adu_area_ft2 >= _IMPACT_FEE_THRESHOLD_SQFT
    jadu_owner_occ = (
        "JADU: owner-occupancy required (either the primary or the JADU) UNLESS the JADU has its "
        "own sanitation facilities. Submit Form 313 – JADU Deed Restriction to Planning."
        if ctx.is_jadu else
        "Standard ADU: no owner-occupancy requirement (CA state law through 2030)."
    )

    return [
        _item(
            part=5, number=22,
            status=_designation_status(ctx.heritage, true_status="verify", false_status="pass"),
            question="Q16. Tree removal — will the ADU require removal of a heritage tree?",
            detail=_designation_detail(
                ctx.heritage,
                "View the City Heritage Tree List. If yes, visit sanjoseca.gov/TreePermit.",
            ),
            source=ctx.heritage.source or "San Jose Heritage Trees layer 511 / sanjoseca.gov/TreePermit",
        ),
        _item(
            part=5, number=23,
            status="verify" if over_impact_fee else "pass",
            question="Q17. School & parkland impact fees — ADU >= 750 sf?",
            detail=(
                f"ADU is {ctx.adu_area_ft2:,.0f} sf — school and parkland impact fees apply. "
                "Building permit will not be issued until fees are paid. Staff provides school fee "
                "referral at submittal."
                if over_impact_fee else
                f"ADU is {ctx.adu_area_ft2:,.0f} sf (below 750 sf) — no school or parkland "
                "impact fees."
            ),
            source="Bulletin #210 Q17 / Fees for ADUs webpage",
        ),
        _item(
            part=5, number=24, status="info",
            question="Owner-occupancy requirement",
            detail=jadu_owner_occ,
            source="Bulletin #210 footnote 8 / CA state law (AB 881)",
        ),
        _item(
            part=5, number=25, status="pass",
            question="Parking requirements",
            detail=(
                "No parking required — exemptions: within 0.5 mi of public transit, "
                "conversion of existing space, historic district, or car-share vehicle within 1 block."
            ),
            source="Bulletin #210 p.3 / CA state law (AB 68 / SB 13)",
        ),
        _item(
            part=5, number=26, status="info",
            question="Approval pathway",
            detail=(
                "Ministerial (by-right) review — no discretionary hearing if the ADU meets all "
                "objective standards. Submit via the ADU Plan Review process at sanjoseca.gov/ADUs."
            ),
            source="CA state law / sanjoseca.gov/ADUs",
        ),
    ]


def build_checklist(
    site_model: dict[str, Any],
    *,
    zoning: FetchResult[ZoningData] | None = None,
    general_plan: FetchResult[GeneralPlanData] | None = None,
    designations: dict[str, FetchResult[DesignationData]] | None = None,
    property_stats: dict[str, Any] | None = None,
    adu_type: str = "detached",
    permits: FetchResult[PermitsData] | None = None,
    code_enforcement: FetchResult[CodeEnforcementData] | None = None,
) -> list[dict[str, Any]]:
    """Compose the full San Jose ADU Universal Checklist."""
    ctx = ChecklistContext.from_site_model(
        site_model,
        zoning=zoning,
        general_plan=general_plan,
        designations=designations,
        property_stats=property_stats,
        adu_type=adu_type,
        permits=permits,
        code_enforcement=code_enforcement,
    )
    return [
        *_part1_property_qualification(ctx),
        *_part2_designations(ctx),
        *_part3_development_standards(ctx),
        *_part4_fire_safety(ctx),
        *_part5_misc(ctx),
    ]
