"""San Jose code enforcement lookup via PLN_PermitsAndComplaints MapServer.

Two independent checks are combined into one result:
  - Layer 1 (Code Complaints Open) by APN — formal open complaints filed by residents/inspectors.
  - Layer 8 (Active Building Permit) spatial query for WORKDESC='Code Investigation' — active
    code-investigation work orders that predate or run alongside formal complaints.

Both are blockers per Bulletin #210: plans will not be accepted until resolved.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException

from app.result import FetchResult
from app.services import arcgis

logger = logging.getLogger(__name__)

_BASE = (
    "https://geo.sanjoseca.gov/server/rest/services/"
    "PLN/PLN_PermitsAndComplaints/MapServer"
)
_COMPLAINTS_URL    = f"{_BASE}/1/query"
_ACTIVE_PERMIT_URL = f"{_BASE}/8/query"

_COMPLAINT_FIELDS    = "CASENUMBER,DESCRIPTION,OPENDATE,CASESTATUS,PROGRAM,DISPOSITION,VIOLATIONTYPE"
_INVESTIGATION_FIELDS = "FOLDERNUM,WORKDESC,SUBDESC,ADDRESS,ISSUEDATE,APN"

_SRC = (
    "San Jose PLN_PermitsAndComplaints MapServer "
    "layer 1 (Code Complaints Open) + layer 8 (Code Investigations)"
)


@dataclass
class CodeIssue:
    """One complaint or active code-investigation work order."""
    issue_type: str       # "complaint" | "investigation"
    identifier: str       # case number or folder number
    description: str
    open_date: str | None
    status: str
    program: str


@dataclass
class CodeEnforcementData:
    complaint_count: int
    investigation_count: int
    issues: list[CodeIssue]

    @property
    def total_count(self) -> int:
        return self.complaint_count + self.investigation_count

    @property
    def has_issues(self) -> bool:
        return self.total_count > 0


def _ms_to_date(ms: Any) -> str | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return None


def _parse_complaint(attrs: dict[str, Any]) -> CodeIssue:
    return CodeIssue(
        issue_type="complaint",
        identifier=str(attrs.get("CASENUMBER") or ""),
        description=str(attrs.get("DESCRIPTION") or attrs.get("VIOLATIONTYPE") or ""),
        open_date=_ms_to_date(attrs.get("OPENDATE")),
        status=str(attrs.get("CASESTATUS") or ""),
        program=str(attrs.get("PROGRAM") or "Code Enforcement"),
    )


def _parse_investigation(attrs: dict[str, Any]) -> CodeIssue:
    return CodeIssue(
        issue_type="investigation",
        identifier=str(attrs.get("FOLDERNUM") or ""),
        description=str(attrs.get("SUBDESC") or attrs.get("WORKDESC") or "Code Investigation"),
        open_date=_ms_to_date(attrs.get("ISSUEDATE")),
        status="Active",
        program="Code Investigation",
    )


async def _fetch_complaints_by_apn(
    client: httpx.AsyncClient, apn: str
) -> list[CodeIssue]:
    if not apn:
        return []
    params = {
        "where": f"APN = '{apn}'",
        "outFields": _COMPLAINT_FIELDS,
        "returnGeometry": "false",
        "f": "json",
    }
    data = await arcgis.fetch_json(client, _COMPLAINTS_URL, params, stage="code complaints by APN")
    return [_parse_complaint(f.get("attributes") or {}) for f in data.get("features") or []]


async def _fetch_investigations_spatial(
    client: httpx.AsyncClient, lat: float, lon: float
) -> list[CodeIssue]:
    """Spatial point query on layer 8 for active 'Code Investigation' work orders."""
    params = {
        "geometry": arcgis.point(lon, lat),
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "where": "WORKDESC = 'Code Investigation'",
        "outFields": _INVESTIGATION_FIELDS,
        "returnGeometry": "false",
        "f": "json",
    }
    data = await arcgis.fetch_json(
        client, _ACTIVE_PERMIT_URL, params, stage="code investigations spatial"
    )
    return [_parse_investigation(f.get("attributes") or {}) for f in data.get("features") or []]


async def fetch_code_enforcement(
    client: httpx.AsyncClient,
    apn: str,
    lat: float,
    lon: float,
) -> FetchResult[CodeEnforcementData]:
    try:
        complaints, investigations = await asyncio.gather(
            _fetch_complaints_by_apn(client, apn),
            _fetch_investigations_spatial(client, lat, lon),
        )
    except HTTPException as exc:
        return FetchResult.failed(exc.detail, _SRC)

    all_issues = complaints + investigations
    if not all_issues:
        return FetchResult.absent(_SRC)

    return FetchResult.ok(
        CodeEnforcementData(
            complaint_count=len(complaints),
            investigation_count=len(investigations),
            issues=all_issues,
        ),
        _SRC,
    )
