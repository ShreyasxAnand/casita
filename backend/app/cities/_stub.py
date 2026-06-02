"""Shared base for not-yet-implemented city adapters.

SF and Oakland will get their own real implementations in follow-up passes —
this scaffolding lets them register in the city dropdown and return a
friendly 501 if someone hits them today, instead of crashing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException

from app.cities.base import GeocodeResult
from app.result import FetchResult


@dataclass(frozen=True)
class StubAdapter:
    """Raises 501 from any pipeline call. Subclasses just override the
    `name`, `display_name`, and `docs_url` fields."""

    name: str
    display_name: str
    docs_url: str

    def _not_implemented(self) -> HTTPException:
        return HTTPException(
            501,
            f"{self.display_name} ADU compliance is not yet supported. "
            "Choose San Jose from the dropdown.",
        )

    async def geocode(self, client: httpx.AsyncClient, address: str) -> GeocodeResult:
        raise self._not_implemented()

    async def fetch_parcel(
        self, client: httpx.AsyncClient, latitude: float, longitude: float,
    ) -> tuple[dict[str, Any], str]:
        raise self._not_implemented()

    async def fetch_buildings(
        self, client: httpx.AsyncClient, parcel_feature: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        raise self._not_implemented()

    def parcel_id(self, parcel_fc: dict[str, Any]) -> str | None:
        return None

    async def fetch_zoning_and_gp(
        self, client: httpx.AsyncClient, latitude: float, longitude: float,
    ) -> tuple[FetchResult[Any], FetchResult[Any], list[dict[str, Any]]]:
        raise self._not_implemented()

    async def fetch_designations(
        self,
        client: httpx.AsyncClient,
        latitude: float,
        longitude: float,
        parcel_feature: dict[str, Any],
    ) -> tuple[dict[str, FetchResult[Any]], dict[str, Any]]:
        raise self._not_implemented()

    async def fetch_permits_and_enforcement(
        self,
        client: httpx.AsyncClient,
        apn: str | None,
        latitude: float,
        longitude: float,
    ) -> tuple[FetchResult[Any], FetchResult[Any], list[dict[str, Any]]]:
        raise self._not_implemented()

    def build_checklist(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise self._not_implemented()

    def serialize_zoning(self, result: FetchResult[Any]) -> dict[str, Any]:
        return {"status": "unsupported", "source": self.display_name}

    def serialize_general_plan(self, result: FetchResult[Any]) -> dict[str, Any]:
        return {"status": "unsupported", "source": self.display_name}

    def serialize_designation(self, result: FetchResult[Any]) -> dict[str, Any]:
        return {"status": "unsupported", "source": self.display_name}

    def serialize_permits(self, result: FetchResult[Any]) -> dict[str, Any]:
        return {"status": "unsupported", "source": self.display_name}

    def serialize_code_enforcement(self, result: FetchResult[Any]) -> dict[str, Any]:
        return {"status": "unsupported", "source": self.display_name}
