"""Static configuration: URLs, CRS, and tunable constants.

Centralising these makes it easy to swap providers or tune timeouts without
hunting through routing/business-rule code.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# ── Coordinate reference systems ─────────────────────────────────────────────
FOOTPRINT_EPSG = 26910  # UTM zone 10N — accurate metres around San Jose
WGS84_EPSG = 4326
WEB_MERCATOR_EPSG = 3857

# ── ArcGIS service endpoints ─────────────────────────────────────────────────
ARCGIS_GEOCODER_URL = (
    "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/"
    "findAddressCandidates"
)
SAN_JOSE_OPN_BASE = (
    "https://geo.sanjoseca.gov/server/rest/services/OPN/OPN_OpenDataService/MapServer"
)
SAN_JOSE_PARCELS_QUERY_URL = f"{SAN_JOSE_OPN_BASE}/270/query"
SAN_JOSE_ZONING_QUERY_URL = f"{SAN_JOSE_OPN_BASE}/401/query"
SAN_JOSE_GENERAL_PLAN_QUERY_URL = f"{SAN_JOSE_OPN_BASE}/404/query"
SAN_JOSE_FLOOD_QUERY_URL = f"{SAN_JOSE_OPN_BASE}/439/query"
SAN_JOSE_HISTORIC_POINTS_QUERY_URL = f"{SAN_JOSE_OPN_BASE}/406/query"
SAN_JOSE_HISTORIC_AREA_QUERY_URL = f"{SAN_JOSE_OPN_BASE}/408/query"
SAN_JOSE_WUI_QUERY_URL = f"{SAN_JOSE_OPN_BASE}/283/query"
SAN_JOSE_HERITAGE_TREES_QUERY_URL = f"{SAN_JOSE_OPN_BASE}/511/query"
SAN_JOSE_BUILDINGS_QUERY_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/DPW/"
    "DPW_BasemapServiceWGS/MapServer/21/query"
)
SCC_BUILDINGS_QUERY_URL = (
    "https://mapservices.sccgov.org/arcgis/rest/services/basic/"
    "SCCBuildings/MapServer/0/query"
)
SAN_JOSE_GEOHAZARD_QUERY_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/PLN/"
    "PLN_LandDesignations/MapServer/31/query"
)
FEMA_NFHL_QUERY_URL = (
    "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query"
)
USDA_WUI_QUERY_URL = (
    "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_WUI_2020_01/MapServer/0/query"
)
ARCGIS_WORLD_IMAGERY_EXPORT = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/export"
)
ARCGIS_WORLD_STREET_EXPORT = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/"
    "World_Street_Map/MapServer/export"
)

# ── Domain constants ─────────────────────────────────────────────────────────
SFHA_ZONES = frozenset({"A", "AE", "AH", "AO", "A99"})

# Conservative bbox used to reject geocoder hits clearly outside San Jose.
SAN_JOSE_BBOX = {"west": -122.08, "south": 37.10, "east": -121.55, "north": 37.50}

# ArcGIS envelope padding (degrees) when searching parcels near a geocoded point.
# Roughly ±50m at this latitude. Documented so future tuning is intentional.
PARCEL_SEARCH_PAD_LON = 0.00045
PARCEL_SEARCH_PAD_LAT = 0.00035
# Heritage-tree records often have imprecise coordinates near parcel edges.
HERITAGE_TREE_PAD_DEG = 0.00018

# HTTP
HTTP_CONNECT_TIMEOUT_S = 8.0
HTTP_READ_TIMEOUT_S = 20.0
USER_AGENT = "adu-mvp/0.3"

# Feature flags
EXPOSE_SAMPLE_ENDPOINT = False  # GET /api/site serves bundled sample — dev only.
