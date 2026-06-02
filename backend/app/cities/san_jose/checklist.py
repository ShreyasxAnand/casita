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

from app.cities.san_jose.code_enforcement import CodeEnforcementData, CodeIssue
from app.cities.san_jose.designations import DesignationData
from app.cities.san_jose.development_standards import (
    AduConstraints,
    get_constraints,
    normalize_property_type,
)
from app.cities.san_jose.permits import PermitRecord, PermitsData
from app.cities.san_jose.zoning import (
    GeneralPlanData,
    ZoningData,
    adu_eligibility,
    property_type_from_style,
)
from app.result import FetchResult
from app.rules_common.state_standards import (
    ca_impact_fees,
    ca_ministerial_review,
    ca_owner_occupancy,
    ca_parking,
)

ADU_TYPE_LABELS = {
    "detached": "Detached ADU",
    "attached": "Attached ADU",
    "jadu": "JADU",
}


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
    adu_height_ft: float
    adu_area_ft2: float
    existing_footprint_ft2: float
    building_count: int
    front_edge_index: int | None
    rear_yard_coverage_pct: float
    fits_requested_size: bool
    property_type: str
    property_type_source: str
    primary_sqft: float | None
    allowed: bool | None  # None when zoning/GP data was unavailable
    allowed_reason: str
    standards: str          # "city" | "state"
    constraints: AduConstraints

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

    @property
    def has_primary_outline(self) -> bool:
        return self.building_count > 0 and self.existing_footprint_ft2 > 0

    @property
    def geometry_needs_primary_outline(self) -> bool:
        sep = self.constraints.min_building_separation_ft
        return self.is_attached or (sep is not None and sep > 0)

    @property
    def geometry_needs_front_edge(self) -> bool:
        offset = self.constraints.siting_min_front_offset_ft
        setback = self.constraints.front_setback_ft
        return (offset is not None and offset > 0) or setback > 0

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
        standards: str = "city",
        adu_stories: int = 1,
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
        adu_h = float(adu.get("height_ft") or 16.0)
        adu_area = adu_w * adu_d
        buildings = site_model.get("buildings") or []
        # JADUs must fit within the existing primary residence/attached garage.
        # Use the largest loaded building outline as the primary candidate;
        # summing multiple detached structures could incorrectly make a JADU
        # look feasible.
        existing_footprint = max(
            (float(b.get("area_ft2") or 0) for b in buildings),
            default=0.0,
        )
        rear_coverage = adu_area / parcel_area * 100 if parcel_area > 0 else 0.0

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

        # Prefer pre-computed constraints embedded by the pipeline (includes encroachment state).
        # Fall back to computing them here when called outside the pipeline (e.g. tests).
        constraints_dict = site_model.get("applied_constraints")
        if constraints_dict:
            constraints = AduConstraints(**constraints_dict)
        else:
            zone = zoning_code_hint
            prop_type_key = normalize_property_type(property_type)
            rule_adu_type = (
                adu_type_key if adu_type_key in ("detached", "attached", "jadu")
                else "detached"
            )
            constraints = get_constraints(
                standards, prop_type_key, rule_adu_type, adu_stories, zone,  # type: ignore[arg-type]
                lot_size_sf=parcel_area,
                main_home_livable_sf=primary_sqft,
            )

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
            adu_height_ft=adu_h,
            adu_area_ft2=adu_area,
            existing_footprint_ft2=existing_footprint,
            building_count=len(buildings),
            front_edge_index=buildable.get("front_edge_index"),
            rear_yard_coverage_pct=rear_coverage,
            fits_requested_size=bool(adu.get("fits_requested_size")),
            property_type=property_type,
            property_type_source=pt_source,
            primary_sqft=primary_sqft,
            allowed=allowed,
            allowed_reason=allowed_reason,
            standards=standards,
            constraints=constraints,
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
_TYPE_SELECTOR_DETAILS = {
    "detached": (
        "Detached ADU — a standalone structure separate from the primary home. "
        "City Standards (§20.80.175): must be in the rear yard or >= 45 ft from front property line; "
        "min 6 ft separation from main home; max 40% rear yard coverage. "
        "State Standards (§20.80.176): no siting restriction."
    ),
    "attached": (
        "Attached ADU — shares a wall or structural element with the primary home. "
        "No additional siting restriction beyond applicable setbacks — can be located in the "
        "front yard only outside the required front setback. "
        "Front door must be on a DIFFERENT facade from the main home entry."
    ),
    "jadu": (
        "JADU (Junior ADU) — built entirely within the existing footprint of the single-family "
        "home (including attached garage), or within a proposed new SFR. Max 500 sf. "
        "Up to 150 sf may be added for ingress/egress only. "
        "Owner-occupancy required (unless JADU has its own sanitation facilities)."
    ),
}


