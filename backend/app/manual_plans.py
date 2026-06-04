"""User-authored ADU plan storage.

A small, file-backed store for plans entered by hand through the "Add Plans"
UI — the deliberate replacement for the abandoned scraped catalog. There is no
database in this project, so records persist as JSON in ``data/manual_plans.json``
and uploaded images live under ``static/plans/``.

Design notes:
* Writes are atomic (temp file + ``os.replace``) so a crash mid-write can never
  corrupt the store or expose a half-written file to a concurrent reader.
* Honesty contract (see ``app.result``): optional fields the user leaves blank
  are stored as ``None`` — never coerced to ``0`` or a placeholder.
* This module owns *persistence only*; HTTP concerns (uploads, validation
  responses) live in ``app.main``.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

# Repo-root-relative data dir, matching app.config / development_standards.
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
STORE_PATH = _DATA_DIR / "manual_plans.json"

# Uploaded plan images are served as ordinary static assets.
UPLOAD_DIR = Path(__file__).resolve().parent / "static" / "plans"
UPLOAD_URL_PREFIX = "/static/plans"

City = Literal["san_jose", "sf", "oakland"]
AduType = Literal["detached", "attached", "jadu"]

# Serialize read-modify-write cycles within a process. The store is tiny and
# writes are infrequent (manual data entry), so a coarse lock is plenty.
_LOCK = threading.Lock()


class ManualPlanInput(BaseModel):
    """Fields supplied by the user when adding a plan.

    Only ``name``, ``city``, and ``sqft`` are required — everything else is
    optional and stays ``None`` when omitted.
    """

    name: str = Field(min_length=1, max_length=120)
    city: City
    sqft: int = Field(gt=0, le=5000)
    adu_type: AduType = "detached"
    vendor: str | None = Field(default=None, max_length=120)
    bedrooms: int | None = Field(default=None, ge=0, le=10)
    bathrooms: int | None = Field(default=None, ge=0, le=10)
    width_ft: float | None = Field(default=None, gt=0, le=200)
    depth_ft: float | None = Field(default=None, gt=0, le=200)
    url: str | None = Field(default=None, max_length=500)


class ManualPlan(ManualPlanInput):
    """A stored plan: user input plus server-assigned fields."""

    id: str
    image_url: str | None = None
    floor_plan_url: str | None = None
    created_at: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_store() -> list[dict[str, Any]]:
    if not STORE_PATH.exists():
        return []
    try:
        with STORE_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []
    plans = data.get("plans") if isinstance(data, dict) else None
    return plans if isinstance(plans, list) else []


def _write_store(plans: list[dict[str, Any]]) -> None:
    """Atomically persist the full plan list."""
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"plans": plans}
    fd, tmp = tempfile.mkstemp(dir=STORE_PATH.parent, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, STORE_PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def list_plans(city: str | None = None) -> list[dict[str, Any]]:
    """Return stored plans, newest first, optionally filtered by city."""
    plans = _read_store()
    if city:
        plans = [p for p in plans if p.get("city") == city]
    return sorted(plans, key=lambda p: p.get("created_at", ""), reverse=True)


def add_plan(
    plan_input: ManualPlanInput,
    *,
    image_url: str | None = None,
    floor_plan_url: str | None = None,
) -> dict[str, Any]:
    """Create and persist a new plan, returning the stored record."""
    record = ManualPlan(
        id=uuid.uuid4().hex[:12],
        image_url=image_url,
        floor_plan_url=floor_plan_url,
        created_at=_utc_now_iso(),
        **plan_input.model_dump(),
    )
    stored = record.model_dump()
    with _LOCK:
        plans = _read_store()
        plans.append(stored)
        _write_store(plans)
    return stored


def delete_plan(plan_id: str) -> dict[str, Any] | None:
    """Remove a plan by id, deleting its uploaded images. Returns the removed
    record, or ``None`` if no plan had that id."""
    with _LOCK:
        plans = _read_store()
        removed = next((p for p in plans if p.get("id") == plan_id), None)
        if removed is None:
            return None
        _write_store([p for p in plans if p.get("id") != plan_id])

    # Best-effort cleanup of owned upload files (outside the lock).
    for url in (removed.get("image_url"), removed.get("floor_plan_url")):
        _delete_upload(url)
    return removed


def _delete_upload(url: str | None) -> None:
    """Delete an uploaded file we own, identified by its public URL.

    Guards against path traversal: only files directly inside UPLOAD_DIR whose
    URL carries our prefix are eligible.
    """
    if not url or not url.startswith(UPLOAD_URL_PREFIX + "/"):
        return
    name = Path(url).name
    target = (UPLOAD_DIR / name).resolve()
    if target.parent == UPLOAD_DIR.resolve() and target.is_file():
        target.unlink(missing_ok=True)
