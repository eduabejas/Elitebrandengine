"""Deal detection.

An offer becomes a *deal* when at least one of these is true:

1. **Target hit** — the operator set a ``target_price`` and the offer is at or
   below it.
2. **Discount vs. reference** — the price is ``min_discount_pct`` below a
   reference, where the reference is the source's own "was" price when present,
   otherwise the median of recent history.
3. **New historical low** — with enough history, the price undercuts every
   observation seen so far.

Only variants matching the desired size/colour qualify, and a ledger prevents
the same deal being emailed repeatedly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Optional

from .config import Config
from .models import Deal, Offer, PricePoint, WatchItem, now_iso
from .normalize import colors_match, sizes_match


def _reference_price(
    offer: Offer, history: list[PricePoint], min_points: int
) -> tuple[Optional[float], str]:
    """Return (reference_price, basis) used to judge the discount."""
    if offer.list_price and offer.list_price > offer.price:
        return offer.list_price, "list price"
    same_source = [h.price for h in history if h.source == offer.source]
    pool = same_source if len(same_source) >= min_points else [h.price for h in history]
    if len(pool) >= min_points:
        return float(median(pool)), "recent median"
    return None, "insufficient history"


def detect_deals(
    cfg: Config,
    watch: WatchItem,
    offers: list[Offer],
    history: list[PricePoint],
    ledger: dict[str, str],
) -> tuple[list[Deal], list[Deal]]:
    """Return (all_active_deals, new_deals_to_alert) for one watch item."""
    d = cfg.get("detection", {})
    min_discount = float(d.get("min_discount_pct", 15.0))
    min_points = int(d.get("min_history_points", 4))
    ttl_days = int(d.get("alert_ttl_days", 7))

    hist_prices = [h.price for h in history]
    hist_low = min(hist_prices) if hist_prices else None

    active: list[Deal] = []
    for o in offers:
        # Respect the desired variant (size/colour). Empty desired = any.
        if not sizes_match(watch.sizes, o.size):
            continue
        if not colors_match(watch.colors, o.color):
            continue

        ref, basis = _reference_price(o, history, min_points)
        discount_pct = None
        if ref and ref > 0:
            discount_pct = round((ref - o.price) / ref * 100.0, 1)

        reasons: list[str] = []
        if watch.target_price is not None and o.price <= watch.target_price:
            reasons.append(f"At/below target ({o.price:.2f} ≤ {watch.target_price:.2f})")
        if discount_pct is not None and discount_pct >= min_discount:
            reasons.append(f"{discount_pct:.0f}% below {basis}")
        if (
            hist_low is not None
            and len(hist_prices) >= min_points
            and o.price < hist_low
        ):
            reasons.append("Lowest price ever recorded")

        if not reasons:
            continue

        active.append(
            Deal(
                watch_id=watch.id,
                brand=watch.brand,
                product_name=watch.name,
                source=o.source,
                url=o.url,
                price=o.price,
                currency=o.currency,
                size=o.size,
                color=o.color,
                condition=o.condition,
                reason="; ".join(reasons),
                discount_pct=discount_pct,
                reference_price=ref,
                target_price=watch.target_price,
                detected_at=now_iso(),
            )
        )

    # Deduplicate for alerting via the ledger (key -> last alert ISO ts).
    new: list[Deal] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    for deal in active:
        last = ledger.get(deal.key)
        recent = False
        if last:
            try:
                recent = datetime.fromisoformat(last) > cutoff
            except ValueError:
                recent = False
        if not recent:
            new.append(deal)

    return active, new