def _siting_detail(ctx: ChecklistContext) -> str:
    c = ctx.constraints
    if ctx.is_jadu:
        return (
            "JADU: must remain within the existing footprint of the single-family home "
            "(including an attached garage). Up to 150 sf may be added for ingress/egress only."
        )
    if c.siting_min_front_offset_ft is not None:
        sep = f"Min {c.min_building_separation_ft:.0f} ft" if c.min_building_separation_ft else "Min building"
        cov = f"Max {c.max_rear_yard_coverage_pct:.0f}% rear yard coverage." if c.max_rear_yard_coverage_pct else ""
        return (
            f"Detached ADU ({ctx.standards.capitalize()} Standards): must be behind the main home OR "
            f">= {c.siting_min_front_offset_ft:.0f} ft from the front property line. "
            f"{sep} separation from main home required. {cov}"
        )
    if ctx.is_attached:
        return (
            f"Attached ADU ({ctx.standards.capitalize()} Standards): no additional siting "
            "restriction beyond applicable setbacks; front-yard placement still must respect "
            "the required front setback. "
            "Front door must be on a different facade than the main home entry."
        )
    encroach = (
        " Front setback encroachment active: waived because an 800 sf ADU cannot fit elsewhere."
        if c.front_setback_encroachment_active else ""
    )
    return (
        f"Detached ADU (State Standards §20.80.176): no siting restriction — "
        f"may be placed anywhere on the parcel.{encroach}"
    )


def _height_detail(ctx: ChecklistContext) -> str:
    c = ctx.constraints
    if ctx.is_jadu or c.max_height_ft is None:
        return "JADU: no independent height limit — height is that of the existing primary structure."
    std_label = "City" if ctx.standards == "city" else "State"
    return (
        f"{ctx.adu_type_label} ({std_label} Standards): max {c.max_height_ft:.0f} ft. "
        "Confirm final design height before submittal."
    )


def _size_status(ctx: ChecklistContext) -> tuple[str, float]:
    if ctx.parcel_area_ft2 <= 0:
        return "verify", 0.0
    max_sf = ctx.constraints.max_adu_size_sf
    overage = max(0.0, ctx.adu_area_ft2 - max_sf)
    return ("pass" if overage == 0 else "fail"), overage


def _size_detail(ctx: ChecklistContext) -> str:
    c = ctx.constraints
    std_label = "City" if ctx.standards == "city" else "State"
    detail = (
        f"Requested: {ctx.adu_area_ft2:,.0f} sf ({ctx.adu_width_ft:.0f} × {ctx.adu_depth_ft:.0f} ft). "
        f"Max allowable: {c.max_adu_size_sf:,.0f} sf ({std_label} Standards, {ctx.adu_type_label})."
    )
    _, overage = _size_status(ctx)
    if overage > 0:
        detail += f" OVER by {overage:,.0f} sf — reduce footprint or switch to a smaller type."
    if ctx.primary_sqft and ctx.is_attached:
        detail += (
            f" Attached cap: 50% of {ctx.primary_sqft:,.0f} sf primary = "
            f"{ctx.primary_sqft * 0.5:,.0f} sf; capped at lot-tier max {c.max_adu_size_sf:,.0f} sf."
        )
    if ctx.is_jadu:
        detail += " JADU must remain within the existing primary footprint."
    return detail


def _setback_detail(ctx: ChecklistContext) -> str:
    c = ctx.constraints
    zone = ctx.zoning_result.data.zoning if ctx.zoning_result.data else "unknown zone"
    parts = [
        f"Front setback: {c.front_setback_ft:.0f} ft ({zone} per Table 20-60).",
        f"Side setback: {c.min_side_setback_ft:.0f} ft.",
        f"Rear setback: {c.min_rear_setback_ft:.0f} ft.",
    ]
    if c.siting_min_front_offset_ft is not None:
        parts.append(
            f"Siting: must be behind the main home OR >= {c.siting_min_front_offset_ft:.0f} ft "
            "from the front property line."
        )
    if ctx.geometry_needs_front_edge:
        if ctx.front_edge_index is None:
            parts.append(
                "Front property line was not selected, so the geometry model did not enforce "
                "the front setback/siting distance."
            )
        else:
            parts.append("Selected front property line was used for the geometry model.")
    if c.min_building_separation_ft is not None:
        parts.append(f"Min {c.min_building_separation_ft:.0f} ft separation from main home.")
        if not ctx.has_primary_outline:
            parts.append(
                "No primary-residence footprint was found, so separation from the main home "
                "could not be verified."
            )
    elif ctx.is_attached and not ctx.has_primary_outline:
        parts.append(
            "No primary-residence footprint was found, so the required attachment to the "
            "main home could not be verified."
        )
    if ctx.standards == "state" and c.front_setback_encroachment_active:
        parts.append(
            "Front setback encroachment active (§20.80.176): waived because an 800 sf ADU "
            "cannot fit elsewhere on the lot."
        )
    return " ".join(parts)


