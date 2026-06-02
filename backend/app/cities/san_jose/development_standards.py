"""San Jose ADU development standards engine.

Loads sj_adu_standards_city.json or sj_adu_standards_state.json and resolves
the full constraint set for a given ADU configuration. This is the Python port
of the (now deleted) cityRulesEngine.js / stateRulesEngine.js — all rule logic
lives here; the JSON files are pure data with no string values.

City vs State is the only dimension that toggles. Everything else (compliance,
designations, permits, code enforcement) is always city.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

_DATA_DIR = Path(__file__).parents[4] / "data"

StandardSet = Literal["city", "state"]
PropertyType = Literal["single_family", "multifamily"]
AduType = Literal["detached", "attached", "jadu"]


@dataclass(frozen=True)
class AduConstraints:
    max_adu_size_sf: float
    min_side_setback_ft: float
    min_rear_setback_ft: float
    front_setback_ft: float
    siting_min_front_offset_ft: float | None
    max_height_ft: float | None   # None = existing structure height (JADU)
    max_rear_yard_coverage_pct: float | None
    min_building_separation_ft: float | None
    front_setback_encroachment_active: bool


# JADU is always city-only and within the existing footprint.
# Setbacks = those of the existing structure; height = existing structure.
JADU_CONSTRAINTS = AduConstraints(
    max_adu_size_sf=500.0,
    min_side_setback_ft=0.0,
    min_rear_setback_ft=0.0,
    front_setback_ft=0.0,
    siting_min_front_offset_ft=None,
    max_height_ft=None,
    max_rear_yard_coverage_pct=None,
    min_building_separation_ft=None,
    front_setback_encroachment_active=False,
)


@lru_cache(maxsize=2)
def _load(standard_set: StandardSet) -> dict:
    path = _DATA_DIR / f"sj_adu_standards_{standard_set}.json"
    with path.open() as f:
        return json.load(f)


def normalize_property_type(raw: str) -> PropertyType:
    """Map HomeHarvest / ArcGIS property-type strings to JSON keys."""
    s = (raw or "").lower()
    if any(x in s for x in ("duplex", "multi", "apartment", "condo", "townhouse")):
        return "multifamily"
    return "single_family"


def get_constraints(
    standard: StandardSet,
    property_type: PropertyType,
    adu_type: AduType,
    stories: int,
    zone: str,
    *,
    lot_size_sf: float = 0.0,
    main_home_livable_sf: float | None = None,
    lot_width_ft: float | None = None,
    lot_depth_ft: float | None = None,
    home_footprint: dict | None = None,
) -> AduConstraints:
    """Return resolved constraints for the given ADU configuration.

    JADU is always handled by JADU_CONSTRAINTS regardless of standard.
    City inputs:   lot_size_sf, main_home_livable_sf
    State inputs:  lot_width_ft, lot_depth_ft, home_footprint
                   home_footprint = {x, y, width, depth} all in ft
                   x/y = distance from left/front property line
    """
    if adu_type == "jadu":
        return JADU_CONSTRAINTS
    standards = _load(standard)
    if standard == "city":
        return _city_constraints(
            standards, property_type, adu_type, stories, zone,
            lot_size_sf, main_home_livable_sf,
        )
    return _state_constraints(
        standards, property_type, adu_type, stories, zone,
        lot_width_ft, lot_depth_ft, home_footprint,
    )


# ── City ─────────────────────────────────────────────────────────────────────

def _city_constraints(
    standards: dict,
    property_type: PropertyType,
    adu_type: AduType,
    stories: int,
    zone: str,
    lot_size_sf: float,
    main_home_livable_sf: float | None,
) -> AduConstraints:
    s = standards[property_type][adu_type]
    front_setback_ft = float(standards["front_setbacks_by_zone"].get(zone, 20))
    threshold = standards["lot_size_threshold_sf"]

    # Max ADU size — lot-tier selection then optional 50% cap
    size_block = (
        s["max_size_sf"]["lot_lte_9000_sf"]
        if lot_size_sf <= threshold
        else s["max_size_sf"]["lot_gt_9000_sf"]
    )
    if isinstance(size_block, dict):
        lot_cap = float(size_block["value_sf"])
        nested_cap = bool(size_block.get("fifty_pct_of_main_home_cap", False))
    else:
        lot_cap = float(size_block)
        nested_cap = False

    # SF attached carries fifty_pct_of_main_home_cap at the top level of max_size_sf
    top_level_cap = bool(s["max_size_sf"].get("fifty_pct_of_main_home_cap", False))

    if (nested_cap or top_level_cap) and main_home_livable_sf and main_home_livable_sf > 0:
        max_adu_size_sf = min(lot_cap, math.floor(main_home_livable_sf * 0.5))
    else:
        max_adu_size_sf = lot_cap

    return AduConstraints(
        max_adu_size_sf=max_adu_size_sf,
        min_side_setback_ft=_resolve_setback(s["min_side_setback_ft"], stories),
        min_rear_setback_ft=_resolve_setback(s["min_rear_setback_ft"], stories),
        front_setback_ft=front_setback_ft,
        siting_min_front_offset_ft=s["siting_min_front_offset_ft"],
        max_height_ft=_resolve_height(s["max_height_ft"], stories),
        max_rear_yard_coverage_pct=s.get("max_rear_yard_coverage_pct"),
        min_building_separation_ft=s.get("min_building_separation_ft"),
        front_setback_encroachment_active=False,
    )


# ── State ─────────────────────────────────────────────────────────────────────

def _state_constraints(
    standards: dict,
    property_type: PropertyType,
    adu_type: AduType,
    stories: int,
    zone: str,
    lot_width_ft: float | None,
    lot_depth_ft: float | None,
    home_footprint: dict | None,
) -> AduConstraints:
    s = standards[property_type][adu_type]
    zone_front_setback = float(standards["front_setbacks_by_zone"].get(zone, 20))

    encroachment_active = False
    if (
        s.get("front_setback_encroachment_allowed")
        and lot_width_ft is not None
        and lot_depth_ft is not None
        and home_footprint is not None
    ):
        fits = _can_fit_800sf(
            lot_width=lot_width_ft,
            lot_depth=lot_depth_ft,
            front_setback=zone_front_setback,
            side_setback=float(s["min_side_setback_ft"]),
            rear_setback=float(s["min_rear_setback_ft"]),
            home_x=float(home_footprint["x"]),
            home_y=float(home_footprint["y"]),
            home_w=float(home_footprint["width"]),
            home_d=float(home_footprint["depth"]),
        )
        encroachment_active = not fits

    return AduConstraints(
        max_adu_size_sf=float(s["max_size_sf"]),
        min_side_setback_ft=float(s["min_side_setback_ft"]),
        min_rear_setback_ft=float(s["min_rear_setback_ft"]),
        front_setback_ft=0.0 if encroachment_active else zone_front_setback,
        siting_min_front_offset_ft=None,
        max_height_ft=_resolve_height(s["max_height_ft"], stories),
        max_rear_yard_coverage_pct=None,
        min_building_separation_ft=None,
        front_setback_encroachment_active=encroachment_active,
    )


def _can_fit_800sf(
    lot_width: float,
    lot_depth: float,
    front_setback: float,
    side_setback: float,
    rear_setback: float,
    home_x: float,
    home_y: float,
    home_w: float,
    home_d: float,
) -> bool:
    """Return True if an 800 sf ADU fits anywhere on the lot under normal setbacks."""
    # Rear yard (most common placement zone)
    rear_buildable_width = lot_width - side_setback * 2
    home_rear_edge = home_y + home_d
    rear_buildable_depth = lot_depth - home_rear_edge - rear_setback
    if rear_buildable_width > 0 and rear_buildable_depth > 0:
        if rear_buildable_width * rear_buildable_depth >= 800:
            return True

    side_strip_depth = lot_depth - front_setback - rear_setback

    # Left side strip (between side setback and home left edge)
    left_strip_width = home_x - side_setback
    if left_strip_width > 0 and side_strip_depth > 0:
        if left_strip_width * side_strip_depth >= 800:
            return True

    # Right side strip (between home right edge and side setback)
    right_strip_width = (lot_width - (home_x + home_w)) - side_setback
    if right_strip_width > 0 and side_strip_depth > 0:
        if right_strip_width * side_strip_depth >= 800:
            return True

    return False


# ── Shared helpers ────────────────────────────────────────────────────────────

def _resolve_setback(field: int | float | dict, stories: int) -> float:
    if isinstance(field, dict):
        return float(field[f"story_{stories}"])
    return float(field)


def _resolve_height(field: int | float | dict, stories: int) -> float:
    if isinstance(field, dict):
        return float(field[f"story_{stories}"])
    return float(field)
