"""FastAPI entry point for the San Jose ADU MVP.

The actual work happens in `app.services.site_pipeline.run_site_pipeline`.
This module owns:
  * app construction + lifespan (one pooled `httpx.AsyncClient` per process),
  * static file mounting,
  * the public HTTP routes.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from pydantic import ValidationError
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform, unary_union

from app import manual_plans
from app.cities import get_adapter, list_supported
from app.manual_plans import ManualPlanInput
from app.models import SiteRequest
from app.services.arcgis import TO_UTM, TO_WGS84
from app.services.site_pipeline import run_site_pipeline

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# `GET /api/site` serves the bundled Alderbrook sample. It is gated behind an
# environment variable so production deployments never accidentally expose
# the demo response under a real-looking URL.
ENABLE_DEMO_SAMPLE = os.environ.get("ADU_ENABLE_DEMO_SAMPLE", "0") == "1"

_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage a single pooled HTTP client for the whole process lifetime."""
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        headers={"User-Agent": "adu-mvp/0.3"},
    ) as client:
        app.state.http_client = client
        yield


app = FastAPI(
    title="San Jose ADU MVP",
    description=(
        "Address-to-parcel ADU studio. Uses live geocoding plus San Jose "
        "parcel and Santa Clara County building outline services; no LiDAR "
        "dependency."
    ),
    version="0.3.0",
    lifespan=lifespan,
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "rate_limit_exceeded", "detail": str(exc.detail)},
    )

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(500, f"Missing required data file: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _centroid_lat_lon(parcel_fc: dict[str, Any]) -> tuple[float, float]:
    features = parcel_fc.get("features") or []
    if not features:
        raise HTTPException(500, "Parcel GeoJSON has no features.")
    parcel_wgs = unary_union([shape(f["geometry"]) for f in features if f.get("geometry")])
    centroid = shapely_transform(TO_WGS84, shapely_transform(TO_UTM, parcel_wgs).centroid)
    return float(centroid.y), float(centroid.x)


@app.get("/")
def root():
    return RedirectResponse("/static/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def get_config():
    """Expose non-secret runtime config to the frontend."""
    return {"google_tiles_key": os.environ.get("GOOGLE_TILES_KEY", "")}


@app.get("/api/site")
def get_site_sample():
    """Serve the bundled sample parcel — only when explicitly enabled.

    Production deployments should leave `ADU_ENABLE_DEMO_SAMPLE` unset so
    this endpoint 404s; demos can opt in via env var.
    """
    if not ENABLE_DEMO_SAMPLE:
        raise HTTPException(
            404,
            "Sample endpoint disabled. Set ADU_ENABLE_DEMO_SAMPLE=1 to enable, "
            "or POST /api/site with a real address.",
        )
    # Build a minimal sample response using `build_site_model` directly so we
    # do not duplicate the live pipeline's response envelope here.
    from app.site_model import build_site_model

    parcel_fc = _read_json(DATA_DIR / "parcel.geojson")
    building_fc = _read_json(DATA_DIR / "building.geojson")
    lat, lon = _centroid_lat_lon(parcel_fc)
    site_model = build_site_model(
        address="Sample outline parcel",
        latitude=lat,
        longitude=lon,
        parcel_fc=parcel_fc,
        building_fc=building_fc,
    )
    return {
        "job_id": "sample",
        "address": site_model["address"],
        "latitude": lat,
        "longitude": lon,
        "parcel_geojson": parcel_fc,
        "building_geojson": building_fc,
        "site_model": site_model,
        "site_model_url": None,
        "zoning": {"district": {}, "general_plan": {}, "designations": {}},
        "checklist": {"items": [], "city": "san_jose"},
        "property_stats": {},
        "zip_context": {},
        "financing": {},
        "stages": [{
            "name": "load_sample_outline_files",
            "status": "ok",
            "duration_ms": 0,
            "detail": "Loaded bundled sample GeoJSON files.",
            "data": None,
            "log_tail": None,
        }],
        "debug": {
            "mode": "sample_file_get",
            "parcel_path": str(DATA_DIR / "parcel.geojson"),
            "building_path": str(DATA_DIR / "building.geojson"),
        },
    }


@app.get("/api/basemap")
async def proxy_basemap(src: str = Query(...)):
    """Proxy an ArcGIS basemap image to the browser, bypassing CORS restrictions."""
    if not src.startswith("https://services.arcgisonline.com/"):
        raise HTTPException(400, "Only ArcGIS basemap sources are allowed.")
    r = await app.state.http_client.get(src, follow_redirects=True)
    return Response(content=r.content, media_type=r.headers.get("content-type", "image/png"))


@app.get("/api/cities")
def get_cities():
    """List the supported cities the frontend dropdown can offer."""
    return {
        "cities": [
            {"name": a.name, "display_name": a.display_name, "docs_url": a.docs_url}
            for a in (get_adapter(c) for c in list_supported())
        ]
    }


@app.post("/api/site")
@limiter.limit("60/minute")
async def post_site(request: Request, body: SiteRequest):
    adapter = get_adapter(body.city)
    return await run_site_pipeline(app.state.http_client, body, adapter)


# ── Manual plans ─────────────────────────────────────────────────────────────

# Accepted upload types and size cap for plan images / floor plans.
_ALLOWED_UPLOAD_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


async def _save_upload(file: UploadFile | None) -> str | None:
    """Persist an uploaded file to the plans static dir; return its public URL.

    Returns ``None`` for an empty field. Rejects disallowed types and
    oversized files so a bad upload fails loudly rather than being stored.
    """
    if file is None or not file.filename:
        return None

    ext = _ALLOWED_UPLOAD_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(
            400, f"Unsupported file type {file.content_type!r}; "
                 "use JPEG, PNG, WebP, GIF, or PDF.",
        )

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File exceeds the 10 MB limit.")

    manual_plans.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (manual_plans.UPLOAD_DIR / name).write_bytes(data)
    return f"{manual_plans.UPLOAD_URL_PREFIX}/{name}"


@app.get("/api/plans")
def get_plans(city: str | None = Query(None)):
    """List user-authored plans, optionally filtered by city."""
    return {"plans": manual_plans.list_plans(city)}


@app.post("/api/plans")
async def create_plan(
    name: str = Form(...),
    city: str = Form(...),
    sqft: int = Form(...),
    adu_type: str = Form("detached"),
    vendor: str | None = Form(None),
    bedrooms: int | None = Form(None),
    bathrooms: int | None = Form(None),
    width_ft: float | None = Form(None),
    depth_ft: float | None = Form(None),
    url: str | None = Form(None),
    image: UploadFile | None = File(None),
    floor_plan: UploadFile | None = File(None),
):
    """Create a plan from a multipart form with optional image + floor-plan uploads."""
    # Treat blank optional strings as omitted so they validate as None.
    vendor = vendor or None
    url = url or None
    try:
        plan_input = ManualPlanInput(
            name=name, city=city, sqft=sqft, adu_type=adu_type, vendor=vendor,
            bedrooms=bedrooms, bathrooms=bathrooms,
            width_ft=width_ft, depth_ft=depth_ft, url=url,
        )
    except ValidationError as exc:
        raise HTTPException(422, exc.errors())

    image_url = await _save_upload(image)
    floor_plan_url = await _save_upload(floor_plan)
    record = manual_plans.add_plan(
        plan_input, image_url=image_url, floor_plan_url=floor_plan_url,
    )
    return record


@app.delete("/api/plans/{plan_id}")
def remove_plan(plan_id: str):
    """Delete a plan and its uploaded files."""
    removed = manual_plans.delete_plan(plan_id)
    if removed is None:
        raise HTTPException(404, f"No plan with id {plan_id!r}")
    return {"deleted": plan_id}
