"""The decision brain — Buy / Wait / Hold, cautiously.

Finding a deal isn't enough; the operator needs to know **whether to act**. The
brain reads the product's own price history and the credibility assessment and
returns a recommendation plus a confidence — and it is deliberately conservative
so it never manufactures illusions:

* **hold** — not credible (see credibility.py), or the discount is weak. Do not
  chase.
* **buy** — a credible discount at/near the item's historical floor, or an
  off-season clearance (already near the bottom of the year).
* **wait** — a credible but middling price for an item that history says usually
  drops further (in season).

Cult/premium legitimate deals from authorized/outlet channels are also marked
**flash** (they tend to sell out within the hour), which nudges "buy now".
"""

from __future__ import annotations

from statistics import median
from typing import Optional

from .credibility import Credibility


def price_stats(prices: list[float]) -> Optional[dict]:
    if not prices:
        return None
    return {"min": round(min(prices), 2), "max": round(max(prices), 2),
            "median": round(median(prices), 2), "n": len(prices)}


def percentile_rank(prices: list[float], value: float) -> Optional[float]:
    """Fraction of history cheaper than ``value`` (0.0 = cheapest ever seen)."""
    if not prices:
        return None
    below = sum(1 for p in prices if p < value)
    return round(below / len(prices), 2)


def recommend(effective_discount: Optional[float], effective_price: float,
              history_prices: list[float], cred: Credibility, *,
              is_offseason: bool, sale_window: Optional[str],
              min_discount: float, min_points: int,
              match_score: float) -> tuple[str, bool, float, Optional[str], Optional[float]]:
    """Return (recommendation, flash, confidence, note, price_percentile)."""
    pr = (percentile_rank(history_prices, effective_price)
          if len(history_prices) >= min_points else None)

    # Not credible -> never present as an opportunity.
    if cred.implausible:
        conf = round(cred.credibility * (0.4 + 0.4 * _clamp(match_score)), 2)
        return "hold", False, conf, "verificar condición/autenticidad antes de comprar", pr

    flash = (cred.tier in ("cult", "premium")
             and cred.channel_class in ("authorized", "outlet")
             and (is_offseason or bool(sale_window)))

    near_low = pr is not None and pr <= 0.15
    mediocre = pr is not None and pr >= 0.5
    note: Optional[str] = None

    if effective_discount is None or effective_discount < min_discount:
        rec = "hold"
    elif near_low or is_offseason:
        rec = "buy"
    elif mediocre:
        rec = "wait"
        note = "suele bajar más; esperar salvo que se agote"
    else:
        rec = "buy"

    conf = cred.credibility * (0.5 + 0.5 * _clamp(match_score))
    if pr is None:
        conf *= 0.85  # less certain without enough history
    if flash and rec == "wait":
        rec, note = "buy", "oferta relámpago — suele agotarse en poco tiempo"
    return rec, flash, round(min(1.0, conf), 2), note, pr


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))
