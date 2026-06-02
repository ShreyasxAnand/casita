"""San Jose `CityAdapter` implementation.

Wraps the San Jose ArcGIS clients and the Bulletin #210 checklist behind the
city-agnostic Protocol. All stage-detail strings and source labels mention
San Jose so the response log reads naturally — sibling adapters do the same
for their own cities.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException

from app.cities.base import CityAdapter, GeocodeResult
from app.cities.san_jose import designations as _designations
from app.cities.san_jose.buildings import fetch_buildings_for_parcel
from app.cities.san_jose.checklist import build_checklist as _build_checklist
from app.cities.san_jose.code_enforcement import (
    CodeEnforcementData,
    fetch_code_enforcement,
)
from app.cities.san_jose.designations import DesignationData
from app.cities.san_jose.geocoder import geocode_san_jose_address
from app.cities.san_jose.parcels import fetch_parcel_at_point, parcel_apn
from app.cities.san_jose.permits import PermitsData, fetch_permits
from app.cities.san_jose.zoning import (
    GeneralPlanData,
    ZoningData,
    fetch_general_plan,
    fetch_zoning,
)
from app.models import stage
from app.result import FetchResult


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


@dataclass(frozen=True)
class SanJoseAdapter:
    name: str = "san_jose"
    display_name: str = "San Jose"
    docs_url: str = (
        "https://www.sanjoseca.gov/your-government/departments-offices/"
        "planning-building-code-enforcement/planning-division/"
        "accessory-dwelling-units-adus"
    )

    # ── address resolution ──────────────────────────────────────────────
    async def geocode(self, client: httpx.AsyncClient, address: str) -> GeocodeResult:
        return await geocode_san_jose_address(client, address)

    # ── parcel + building outlines ──────────────────────────────────────
    async def fetch_parcel(
        self, client: httpx.AsyncClient, latitude: float, longitude: float,
    ) -> tuple[dict[str, Any], str]:
        return await fetch_parcel_at_point(client, latitude, longitude)

    async def fetch_buildings(
        self, client: httpx.AsyncClient, parcel_feature: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        return await fetch_buildings_for_parcel(client, parcel_feature)

    def parcel_id(self, parcel_fc: dict[str, Any]) -> str | None:
        return parcel_apn(parcel_fc)

    # ── zoning + GP ─────────────────────────────────────────────────────
    async def fetch_zoning_and_gp(
        self, client: httpx.AsyncClient, latitude: float, longitude: float,
    ) -> tuple[FetchResult[ZoningData], FetchResult[GeneralPlanData], list[dict[str, Any]]]:
        start = time.perf_counter()
        zoning_result, gp_result = await asyncio.gather(
            fetch_zoning(client, latitude, longitude),
            fetch_general_plan(client, latitude, longitude),
        )
        zoning_code = zoning_result.data.zoning if zoning_result.data else None
        gp_desig = gp_result.data.gp_designation if gp_result.data else None
        any_failed = zoning_result.is_failed or gp_result.is_failed
        if any_failed:
            parts: list[str] = []
            if zoning_result.is_failed:
                parts.append(f"Zoning failed: {zoning_result.error}")
            else:
                parts.append(f"Zoning: {zoning_code or 'unknown'}")
            if gp_result.is_failed:
                parts.append(f"GP failed: {gp_result.error}")
            else:
                parts.append(f"GP: {gp_desig or 'unknown'}")
            detail = ". ".join(parts) + "."
        else:
            detail = (
                f"Loaded zoning district {zoning_code or 'unknown'} and "
                f"General Plan {gp_desig or 'unknown'}."
            )
        return zoning_result, gp_result, [
            stage(
                "fetch_zoning", start, detail,
                {
                    "zoning": zoning_code,
                    "gp": gp_desig,
                    "zoning_status": zoning_result.status.value,
                    "gp_status": gp_result.status.value,
                },
                status="warn" if any_failed else "ok",
            ),
        ]

    # ── designations ────────────────────────────────────────────────────
    async def fetch_designations(
        self,
        client: httpx.AsyncClient,
        latitude: float,
        longitude: float,
        parcel_feature: dict[str, Any],
    ) -> tuple[dict[str, FetchResult[DesignationData]], dict[str, Any]]:
        start = time.perf_counter()
        typed = await _designations.fetch_all(client, latitude, longitude, parcel_feature)
        serialised = {k: self.serialize_designation(v) for k, v in typed.items()}
        return typed, stage(
            "fetch_designations", start,
            "Loaded flood, geohazard, historic, WUI, and heritage-tree designation layers.",
            serialised,
        )

    # ── permits + code enforcement ──────────────────────────────────────
    async def fetch_permits_and_enforcement(
        self,
        client: httpx.AsyncClient,
        apn: str | None,
        latitude: float,
        longitude: float,
    ) -> tuple[FetchResult[PermitsData], FetchResult[CodeEnforcementData], list[dict[str, Any]]]:
        start = time.perf_counter()
        permits_result, ce_result = await asyncio.gather(
            fetch_permits(client, apn or ""),
            fetch_code_enforcement(client, apn or "", latitude, longitude),
        )
        permit_summary = (
            f"{permits_result.data.active_count} active, "
            f"{permits_result.data.finalized_count} finalized."
            if permits_result.is_ok and permits_result.data
            else permits_result.error or permits_result.status.value
        )
        ce_summary = (
            f"{ce_result.data.total_count} issue(s) "
            f"({ce_result.data.complaint_count} complaint(s), "
            f"{ce_result.data.investigation_count} investigation(s))."
            if ce_result.is_ok and ce_result.data
            else "none" if ce_result.is_absent
            else ce_result.error or ce_result.status.value
        )
        any_failed = permits_result.is_failed or ce_result.is_failed
        return permits_result, ce_result, [
            stage(
                "fetch_permits_enforcement", start,
                f"Permits: {permit_summary} Code enforcement: {ce_summary}",
                {
                    "permits_status": permits_result.status.value,
                    "ce_status": ce_result.status.value,
                    "permit_active": permits_result.data.active_count if permits_result.data else None,
                    "permit_finalized": permits_result.data.finalized_count if permits_result.data else None,
                    "ce_total": ce_result.data.total_count if ce_result.data else None,
                    "ce_complaints": ce_result.data.complaint_count if ce_result.data else None,
                    "ce_investigations": ce_result.data.investigation_count if ce_result.data else None,
                },
                status="warn" if any_failed else "ok",
            ),
        ]

    # ── checklist ───────────────────────────────────────────────────────
    def build_checklist(
        self,
        site_model: dict[str, Any],
        *,
        zoning: FetchResult[ZoningData] | None,
        general_plan: FetchResult[GeneralPlanData] | None,
        designations: dict[str, FetchResult[DesignationData]] | None,
        property_stats: dict[str, Any] | None,
        adu_type: str,
        permits: FetchResult[PermitsData] | None,
        code_enforcement: FetchResult[CodeEnforcementData] | None,
        standards: str = "city",
        adu_stories: int = 1,
    ) -> list[dict[str, Any]]:
        return _build_checklist(
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

    # ── serializers ─────────────────────────────────────────────────────
    def serialize_zoning(self, result: FetchResult[ZoningData]) -> dict[str, Any]:
        d: dict[str, Any] = {"status": result.status.value, "source": result.source}
        if result.data is not None:
            d.update({
                "zoning": result.data.zoning,
                "zoning_abbrev": result.data.zoning_abbrev,
                "zoning_full_name": result.data.zoning_full_name,
                "facility_id": result.data.facility_id,
                "rezoning_file": result.data.rezoning_file,
                "pd_use": result.data.pd_use,
                "pd_density": result.data.pd_density,
                "developed_as_pd": result.data.developed_as_pd,
                "approval_date": result.data.approval_date,
                "notes": result.data.notes,
            })
        if result.error is not None:
            d["error"] = result.error
        return d

    def serialize_general_plan(self, result: FetchResult[GeneralPlanData]) -> dict[str, Any]:
        d: dict[str, Any] = {"status": result.status.value, "source": result.source}
        if result.data is not None:
            d.update({
                "gp_designation": result.data.gp_designation,
                "gp_abbreviation": result.data.gp_abbreviation,
                "notes": result.data.notes,
                "last_update": result.data.last_update,
            })
        if result.error is not None:
            d["error"] = result.error
        return d

    def serialize_designation(self, result: FetchResult[DesignationData]) -> dict[str, Any]:
        d: dict[str, Any] = {"status": result.status.value, "source": result.source}
        if result.data is not None:
            d["present"] = result.data.present
            d["detail"] = result.data.detail
        if result.error is not None:
            d["error"] = result.error
        return d

    def serialize_permits(self, result: FetchResult[PermitsData]) -> dict[str, Any]:
        d: dict[str, Any] = {"status": result.status.value, "source": result.source}
        if result.error:
            d["error"] = result.error
        if result.data:
            d["active_count"] = result.data.active_count
            d["finalized_count"] = result.data.finalized_count
            d["total_count"] = len(result.data.records)
            d["has_pool_permit"] = result.data.has_pool_permit
            d["pool_permits"] = [
                {
                    "folder_num": p.folder_num,
                    "work_desc": p.work_desc,
                    "sub_desc": p.sub_desc,
                    "status": p.status,
                    "issue_date": p.issue_date,
                    "final_date": p.final_date,
                }
                for p in result.data.pool_permits
            ]
        return d

    def serialize_code_enforcement(
        self, result: FetchResult[CodeEnforcementData]
    ) -> dict[str, Any]:
        d: dict[str, Any] = {"status": result.status.value, "source": result.source}
        if result.error:
            d["error"] = result.error
        if result.data:
            d["complaint_count"] = result.data.complaint_count
            d["investigation_count"] = result.data.investigation_count
            d["total_count"] = result.data.total_count
            d["issues"] = [
                {
                    "issue_type": i.issue_type,
                    "identifier": i.identifier,
                    "description": i.description,
                    "open_date": i.open_date,
                    "status": i.status,
                    "program": i.program,
                }
                for i in result.data.issues
            ]
        return d


SAN_JOSE_ADAPTER = SanJoseAdapter()
