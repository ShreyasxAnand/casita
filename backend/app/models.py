"""Request models + small response-envelope helpers."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field


class SiteRequest(BaseModel):
    """User-supplied parameters for `POST /api/site`."""

    address: str = Field(
        "",
        description="San Jose street address to geocode and load from city parcel GIS.",
    )
    include_checklist: bool = False
    adu_type: str = Field(
        "detached",
        description=(
            "ADU type: 'detached', 'attached', or 'jadu'. Controls size limits, "
            "setbacks, and siting rules per Bulletin #210."
        ),
    )
    # Tightened from the legacy 8–60 ft range. Real ADUs fall comfortably
    # inside 10–35 ft on each dimension; the prior upper bound let users
    # request 60-ft "ADUs" that would never be code-compliant.
    adu_width_ft: float = Field(30.0, ge=8.0, le=40.0)
    adu_depth_ft: float = Field(40.0, ge=8.0, le=60.0)
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
