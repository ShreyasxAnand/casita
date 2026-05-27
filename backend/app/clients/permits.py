"""San Jose building permits lookup via PLN_PermitsAndComplaints MapServer.

Queries layer 8 (Active Building Permit) and layer 9 (Expired Building Permit)
by APN to surface permit history for two checklist questions:
  - Q2: Is the main home permitted? — finalized permits are strong evidence.
  - Q9: Demolished pool? — any permit mentioning "pool", "swimming", or "spa".
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
_ACTIVE_URL = f"{_BASE}/8/query"
_EXPIRED_URL = f"{_BASE}/9/query"

_OUT_FIELDS = "FOLDERNUM,WORKDESC,SUBDESC,PERMITAPPROVAL,ISSUEDATE,FINALDATE,ADDRESS,APN"
_POOL_KEYWORDS = frozenset({"pool", "swimming", "spa", "jacuzzi"})
_SRC = "San Jose PLN_PermitsAndComplaints MapServer layers 8+9"


@dataclass
class PermitRecord:
    folder_num: str
    work_desc: str
    sub_desc: str
    status: str         # "active" | "expired"
    issue_date: str | None
    final_date: str | None


@dataclass
class PermitsData:
    active_count: int
    finalized_count: int
    records: list[PermitRecord]
    has_pool_permit: bool
    pool_permits: list[PermitRecord]


def _ms_to_date(ms: Any) -> str | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return None


def _parse_record(attrs: dict[str, Any], status: str) -> PermitRecord:
    return PermitRecord(
        folder_num=str(attrs.get("FOLDERNUM") or ""),
        work_desc=str(attrs.get("WORKDESC") or ""),
        sub_desc=str(attrs.get("SUBDESC") or ""),
        status=status,
        issue_date=_ms_to_date(attrs.get("ISSUEDATE")),
        final_date=_ms_to_date(attrs.get("FINALDATE")),
    )


def _is_pool(r: PermitRecord) -> bool:
    text = f"{r.work_desc} {r.sub_desc}".lower()
    return any(kw in text for kw in _POOL_KEYWORDS)


async def _query_layer(
    client: httpx.AsyncClient,
    url: str,
    apn: str,
    status: str,
    *,
    stage: str,
) -> list[PermitRecord]:
    params = {
        "where": f"APN = '{apn}'",
        "outFields": _OUT_FIELDS,
        "returnGeometry": "false",
        "f": "json",
    }
    data = await arcgis.fetch_json(client, url, params, stage=stage)
    return [
        _parse_record(f.get("attributes") or {}, status)
        for f in data.get("features") or []
    ]


async def fetch_permits(
    client: httpx.AsyncClient,
    apn: str,
) -> FetchResult[PermitsData]:
    if not apn:
        return FetchResult.failed("No APN available", _SRC)
    try:
        active, expired = await asyncio.gather(
            _query_layer(client, _ACTIVE_URL, apn, "active", stage="active permits"),
            _query_layer(client, _EXPIRED_URL, apn, "expired", stage="expired permits"),
        )
    except HTTPException as exc:
        return FetchResult.failed(exc.detail, _SRC)

    all_records = active + expired
    if not all_records:
        return FetchResult.absent(_SRC)

    pool_permits = [r for r in all_records if _is_pool(r)]
    finalized = [r for r in expired if r.final_date]

    return FetchResult.ok(
        PermitsData(
            active_count=len(active),
            finalized_count=len(finalized),
            records=all_records,
            has_pool_permit=bool(pool_permits),
            pool_permits=pool_permits,
        ),
        _SRC,
    )
