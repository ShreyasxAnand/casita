"""Map a HomeHarvest `style` value to a coarse property-type bucket.

HomeHarvest is the listing-data dependency we use to enrich the property,
and the `style` field is provider-defined — not city-specific. Living here
so SJ, SF, Oakland, and any future city use the same bucketing.
"""

from __future__ import annotations


def property_type_from_style(style: str | None) -> str:
    if not style:
        return "Unknown"
    s = str(style).upper().replace("_", " ")
    if "DUPLEX" in s or "TWO FAMILY" in s or "2 FAMILY" in s:
        return "Duplex"
    if "MULTI" in s or "APARTMENT" in s or "TRIPLEX" in s or "FOURPLEX" in s:
        return "Multi-Family"
    if "TOWNHOUSE" in s or "TOWN HOUSE" in s or "ROW" in s:
        return "Townhouse"
    if "CONDO" in s:
        return "Condo"
    if "SINGLE" in s or "SFR" in s or "1 FAMILY" in s or "ONE FAMILY" in s or "DETACHED" in s:
        return "Single-Family"
    if "FAMILY" in s and "TWO" not in s and "MULTI" not in s:
        return "Single-Family"
    if s in ("RESIDENTIAL", "RES"):
        return "Single-Family"
    return "Unknown"
