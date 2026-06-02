"""Registry of supported city adapters.

Lookup is lazy so importing `app.cities` does not pull every city's clients
into memory. A request comes in with `city: str`; we resolve here.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.cities.base import CityAdapter, GeocodeResult

__all__ = ["CityAdapter", "GeocodeResult", "get_adapter", "list_supported"]


_SUPPORTED = ("san_jose", "sf", "oakland")


def list_supported() -> tuple[str, ...]:
    return _SUPPORTED


def get_adapter(name: str) -> CityAdapter:
    key = (name or "").strip().lower()
    if key in ("", "san_jose", "san-jose", "sanjose"):
        from app.cities.san_jose.adapter import SAN_JOSE_ADAPTER
        return SAN_JOSE_ADAPTER
    if key in ("sf", "san_francisco", "san-francisco"):
        from app.cities.sf.adapter import SF_ADAPTER
        return SF_ADAPTER
    if key == "oakland":
        from app.cities.oakland.adapter import OAKLAND_ADAPTER
        return OAKLAND_ADAPTER
    raise HTTPException(
        422,
        f"Unsupported city '{name}'. Supported: {', '.join(_SUPPORTED)}.",
    )
