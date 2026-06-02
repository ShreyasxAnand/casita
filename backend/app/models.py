"""Request models + small response-envelope helpers."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

City = Literal["san_jose", "sf", "oakland"]
Standards = Literal["city", "state"]


class SiteRequest(BaseModel):
    """User-supplied parameters for `POST /api/site`."""

    city: City = Field(
        "san_jose",
        description=(
            "Which city's ADU compliance rules and GIS sources to use. "
            "The geocoder enforces that the typed address actually falls inside "
            "the selected city's bounds."
        ),
    )
    address: str = Field(
        "",
        description="Street address to geocode and load from the city's parcel GIS.",
    )
    include_checklist: bool = False
    standards: Standards = Field(
        "city",
        description=(
            "Development standards to apply for size, setbacks, siting, and height. "
            "'city' = Municipal Code 20.80.175 (City Standards). "
            "'state' = Municipal Code 20.80.176 (State Standards). "
            "All compliance checks (designations, permits, fire safety) always use city rules."
        ),
    )
    adu_type: str = Field(
        "detached",
        description=(
            "ADU type: 'detached', 'attached', or 'jadu'. Controls size limits, "
            "setbacks, and siting rules per Bulletin #210."
        ),
    )
    adu_stories: int = Field(
        1,
        ge=1,
        le=2,
        description="Number of stories for the ADU. Affects setbacks and max height.",
    )
    # Tightened from the legacy 8–60 ft range. Real ADUs fall comfortably
    # inside 10–35 ft on each dimension; the prior upper bound let users
    # request 60-ft "ADUs" that would never be code-compliant.
    adu_width_ft: float = Field(30.0, ge=8.0, le=40.0)
    adu_depth_ft: float = Field(40.0, ge=8.0, le=60.0)
    adu_height_ft: float = Field(16.0, ge=10.0, le=24.0)
    front_edge_index: int | None = Field(
        None,
        description="Index of the parcel ring edge the user identified as facing the street.",
    )
    build_cost_per_sqft: float = Field(350.0, ge=100.0, le=1500.0)
    down_payment_pct: float = Field(0.20, ge=0.0, le=1.0)
    interest_rate_pct: float = Field(7.5, ge=0.0, le=20.0)
    loan_term_years: int = Field(30, ge=5, le=40)


def stage(
    name: str, start: float, detail: str, data: dict[str, Any] | None = None,
    *, status: str = "ok",
) -> dict[str, Any]:
    """Build one entry of the response `stages` array.

    `stages` is a per-request trace surfaced to the frontend so users can see
    which external services were called and how long each took.
    """
    return {
        "name": name,
        "status": status,
        "duration_ms": round((time.perf_counter() - start) * 1000),
        "detail": detail,
        "data": data,
        "log_tail": None,
    }


def warn_stage(name: str, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "warn",
        "duration_ms": 0,
        "detail": detail,
        "data": None,
        "log_tail": None,
    }