def _setback_status_and_message(ctx: ChecklistContext) -> tuple[str, str]:
    if ctx.is_jadu:
        if not ctx.has_primary_outline:
            return (
                "verify",
                "No primary-home footprint was found, so the app cannot verify that the "
                "JADU remains within the existing single-family home or attached garage.",
            )
        if ctx.adu_area_ft2 > ctx.existing_footprint_ft2:
            return (
                "fail",
                f"Requested JADU area ({ctx.adu_area_ft2:,.0f} sf) exceeds the loaded "
                f"primary footprint ({ctx.existing_footprint_ft2:,.0f} sf).",
            )
        return (
            "verify",
            "JADU setbacks are those of the existing structure. Confirm on the site plan "
            "that the JADU is entirely within the existing single-family home or attached "
            "garage; this app does not verify interior layout.",
        )

    uncertainty: list[str] = []
    if ctx.geometry_needs_front_edge and ctx.front_edge_index is None:
        uncertainty.append(
            "front property line was not selected, so the front setback/siting distance "
            "was not enforced in geometry"
        )
    if ctx.geometry_needs_primary_outline and not ctx.has_primary_outline:
        if ctx.is_attached:
            uncertainty.append(
                "no primary-residence footprint was found, so attachment to the main home "
                "could not be verified"
            )
        else:
            uncertainty.append(
                "no primary-residence footprint was found, so required building separation "
                "was not enforced"
            )

    if not ctx.fits_requested_size:
        return (
            "verify",
            "ADU footprint does not fit the computed buildable zone — verify manual "
            "placement or reduce size.",
        )
    if uncertainty:
        return (
            "verify",
            "At the requested dimensions, the ADU fits the partial computed buildable zone, "
            f"but {', and '.join(uncertainty)}.",
        )
    return (
        "pass",
        f"At {ctx.adu_width_ft:.0f} × {ctx.adu_depth_ft:.0f} ft, the ADU fits inside "
        "the computed buildable zone.",
    )


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

    std_label = "City" if ctx.standards == "city" else "State"
    std_code = "20.80.175" if ctx.standards == "city" else "20.80.176"

    items.append(_item(
        part=3, number=10.5, status="info",
        question=f"ADU type selected: {ctx.adu_type_label} ({std_label} Standards)",
        detail=_TYPE_SELECTOR_DETAILS.get(ctx.adu_type, "Unknown type selected."),
        source=f"Bulletin #210 {std_label} Development Standards (§{std_code})",
    ))

    size_status, _ = _size_status(ctx)
    items.append(_item(
        part=3, number=11, status=size_status,
        question=f"ADU maximum size ({std_label} Development Standards §{std_code})",
        detail=_size_detail(ctx),
        source=f"Bulletin #210 / Municipal Code {std_code}",
    ))

    siting_status = "pass" if ctx.is_attached else ("info" if ctx.is_jadu else "verify")
    items.append(_item(
        part=3, number=12, status=siting_status,
        question=f"ADU siting — where can the {ctx.adu_type_label} be located on the parcel?",
        detail=_siting_detail(ctx),
        source=f"Bulletin #210 {std_label} Development Standards table",
    ))

    setback_status, fits_msg = _setback_status_and_message(ctx)
    items.append(_item(
        part=3, number=13, status=setback_status,
        question="Minimum setbacks",
        detail=f"{_setback_detail(ctx)} {fits_msg}",
        source=f"Bulletin #210 {std_label} Standards + parcel/building geometry",
    ))

    max_coverage = ctx.constraints.max_rear_yard_coverage_pct
    if ctx.is_detached and max_coverage is not None:
        items.append(_item(
            part=3, number=14, status="verify",
            question=f"Rear yard coverage — max {max_coverage:.0f}% of rear yard covered by structures (detached only)",
            detail=(
                "Must be verified manually. "
                f"Estimated ADU coverage: {ctx.rear_yard_coverage_pct:.1f}% "
                f"(ADU {ctx.adu_area_ft2:,.0f} sf over entire parcel {ctx.parcel_area_ft2:,.0f} sf). "
                "Parcel used as proxy; actual rear yard is smaller so real % may be higher. "
                "Add any other existing rear-yard structures to this percentage. "
                f"Max {max_coverage:.0f}% of rear yard may be covered (excluding pools)."
            ),
            source="Bulletin #210 footnote 5",
        ))

    if ctx.is_jadu:
        if not ctx.has_primary_outline:
            buildable_status = "verify"
            buildable_detail = (
                "No primary-residence footprint was found, so the app cannot identify "
                "the existing footprint available for a JADU."
            )
        elif ctx.adu_area_ft2 > ctx.existing_footprint_ft2:
            buildable_status = "fail"
            buildable_detail = (
                f"Requested JADU area ({ctx.adu_area_ft2:,.0f} sf) exceeds the largest "
                f"loaded primary-footprint candidate ({ctx.existing_footprint_ft2:,.0f} sf)."
            )
        else:
            buildable_status = "verify"
            buildable_detail = (
                f"JADU candidate footprint: {ctx.existing_footprint_ft2:,.0f} sf from the "
                "largest loaded building outline. This verifies exterior footprint capacity "
                "only; confirm the JADU is entirely within the existing single-family home "
                "or attached garage on the site plan."
            )
    elif ctx.buildable_area_ft2 <= 0:
        buildable_status = "fail" if not ctx.is_jadu else "info"
        buildable_detail = (
            "No buildable area detected — parcel may be too small or fully covered by the primary."
        )
    elif ctx.geometry_needs_primary_outline and not ctx.has_primary_outline:
        buildable_status = "verify"
        if ctx.is_attached:
            buildable_detail = (
                f"Computed partial buildable zone: {ctx.buildable_area_ft2:,.0f} sf. "
                "No primary-residence footprint was found, so the app cannot verify that "
                "the attached ADU shares a wall or structural element with the main home."
            )
        else:
            buildable_detail = (
                f"Computed partial buildable zone: {ctx.buildable_area_ft2:,.0f} sf. "
                "No primary-residence footprint was found, so this area is only the parcel after "
                "setbacks and does not subtract required clearance from the main home."
            )
    elif ctx.geometry_needs_front_edge and ctx.front_edge_index is None:
        buildable_status = "verify"
        buildable_detail = (
            f"Computed partial buildable zone: {ctx.buildable_area_ft2:,.0f} sf. "
            "Front property line was not selected, so front siting/setback geometry was not applied."
        )
    else:
        buildable_status = "pass"
        buildable_detail = (
            f"Computed buildable zone: {ctx.buildable_area_ft2:,.0f} sf "
            "(parcel minus setback buffers and primary-residence clearance)."
        )

    items.append(_item(
        part=3, number=14.5,
        status=buildable_status,
        question="Buildable area after setbacks",
        detail=buildable_detail,
        source="Parcel / building geometry model",
    ))

    c = ctx.constraints
    if ctx.is_jadu or c.max_height_ft is None:
        height_status = "verify" if ctx.is_jadu else "pass"
    else:
        height_status = "pass" if ctx.adu_height_ft <= c.max_height_ft else "fail"

    items.append(_item(
        part=3, number=15, status=height_status,
        question="ADU height within limits",
        detail=(
            f"Requested: {ctx.adu_height_ft:.1f} ft. {_height_detail(ctx)}"
            + (
                f" OVER by {ctx.adu_height_ft - c.max_height_ft:.1f} ft."
                if height_status == "fail" and c.max_height_ft is not None else ""
            )
        ),
        source=f"Bulletin #210 {std_label} Development Standards table",
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
        # Items 23–26 are CA state-law items shared across all CA cities.
        ca_impact_fees(ctx.adu_area_ft2, part=5, number=23),
        ca_owner_occupancy(ctx.adu_type, part=5, number=24),
        ca_parking(part=5, number=25),
        ca_ministerial_review("sanjoseca.gov/ADUs", part=5, number=26),
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
    standards: str = "city",
    adu_stories: int = 1,
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
        standards=standards,
        adu_stories=adu_stories,
    )
    return [
        *_part1_property_qualification(ctx),
        *_part2_designations(ctx),
        *_part3_development_standards(ctx),
        *_part4_fire_safety(ctx),
        *_part5_misc(ctx),
    ]
