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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform, unary_union

from app.models import SiteRequest
from app.services.arcgis import TO_UTM, TO_WGS84
from app.services.site_pipeline import run_site_pipeline

logger = logging.getLogger(__name__)

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
        "checklist": {"san_jose_checklist": []},
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


@app.post("/api/site")
async def post_site(body: SiteRequest):
    return await run_site_pipeline(app.state.http_client, body)
