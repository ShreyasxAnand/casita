"""Module-level pyproj transformers.

`Transformer.from_crs` is expensive (loads PROJ tables). Building it on every
request was a measurable hot-spot; here we build each one once and expose the
ready-to-call `.transform` function.
"""
from __future__ import annotations

from pyproj import Transformer

from app.config import FOOTPRINT_EPSG, WEB_MERCATOR_EPSG, WGS84_EPSG

WGS84_TO_UTM = Transformer.from_crs(
    f"EPSG:{WGS84_EPSG}", f"EPSG:{FOOTPRINT_EPSG}", always_xy=True
).transform
UTM_TO_WGS84 = Transformer.from_crs(
    f"EPSG:{FOOTPRINT_EPSG}", f"EPSG:{WGS84_EPSG}", always_xy=True
).transform
UTM_TO_3857 = Transformer.from_crs(
    f"EPSG:{FOOTPRINT_EPSG}", f"EPSG:{WEB_MERCATOR_EPSG}", always_xy=True
).transform
WEB_MERCATOR_TO_UTM = Transformer.from_crs(
    f"EPSG:{WEB_MERCATOR_EPSG}", f"EPSG:{FOOTPRINT_EPSG}", always_xy=True
).transform
