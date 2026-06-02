"""California state-level ADU rules that apply to every CA city.

Each city's adapter layers its own "City Standards" on top of these. The
constants and checklist-item functions here come from CA Government Code
§§66310-66342 and stay stable across SJ, SF, and Oakland.
"""

from app.rules_common.property_type import property_type_from_style
from app.rules_common.state_standards import (
    STATE_DETACHED_MAX_SQFT,
    STATE_DETACHED_MAX_SQFT_PITCHED_ROOF,
    STATE_IMPACT_FEE_SQFT_THRESHOLD,
    STATE_MAX_HEIGHT_FT,
    STATE_PARKING_TRANSIT_EXEMPTION_MILES,
    STATE_SIDE_REAR_SETBACK_FT,
    ca_impact_fees,
    ca_ministerial_review,
    ca_owner_occupancy,
    ca_parking,
)

__all__ = [
    # constants
    "STATE_DETACHED_MAX_SQFT",
    "STATE_DETACHED_MAX_SQFT_PITCHED_ROOF",
    "STATE_IMPACT_FEE_SQFT_THRESHOLD",
    "STATE_MAX_HEIGHT_FT",
    "STATE_PARKING_TRANSIT_EXEMPTION_MILES",
    "STATE_SIDE_REAR_SETBACK_FT",
    # checklist-item functions
    "ca_impact_fees",
    "ca_ministerial_review",
    "ca_owner_occupancy",
    "ca_parking",
    # shared utilities
    "property_type_from_style",
]
