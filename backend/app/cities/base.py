"""City-agnostic interface for the ADU compliance pipeline.

`CityAdapter` is the contract every supported city implements. `run_site_pipeline`
operates against this Protocol — it knows nothing about San Jose ArcGIS URLs,
San Francisco zoning vocabularies, or Oakland bulletin numbering. Each adapter
wires its own clients, rules, and checklist together.

Shape choices:
  * `GeocodeResult` is shared because the pipeline needs `latitude`, `longitude`,
    `zip_code`, etc. to drive every downstream call. The matched `city` field is
    how `CityAdapter.validate_address_match` enforces that the geocoded point
    actually lives in the city the user selected.
  * Zoning / GP / permits / code-enforcement / designation data shapes stay
    city-specific (San Jose's `facility_id` does not exist in SF), so the
    pipeline treats those as opaque `FetchResult` values and asks the adapter
    to serialize them for the response envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from app.result import FetchResult


@dataclass(frozen=True)
class GeocodeResult:
    matched_address: str
    latitude:        float
    longitude:       float
    score:           float
    normalized_input: str
    zip_code:        str
    city:            str
    state:           str


@runtime_checkable
class CityAdapter(Protocol):
    """Everything a city plugs into the shared pipeline.

    Methods return values that the pipeline either passes verbatim through the
    response (parcel/building FeatureCollections, stage entries) or hands back
    to the adapter for serialization (typed FetchResults).
    """

    name: str          # registry key, e.g. "san_jose"
    display_name: str  # human label, e.g. "San Jose"
    docs_url: str      # external URL shown in the UI header

    # ── address resolution ──────────────────────────────────────────────
    async def geocode(self, client: httpx.AsyncClient, address: str) -> GeocodeResult: ...

    # ── parcel + building outlines ──────────────────────────────────────
    async def fetch_parcel(
        self, client: httpx.AsyncClient, latitude: float, longitude: float,
    ) -> tuple[dict[str, Any], str]:
        """Return (parcel GeoJSON feature, source tag)."""

    async def fetch_buildings(
        self, client: httpx.AsyncClient, parcel_feature: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """Return (FeatureCollection of building outlines, source tag)."""

    # ── zoning + designations + permits ─────────────────────────────────
    async def fetch_zoning_and_gp(
        self, client: httpx.AsyncClient, latitude: float, longitude: float,
    ) -> tuple[FetchResult[Any], FetchResult[Any], list[dict[str, Any]]]:
        """Return (zoning_result, general_plan_result, stage entries)."""

    async def fetch_designations(
        self,
        client: httpx.AsyncClient,
        latitude: float,
        longitude: float,
        parcel_feature: dict[str, Any],
    ) -> tuple[dict[str, FetchResult[Any]], dict[str, Any]]:
        """Return (mapping designation_key -> FetchResult, single stage entry)."""

    async def fetch_permits_and_enforcement(
        self,
        client: httpx.AsyncClient,
        apn: str | None,
        latitude: float,
        longitude: float,
    ) -> tuple[FetchResult[Any], FetchResult[Any], list[dict[str, Any]]]:
        """Return (permits_result, code_enforcement_result, stage entries)."""

    # ── parcel identifier ───────────────────────────────────────────────
    def parcel_id(self, parcel_fc: dict[str, Any]) -> str | None:
        """Stable identifier (APN or equivalent) extracted from the parcel FC.

        Used as the job-id prefix. Falls back to an address hash when absent.
        """

    # ── checklist ───────────────────────────────────────────────────────
    def build_checklist(
        self,
        site_model: dict[str, Any],
        *,
        zoning: FetchResult[Any] | None,
        general_plan: FetchResult[Any] | None,
        designations: dict[str, FetchResult[Any]] | None,
        property_stats: dict[str, Any] | None,
        adu_type: str,
        permits: FetchResult[Any] | None,
        code_enforcement: FetchResult[Any] | None,
        standards: str = "city",
        adu_stories: int = 1,
    ) -> list[dict[str, Any]]: ...

    # ── response serializers ────────────────────────────────────────────
    def serialize_zoning(self, result: FetchResult[Any]) -> dict[str, Any]: ...
    def serialize_general_plan(self, result: FetchResult[Any]) -> dict[str, Any]: ...
    def serialize_designation(self, result: FetchResult[Any]) -> dict[str, Any]: ...
    def serialize_permits(self, result: FetchResult[Any]) -> dict[str, Any]: ...
    def serialize_code_enforcement(self, result: FetchResult[Any]) -> dict[str, Any]: ...
