"""Deal detection v2 — astute, seasonal, and defensive against false positives.

An offer becomes a ranked *deal* only after passing several gates designed to
kill the usual sources of bad detections:

* **Like-for-like**: used/out-of-stock/stale offers don't count as buying "the
  same article new" (configurable); prices are normalised to one currency.
* **Honest reference**: the discount is measured against a robust *regular*
  price (MSRP / believable "was" price / high percentile of recent prices), not
  a median that sale-heavy items drag down (see ``pricing.py``).
* **Believable band**: below the threshold isn't a deal; **above ~68% is
  treated as suspect** (wrong match or price error) and only surfaces if the
  product match is near-certain — otherwise it's dropped.
* **Seasonality**: off-season buys (winter gear in summer) are surfaced earlier
  and ranked higher — the biggest, most reliable discounts.

Each surviving deal gets a 0–100 **score** and a **tier** so the operator acts
on the best first.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .config import Config
from .effective import compute_effective
from .identity import home_region_advantage
from .models import Deal, Offer, PricePoint, WatchItem, now_iso
from .normalize import colors_match, sizes_match
from .pricing import discount_pct, regular_price, to_base
from .seasons import active_sale_window, offseason_status, use_season


def _date_of(ts: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(ts).date()
    except (ValueError, TypeError):
        return None


def _age_days(ts: str, today: date) -> Optional[int]:
    d = _date_of(ts)
    return (today - d).days if d else None


def _lowest_in_days(history: list[PricePoint], price: float, today: date) -> Optional[int]:
    """Days since the price was last strictly cheaper (i.e. 'cheapest in N days')."""
    pts = [(_date_of(h.ts), h.price) for h in history]
    pts = [(d, p) for d, p in pts if d is not None]
    if not pts:
        return None
    pts.sort()
    cheaper = [d for d, p in pts if p < price - 1e-9]
    if cheaper:
        return max(0, (today - max(cheaper)).days)
    return max(0, (today - pts[0][0]).days)  # never cheaper => lowest across span


def _tier(discount: Optional[float], suspect: bool) -> str:
    if suspect:
        return "suspect"
    if discount is None:
        return "target"
    if discount >= 45:
        return "excellent"
    if discount >= 30:
        return "great"
    if discount >= 15:
        return "good"
    return "target"


def _score(discount: Optional[float], strength: int, lowest_in_days: Optional[int],
           match_score: float, channel: str, suspect: bool, in_window: bool,
           offseason_boost: float) -> float:
    disc = discount or 0.0
    s = min(max(disc, 0.0), 60.0) / 60.0 * 70.0        # discount up to +70
    if strength:
        s += strength * (offseason_boost / 2.0)        # off-season: +½·boost per strength
    if lowest_in_days:
        s += min(lowest_in_days, 120) / 120.0 * 12.0   # long-standing low: up to +12
    if in_window:
        s += 3.0
    s *= 0.7 + 0.3 * max(0.0, min(match_score, 1.0))   # scale by match confidence
    if channel == "used":
        s -= 20.0                                      # different market / risk
    elif channel == "refurbished":
        s -= 12.0                                      # restored, still a real buy
    if suspect:
        s -= 25.0
    return round(max(0.0, min(100.0, s)), 1)


def detect_deals(
    cfg: Config,
    watch: WatchItem,
    offers: list[Offer],
    history: list[PricePoint],
    ledger: dict[str, str],
    today: Optional[date] = None,
    promos: Optional[dict] = None,
) -> tuple[list[Deal], list[Deal]]:
    """Return (all_active_deals sorted by score desc, new_deals_to_alert)."""
    today = today or datetime.now(timezone.utc).date()
    d = cfg.get("detection", {})
    ssn = cfg.get("seasonality", {})
    fx = cfg.get("fx", {})
    rates = fx.get("rates", {}) or {}
    base = fx.get("base", "USD")

    cat_overrides = d.get("category_min_discount", {}) or {}
    min_discount = (watch.min_discount_pct
                    if watch.min_discount_pct is not None
                    else cat_overrides.get(watch.category, d.get("min_discount_pct", 15.0)))
    suspect_pct = float(d.get("suspect_discount_pct", 68.0))
    min_points = int(d.get("min_history_points", 4))
    pctl_p = float(d.get("baseline_percentile", 85.0))
    window_days = int(d.get("baseline_window_days", 120))
    require_stock = bool(d.get("require_in_stock", True))
    include_used = bool(d.get("include_used", False))
    include_refurbished = bool(d.get("include_refurbished", True))
    max_age = int(d.get("max_offer_age_days", 3))
    ttl_days = int(d.get("alert_ttl_days", 7))
    suspect_min_match = float(d.get("suspect_min_match_score", 0.9))
    offseason_boost = float(ssn.get("offseason_boost", 12.0))
    offseason_relax = float(ssn.get("offseason_discount_relax", 3.0))
    hemisphere = ssn.get("hemisphere", "north")

    # --- seasonality context for this product -----------------------------
    p_season = use_season(watch.category, watch.season)
    is_off, strength, season_note = offseason_status(p_season, today, hemisphere)
    sale_window = active_sale_window(today)
    home_adv, hr = home_region_advantage(watch, offers)  # brand home market cheaper?
    effective_min = min_discount - (offseason_relax * strength if is_off else 0.0)
    effective_min = max(effective_min, 8.0)  # never chase sub-8% "deals"

    # --- reference inputs (base currency, new condition) ------------------
    cutoff = today - timedelta(days=window_days)
    recent = [h.price for h in history
              if (h.condition or "new") == "new"
              and (_date_of(h.ts) or today) >= cutoff]
    list_prices = [to_base(o.list_price, o.currency, rates, base)
                   for o in offers if o.list_price and (include_used or o.condition == "new")]
    msrp_base = to_base(watch.msrp, watch.currency, rates, base) if watch.msrp else None
    regular, basis = regular_price(recent, list_prices, msrp_base,
                                   percentile_p=pctl_p, min_points=min_points)

    target_base = (to_base(watch.target_price, watch.currency, rates, base)
                   if watch.target_price is not None else None)

    active: list[Deal] = []
    for o in offers:
        if not sizes_match(watch.sizes, o.size) or not colors_match(watch.colors, o.color):
            continue
        # Resolve channel (falls back to condition when offers aren't enriched).
        ch = o.channel if o.channel and o.channel != "new" else (
            o.condition if o.condition in ("used", "refurbished") else "new")
        if ch == "used" and not include_used:
            continue
        if ch == "refurbished" and not include_refurbished:
            continue
        if require_stock and o.availability == "out_of_stock":
            continue
        age = _age_days(o.fetched_at, today)
        if age is not None and age > max_age:
            continue

        price_base = to_base(o.price, o.currency, rates, base)
        merch_disc = discount_pct(regular, price_base)   # sticker discount

        # Effective (all-in) price after stacking every legitimate lever.
        eff = compute_effective(o.price, o.currency, o.source, watch.brand,
                                watch.category, promos, rates, base, today)
        eff_price = eff.effective_price
        eff_disc = discount_pct(regular, eff_price)

        target_hit = target_base is not None and eff_price <= target_base
        discount_ok = eff_disc is not None and eff_disc >= effective_min
        if not (target_hit or discount_ok):
            continue

        # Suspicion is about the RAW price being anomalously low (mismatch/price
        # error) — a legitimately *stacked* effective discount is not suspect.
        suspect = merch_disc is not None and merch_disc > suspect_pct
        if suspect and o.match_score < suspect_min_match:
            continue  # drop rather than raise a false alarm

        low_days = _lowest_in_days(history, price_base, today) if len(history) >= min_points else None
        stacked = (eff_disc is not None and merch_disc is not None
                   and eff_disc - merch_disc >= 1.0)

        reasons: list[str] = []
        if target_hit:
            reasons.append(f"En/bajo objetivo ({eff_price:.0f} ≤ {target_base:.0f})")
        if eff_disc is not None and eff_disc > 0:
            if stacked:
                reasons.append(f"{eff_disc:.0f}% efectivo ({merch_disc:.0f}% precio + apilado)")
            else:
                reasons.append(f"{eff_disc:.0f}% bajo {basis}")
        if low_days and low_days >= 30:
            reasons.append(f"precio más bajo en {low_days}+ días")
        if is_off and season_note:
            reasons.append(season_note.split(" — ")[0])
        if sale_window:
            reasons.append(f"ventana: {sale_window}")
        if suspect:
            reasons.append("⚠ descuento inusual — verificar")
        if ch in ("outlet", "refurbished", "used"):
            reasons.append({"outlet": "outlet", "refurbished": "reacondicionado",
                            "used": "usado"}[ch])
        offer_home_adv = bool(home_adv and o.region == hr)
        if offer_home_adv:
            reasons.append(f"mejor precio en su mercado de origen ({hr})")
        elif o.region != "US":
            reasons.append(f"región {o.region}")

        active.append(Deal(
            watch_id=watch.id, brand=watch.brand, product_name=watch.name,
            source=o.source, url=o.url, price=o.price, currency=o.currency,
            size=o.size, color=o.color, condition=o.condition,
            reason="; ".join(reasons),
            discount_pct=merch_disc, reference_price=regular, target_price=watch.target_price,
            effective_price=eff_price, effective_discount_pct=eff_disc,
            coupon_code=eff.coupon_code, stack_note=(eff.note if stacked else None),
            score=_score(eff_disc, strength if is_off else 0, low_days, o.match_score,
                         ch, suspect, bool(sale_window), offseason_boost),
            tier=_tier(eff_disc, suspect),
            seasonal=bool(is_off), season_note=season_note if is_off else None,
            suspect=suspect, lowest_in_days=low_days,
            channel=ch, region=o.region, home_region_advantage=offer_home_adv,
            detected_at=now_iso(),
        ))

    active.sort(key=lambda x: x.score, reverse=True)

    # De-duplicate for alerting via the ledger (key -> last alert ISO ts).
    new: list[Deal] = []
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    for deal in active:
        last = ledger.get(deal.key)
        recent_alert = False
        if last:
            try:
                recent_alert = datetime.fromisoformat(last) > cutoff_dt
            except ValueError:
                recent_alert = False
        if not recent_alert:
            new.append(deal)

    return active, new
