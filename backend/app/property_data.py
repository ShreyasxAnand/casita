"""HomeHarvest property data + zip context + financing math for the ADU MVP.

Lightweight standalone version (no Redis, no compliance models). Mirrors the
shape of the root project's HomeHarvest client but trims it to what the MVP
UI needs: subject property stats, neighbourhood rent comps, and a financing
estimate for a proposed ADU.
"""
from __future__ import annotations

import logging
from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta
from functools import wraps
from threading import RLock
from time import monotonic
from typing import Any

logger = logging.getLogger(__name__)

# ── In-memory TTL cache ──────────────────────────────────────────────────────
_cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
_cache_ttl_seconds = 30 * 60
_cache_max_entries = 128
_cache_lock = RLock()


def _cache_key(func_name: str, *args, **kwargs) -> str:
    return f"{func_name}:{args!r}:{sorted(kwargs.items())!r}"


def cached(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        key = _cache_key(func.__name__, *args, **kwargs)
        now = monotonic()
        with _cache_lock:
            item = _cache.get(key)
            if item:
                result, expires_at = item
                if expires_at > now:
                    _cache.move_to_end(key)
                    return result
                del _cache[key]
        result = func(*args, **kwargs)
        with _cache_lock:
            _cache[key] = (result, now + _cache_ttl_seconds)
            _cache.move_to_end(key)
            while len(_cache) > _cache_max_entries:
                _cache.popitem(last=False)
        return result

    return wrapper


_STREET_ABBREV = [
    (" Lane", " Ln"),
    (" Street", " St"),
    (" Drive", " Dr"),
    (" Avenue", " Ave"),
    (" Boulevard", " Blvd"),
    (" Road", " Rd"),
    (" Court", " Ct"),
    (" Circle", " Cir"),
    (" Place", " Pl"),
]


def _address_search_variants(address: str) -> list[str]:
    if not address or not str(address).strip():
        return []
    a = " ".join(str(address).strip().split())
    variants = [a]
    abbr = a
    for long_form, short in _STREET_ABBREV:
        if long_form in abbr:
            abbr = abbr.replace(long_form, short)
    if abbr != a:
        variants.append(abbr)
    no_comma = " ".join(a.replace(",", " ").split())
    if no_comma != a and no_comma not in variants:
        variants.append(no_comma)
    return variants


# ── HomeHarvest wrappers ─────────────────────────────────────────────────────
@cached
def get_property_by_address(address: str) -> dict[str, Any] | None:
    """Fetch a single subject property from Realtor.com via HomeHarvest."""
    try:
        from homeharvest import scrape_property  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("homeharvest not installed. Run: pip install homeharvest") from exc

    for location in _address_search_variants(address):
        try:
            df = scrape_property(
                location=location,
                listing_type=None,
                return_type="pandas",
                limit=1,
            )
            if df is not None and not df.empty:
                return df.iloc[0].to_dict()
        except Exception as exc:
            logger.debug("HomeHarvest try %s failed: %s", location, exc)
            continue
    logger.info("HomeHarvest: no match for %s", address)
    return None


@cached
def search_properties_by_zip(zip_code: str, limit: int = 50) -> list[dict[str, Any]]:
    """Pull recent listings in a zip (sale + rent mixed) for zip-level stats."""
    if not zip_code:
        return []
    try:
        from homeharvest import scrape_property  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("homeharvest not installed. Run: pip install homeharvest") from exc
    try:
        df = scrape_property(location=zip_code, listing_type=None, limit=limit)
        if df is None or df.empty:
            return []
        return df.to_dict(orient="records")
    except Exception as exc:
        logger.error("HomeHarvest zip search failed for %s: %s", zip_code, exc)
        raise


# ── Mapping helpers ──────────────────────────────────────────────────────────
def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        f = float(value)
        if f != f:  # NaN guard
            return None
        return f
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    f = _coerce_float(value)
    return int(f) if f is not None else None


def _parse_date(raw: Any) -> str | None:
    if not raw:
        return None
    try:
        if hasattr(raw, "strftime"):
            return raw.strftime("%Y-%m-%d")
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def build_property_stats(
    prop_data: dict[str, Any] | None,
    *,
    address: str,
    city: str,
    state: str,
    zip_code: str,
    latitude: float,
    longitude: float,
    neighborhood_avg_year_built: int | None = None,
) -> dict[str, Any]:
    """Normalize a HomeHarvest property dict (or None) into a UI-friendly stats dict."""
    if not prop_data:
        return {
            "address": address,
            "city": city,
            "state": state,
            "zip_code": zip_code,
            "latitude": latitude,
            "longitude": longitude,
            "found": False,
            "note": "No Realtor.com listing found for this address. Manually verify details.",
        }

    year_built = _coerce_int(prop_data.get("year_built"))
    age = (date.today().year - year_built) if year_built else None
    sqft = _coerce_float(prop_data.get("sqft"))
    lot_sqft = _coerce_float(prop_data.get("lot_sqft"))
    list_price = _coerce_float(prop_data.get("list_price"))
    sold_price = _coerce_float(prop_data.get("sold_price") or prop_data.get("last_sold_price"))
    last_sold_date = _parse_date(prop_data.get("last_sold_date"))
    sold_recently = False
    if last_sold_date:
        try:
            d = datetime.strptime(last_sold_date, "%Y-%m-%d")
            sold_recently = d >= datetime.now() - timedelta(days=365 * 10)
        except ValueError:
            pass

    status_raw = str(prop_data.get("status") or "").upper().replace("_", " ")
    is_rental = "RENT" in status_raw
    style = str(prop_data.get("style") or "").upper().replace("_", " ") or None
    neighborhoods = prop_data.get("neighborhoods")
    neighborhood_name = (
        neighborhoods[0]
        if isinstance(neighborhoods, list) and neighborhoods
        else city
    )

    significantly_newer = False
    if year_built and neighborhood_avg_year_built:
        significantly_newer = (year_built - neighborhood_avg_year_built) >= 30

    return {
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "latitude": latitude,
        "longitude": longitude,
        "found": True,
        "beds": _coerce_int(prop_data.get("beds")),
        "full_baths": _coerce_int(prop_data.get("full_baths")),
        "half_baths": _coerce_int(prop_data.get("half_baths")),
        "sqft": sqft,
        "lot_size_sqft": lot_sqft,
        "year_built": year_built,
        "property_age_years": age,
        "stories": _coerce_int(prop_data.get("stories")),
        "garage": _coerce_int(prop_data.get("garage")),
        "style": style,
        "status": status_raw or None,
        "list_price": list_price,
        "sold_price": sold_price,
        "last_sold_date": last_sold_date,
        "sold_recently": sold_recently,
        "is_rental": is_rental,
        "price_per_sqft": _coerce_float(prop_data.get("price_per_sqft")),
        "neighborhood_name": neighborhood_name,
        "neighborhood_avg_year_built": neighborhood_avg_year_built,
        "significantly_newer_than_neighborhood": significantly_newer,
        "estimated_value": _coerce_float(prop_data.get("estimated_value")),
        "note": "Real listing data from HomeHarvest (Realtor.com).",
    }


def find_subject_in_zip(address: str, properties: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Fallback: locate the subject property inside a zip batch when the
    direct address lookup misses (typical when Realtor.com only indexes the
    abbreviated street form)."""
    if not properties or not address:
        return None

    def _norm(s: str) -> str:
        return " ".join(str(s).lower().replace(",", " ").replace(".", " ").split())

    variants = {_norm(address)}
    for long_form, short in _STREET_ABBREV:
        variants.add(_norm(address.replace(long_form, short)))
    for p in properties:
        candidate = _norm(p.get("full_street_line") or p.get("street") or "")
        if not candidate:
            continue
        for v in variants:
            if v.startswith(candidate):
                return p
    return None


def _is_rental(p: dict[str, Any]) -> bool:
    return str(p.get("status") or "").lower() in ("for_rent", "rental")


def avg_year_built(properties: list[dict[str, Any]]) -> int | None:
    years = [_coerce_int(p.get("year_built")) for p in properties]
    years = [y for y in years if y]
    return round(sum(years) / len(years)) if years else None


def build_zip_context(
    zip_code: str,
    city: str,
    state: str,
    properties: list[dict[str, Any]],
) -> dict[str, Any]:
    if not properties:
        return {
            "zip_code": zip_code,
            "city": city,
            "state": state,
            "total_listings": 0,
            "rental_listings": 0,
            "pct_rental": 0.0,
            "average_rent": None,
            "median_rent": None,
            "rent_per_sqft": None,
            "rent_breakdown": [],
            "note": f"No HomeHarvest listings in {zip_code}.",
        }

    rentals = [p for p in properties if _is_rental(p)]
    rents = [
        _coerce_float(p.get("list_price"))
        for p in rentals
        if _coerce_float(p.get("list_price"))
    ]
    rents = [r for r in rents if r and r > 200]  # filter $0/$1 garbage

    avg_rent = round(sum(rents) / len(rents)) if rents else None
    sorted_rents = sorted(rents)
    median_rent = sorted_rents[len(sorted_rents) // 2] if sorted_rents else None

    # rent per sqft from rentals that report sqft
    psf_samples = []
    for p in rentals:
        rent = _coerce_float(p.get("list_price"))
        sqft = _coerce_float(p.get("sqft"))
        if rent and sqft and 100 <= sqft <= 8000 and rent > 200:
            psf_samples.append(rent / sqft)
    rent_per_sqft = round(sum(psf_samples) / len(psf_samples), 2) if psf_samples else None

    # breakdown by bedrooms
    bed_groups: dict[int, list[float]] = defaultdict(list)
    bed_sqft: dict[int, list[float]] = defaultdict(list)
    for p in rentals:
        beds = _coerce_int(p.get("beds"))
        rent = _coerce_float(p.get("list_price"))
        sqft = _coerce_float(p.get("sqft"))
        if beds is None or not rent or rent <= 200:
            continue
        bed_groups[beds].append(rent)
        if sqft:
            bed_sqft[beds].append(sqft)
    rent_breakdown = []
    for beds in sorted(bed_groups.keys()):
        prices = bed_groups[beds]
        sqfts = bed_sqft.get(beds, [])
        rent_breakdown.append({
            "bedrooms": beds,
            "avg_rent": round(sum(prices) / len(prices)),
            "median_rent": sorted(prices)[len(prices) // 2],
            "avg_sqft": round(sum(sqfts) / len(sqfts)) if sqfts else None,
            "count": len(prices),
        })

    return {
        "zip_code": zip_code,
        "city": city,
        "state": state,
        "total_listings": len(properties),
        "rental_listings": len(rentals),
        "pct_rental": round(100.0 * len(rentals) / len(properties), 1) if properties else 0.0,
        "average_rent": float(avg_rent) if avg_rent else None,
        "median_rent": float(median_rent) if median_rent else None,
        "rent_per_sqft": rent_per_sqft,
        "rent_breakdown": rent_breakdown,
        "note": f"Rental stats from {len(rentals)} rental + {len(properties) - len(rentals)} sale listings in {zip_code} (HomeHarvest/Realtor.com).",
    }


# ── Financing math ───────────────────────────────────────────────────────────
def estimate_adu_rent(
    adu_sqft: float,
    zip_context: dict[str, Any],
) -> dict[str, Any]:
    """Estimate monthly rent for an ADU of `adu_sqft` using zip rent comps.

    Strategy:
      1. If we have rent-per-sqft samples, use that × adu_sqft (most direct).
      2. Else use bedroom-bucket average closest to ADU's likely bed count.
      3. Else fall back to overall average rent in the zip.
    """
    if adu_sqft <= 0:
        return {"monthly_rent": None, "method": "no_size", "confidence": "low"}

    rent_per_sqft = zip_context.get("rent_per_sqft")
    if rent_per_sqft:
        return {
            "monthly_rent": round(rent_per_sqft * adu_sqft),
            "rent_per_sqft": rent_per_sqft,
            "method": "rent_per_sqft",
            "confidence": "medium" if zip_context.get("rental_listings", 0) >= 5 else "low",
        }

    likely_beds = 0 if adu_sqft < 500 else (1 if adu_sqft < 750 else 2)
    breakdown = zip_context.get("rent_breakdown") or []
    if breakdown:
        match = min(breakdown, key=lambda b: abs((b.get("bedrooms") or 0) - likely_beds))
        return {
            "monthly_rent": match.get("avg_rent"),
            "method": f"bedroom_bucket_{match.get('bedrooms')}br",
            "confidence": "low",
            "based_on_listings": match.get("count"),
        }
    if zip_context.get("average_rent"):
        return {
            "monthly_rent": round(zip_context["average_rent"]),
            "method": "zip_average",
            "confidence": "low",
        }
    return {"monthly_rent": None, "method": "no_data", "confidence": "low"}


def build_financing(
    adu_width_ft: float,
    adu_depth_ft: float,
    zip_context: dict[str, Any],
    *,
    build_cost_per_sqft: float = 350.0,
    soft_cost_pct: float = 0.18,
    down_payment_pct: float = 0.20,
    interest_rate_pct: float = 7.5,
    loan_term_years: int = 30,
    annual_property_tax_pct: float = 1.25,
    annual_insurance: float = 1200.0,
    annual_maintenance_pct: float = 0.01,
    vacancy_pct: float = 0.05,
    management_pct: float = 0.08,
) -> dict[str, Any]:
    """Build a quick ADU pro-forma: build cost, monthly payment, NOI, cash-on-cash."""
    adu_sqft = max(0.0, adu_width_ft * adu_depth_ft)
    hard_cost = adu_sqft * build_cost_per_sqft
    soft_cost = hard_cost * soft_cost_pct
    total_cost = hard_cost + soft_cost

    down_payment = total_cost * down_payment_pct
    loan_amount = total_cost - down_payment

    # Standard amortizing mortgage payment.
    monthly_rate = (interest_rate_pct / 100.0) / 12.0
    n_payments = loan_term_years * 12
    if monthly_rate > 0 and n_payments > 0:
        monthly_pi = (
            loan_amount * monthly_rate / (1 - (1 + monthly_rate) ** (-n_payments))
        )
    elif n_payments > 0:
        monthly_pi = loan_amount / n_payments
    else:
        monthly_pi = 0.0

    rent_est = estimate_adu_rent(adu_sqft, zip_context)
    monthly_rent = rent_est.get("monthly_rent") or 0
    gross_annual_rent = monthly_rent * 12

    vacancy_loss = gross_annual_rent * vacancy_pct
    mgmt_cost = (gross_annual_rent - vacancy_loss) * management_pct
    property_tax = total_cost * (annual_property_tax_pct / 100.0)
    maintenance = total_cost * annual_maintenance_pct
    annual_operating_expenses = vacancy_loss + mgmt_cost + property_tax + annual_insurance + maintenance
    noi = gross_annual_rent - annual_operating_expenses

    annual_debt_service = monthly_pi * 12
    cash_flow_annual = noi - annual_debt_service
    cash_flow_monthly = cash_flow_annual / 12 if cash_flow_annual else 0

    cash_on_cash_pct = (cash_flow_annual / down_payment * 100) if down_payment else None
    cap_rate_pct = (noi / total_cost * 100) if total_cost else None
    payback_years = (total_cost / cash_flow_annual) if cash_flow_annual > 0 else None
    dscr = (noi / annual_debt_service) if annual_debt_service > 0 else None

    return {
        "inputs": {
            "adu_sqft": round(adu_sqft, 1),
            "build_cost_per_sqft": build_cost_per_sqft,
            "soft_cost_pct": soft_cost_pct,
            "down_payment_pct": down_payment_pct,
            "interest_rate_pct": interest_rate_pct,
            "loan_term_years": loan_term_years,
            "annual_property_tax_pct": annual_property_tax_pct,
            "annual_insurance": annual_insurance,
            "annual_maintenance_pct": annual_maintenance_pct,
            "vacancy_pct": vacancy_pct,
            "management_pct": management_pct,
        },
        "costs": {
            "hard_cost": round(hard_cost),
            "soft_cost": round(soft_cost),
            "total_cost": round(total_cost),
            "down_payment": round(down_payment),
            "loan_amount": round(loan_amount),
        },
        "rent_estimate": rent_est,
        "income": {
            "monthly_rent": round(monthly_rent),
            "gross_annual_rent": round(gross_annual_rent),
        },
        "operating": {
            "vacancy_loss": round(vacancy_loss),
            "management": round(mgmt_cost),
            "property_tax": round(property_tax),
            "insurance": round(annual_insurance),
            "maintenance": round(maintenance),
            "annual_operating_expenses": round(annual_operating_expenses),
            "noi_annual": round(noi),
        },
        "loan": {
            "monthly_payment": round(monthly_pi),
            "annual_debt_service": round(annual_debt_service),
        },
        "returns": {
            "cash_flow_monthly": round(cash_flow_monthly),
            "cash_flow_annual": round(cash_flow_annual),
            "cash_on_cash_pct": round(cash_on_cash_pct, 2) if cash_on_cash_pct is not None else None,
            "cap_rate_pct": round(cap_rate_pct, 2) if cap_rate_pct is not None else None,
            "dscr": round(dscr, 2) if dscr is not None else None,
            "payback_years": round(payback_years, 1) if payback_years is not None else None,
        },
    }


def compute_financial_score(
    adu_sqft: float,
    adu_type: str,
    zip_context: dict[str, Any],
    estimated_value: float | None,
) -> dict[str, Any]:
    """Score the financial attractiveness of the ADU investment (0–100).

    Weights: gross yield 30 pts, breakeven 25 pts, investment ratio 20 pts,
    local rental demand 25 pts.
    """
    cost_per_sqft = 380.0 if adu_type == "detached" else 290.0
    build_cost = adu_sqft * cost_per_sqft

    rent_psf = zip_context.get("rent_per_sqft")
    rental_listings = int(zip_context.get("rental_listings") or 0)

    if rent_psf and rent_psf > 0:
        monthly_rent = round(rent_psf * adu_sqft)
        rent_source = "rent_per_sqft"
    else:
        rent_est = estimate_adu_rent(adu_sqft, zip_context)
        monthly_rent = round(rent_est.get("monthly_rent") or 0)
        rent_source = rent_est.get("method", "no_data")

    annual_rent = monthly_rent * 12
    gross_yield_pct = (annual_rent / build_cost * 100) if build_cost > 0 else None
    breakeven_years = (build_cost / annual_rent) if annual_rent > 0 else None
    investment_ratio_pct = (
        (build_cost / estimated_value * 100)
        if estimated_value and estimated_value > 0 else None
    )
    value_uplift = build_cost * 1.3
    new_estimated_value = (estimated_value + value_uplift) if estimated_value else None
    heloc_equity = (estimated_value * 0.60) if estimated_value else None
    heloc_viable = bool(heloc_equity and heloc_equity >= build_cost)

    # Gross yield: 30 pts linear 0→8% (capped at 30)
    gy_pts = min(30.0, (gross_yield_pct or 0.0) / 8.0 * 30.0)

    # Breakeven: 25 pts at ≤10 yr, linear down to 0 at ≥20 yr
    if breakeven_years is None:
        be_pts = 0.0
    elif breakeven_years <= 10:
        be_pts = 25.0
    elif breakeven_years < 20:
        be_pts = max(0.0, 25.0 * (20 - breakeven_years) / 10)
    else:
        be_pts = 0.0

    # Investment ratio: 20 pts at ≤15%, linear down to 0 at ≥40%; neutral 10 if unknown
    if investment_ratio_pct is None:
        ir_pts = 10.0
    elif investment_ratio_pct <= 15:
        ir_pts = 20.0
    elif investment_ratio_pct < 40:
        ir_pts = max(0.0, 20.0 * (40 - investment_ratio_pct) / 25)
    else:
        ir_pts = 0.0

    # Rental demand: 25 pts linear, capped at 10 listings
    rd_pts = min(25.0, rental_listings / 10.0 * 25.0)

    financial_score = min(100.0, round(gy_pts + be_pts + ir_pts + rd_pts, 1))

    return {
        "adu_sqft": round(adu_sqft, 1),
        "adu_type": adu_type,
        "cost_per_sqft": cost_per_sqft,
        "build_cost": round(build_cost),
        "monthly_rent": monthly_rent,
        "annual_rent": annual_rent,
        "gross_yield_pct": round(gross_yield_pct, 2) if gross_yield_pct is not None else None,
        "breakeven_years": round(breakeven_years, 1) if breakeven_years is not None else None,
        "investment_ratio_pct": round(investment_ratio_pct, 1) if investment_ratio_pct is not None else None,
        "estimated_value": round(estimated_value) if estimated_value else None,
        "value_uplift": round(value_uplift),
        "new_estimated_value": round(new_estimated_value) if new_estimated_value else None,
        "heloc_viable": heloc_viable,
        "heloc_equity_available": round(heloc_equity) if heloc_equity else None,
        "rental_listings": rental_listings,
        "rent_source": rent_source,
        "financial_score": financial_score,
        "score_breakdown": {
            "gross_yield_pts": round(gy_pts, 1),
            "breakeven_pts": round(be_pts, 1),
            "investment_ratio_pts": round(ir_pts, 1),
            "rental_demand_pts": round(rd_pts, 1),
        },
    }
