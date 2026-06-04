"""San Jose building permits lookup via PLN_PermitsAndComplaints MapServer.

Queries layer 8 (Active Building Permit) and layer 9 (Expired Building Permit)
by APN to surface permit history for two checklist questions:
  - Q2: Is the main home permitted? — finalized permits are strong evidence.
  - Q9: Demolished pool? — any permit mentioning "pool", "swimming", or "spa".

The contractor heatmap also uses this module for live ADU/JADU permit lookups
on a selected APN.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException

from app.result import FetchResult
from app.services import arcgis

_BASE = (
    "https://geo.sanjoseca.gov/server/rest/services/"
    "PLN/PLN_PermitsAndComplaints/MapServer"
)
_ACTIVE_URL = f"{_BASE}/8/query"
_EXPIRED_URL = f"{_BASE}/9/query"

_OUT_FIELDS = "FOLDERNUM,WORKDESC,SUBDESC,PERMITAPPROVAL,ISSUEDATE,FINALDATE,ADDRESS,APN"
_ADU_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\ba\s*\.?\s*d\s*\.?\s*u\.?s?\b",
        r"\bj\s*\.?\s*a\s*\.?\s*d\s*\.?\s*u\.?s?\b",
        r"\baccessory\s+dwelling\b",
        r"\baccessory\s+living\b",
        r"\bjunior\s+accessory\s+dwelling\b",
        r"\bsecond\s+unit\b",
        r"\b2nd\s+unit\b",
        r"\bgranny\s+unit\b",
        r"\bin-?law\s+unit\b",
    )
)
_POOL_KEYWORDS = frozenset({"pool", "swimming", "spa", "jacuzzi"})
_SRC = "San Jose PLN_PermitsAndComplaints MapServer layers 8+9"


def normalize_apn(value: Any) -> str:
    """Return the alphanumeric APN form used by San Jose permit layers."""
    return "".join(ch for ch in str(value or "") if ch.isalnum()).upper()


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
    except (ValueError, TypeError, OSError, OverflowError):
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


def is_adu_permit_text(work_desc: Any, sub_desc: Any = "") -> bool:
    """Return True when permit description fields indicate an ADU/JADU permit."""
    text = f"{work_desc or ''} {sub_desc or ''}"
    return any(pattern.search(text) for pattern in _ADU_PATTERNS)


def is_adu_permit_record(record: PermitRecord) -> bool:
    return is_adu_permit_text(record.work_desc, record.sub_desc)


async def _query_layer(
    client: httpx.AsyncClient,
    url: str,
    apn: str,
    status: str,
    *,
    stage: str,
) -> list[PermitRecord]:
    clean_apn = normalize_apn(apn)
    if not clean_apn:
        return []
    params = {
        "where": f"APN = '{clean_apn}'",
        "outFields": _OUT_FIELDS,
        "returnGeometry": "false",
        "resultRecordCount": "2000",
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
    clean_apn = normalize_apn(apn)
    if not clean_apn:
        return FetchResult.failed("No APN available", _SRC)
    try:
        active, expired = await asyncio.gather(
            _query_layer(
                client, _ACTIVE_URL, clean_apn, "active", stage="active permits",
            ),
            _query_layer(
                client, _EXPIRED_URL, clean_apn, "expired", stage="expired permits",
            ),
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


async def fetch_adu_permits(
    client: httpx.AsyncClient,
    apn: str,
) -> FetchResult[list[PermitRecord]]:
    """Fetch live permit records for one APN and return only ADU/JADU matches."""
    clean_apn = normalize_apn(apn)
    if not clean_apn:
        return FetchResult.failed("No APN available", _SRC)
    try:
        active, expired = await asyncio.gather(
            _query_layer(
                client, _ACTIVE_URL, clean_apn, "active", stage="active ADU permits",
            ),
            _query_layer(
                client, _EXPIRED_URL, clean_apn, "expired", stage="expired ADU permits",
            ),
        )
    except HTTPException as exc:
        return FetchResult.failed(exc.detail, _SRC)

    adu_records = [record for record in active + expired if is_adu_permit_record(record)]
    if not adu_records:
        return FetchResult.absent(_SRC)
    return FetchResult.ok(adu_records, _SRC)
