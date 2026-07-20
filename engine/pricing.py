"""Price reasoning: currency normalisation + a robust "regular price".

The hardest source of *false* deals is a bad reference price:

* a **fake-inflated "was" price** ("$500 → $250" when it never sold above $260),
* a **median dragged down** by an item that is permanently on sale,
* **mixed currencies** compared as if equal.

So the regular (non-sale) price is estimated conservatively as the **max** of:
the explicit MSRP (if given), the source's "was"/list price (only when it is
believable vs. observed prices), and a **high percentile** of recent prices
(the price the item usually sits at when *not* discounted). All inputs are first
converted to a single base currency.
"""

from __future__ import annotations

from typing import Optional


def to_base(price: float, currency: str, rates: dict[str, float], base: str = "USD") -> float:
    """Convert ``price`` in ``currency`` to ``base`` using a static rate table
    (value of 1 unit in USD). Unknown currencies are treated as already-base."""
    if not price:
        return price
    r_from = rates.get((currency or base).upper(), 1.0)
    r_base = rates.get(base.upper(), 1.0) or 1.0
    return price * r_from / r_base


def percentile(values: list[float], p: float) -> Optional[float]:
    """Linear-interpolated percentile (p in 0..100)."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def regular_price(
    recent_prices: list[float],
    list_prices: list[float],
    msrp: Optional[float],
    *,
    percentile_p: float = 85.0,
    min_points: int = 4,
    max_list_ratio: float = 1.4,
) -> tuple[Optional[float], str]:
    """Estimate the regular (non-sale) price and the basis used.

    ``recent_prices`` / ``list_prices`` must already be in the base currency.
    Returns ``(None, "insufficient data")`` when there's nothing to anchor to —
    in which case only an explicit target price can make something a deal (we
    never invent a discount).
    """
    pctl = percentile(recent_prices, percentile_p) if len(recent_prices) >= min_points else None

    candidates: list[tuple[float, str]] = []
    if msrp and msrp > 0:
        candidates.append((float(msrp), "MSRP"))

    list_anchor = max(list_prices) if list_prices else None
    if list_anchor is not None:
        # Trust a "was" price only if it isn't wildly above what the item
        # actually sells for (guards against fake-inflated reference prices).
        if pctl is None or list_anchor <= max_list_ratio * pctl:
            candidates.append((float(list_anchor), "list price"))

    if pctl is not None:
        candidates.append((float(pctl), f"p{int(percentile_p)} of recent prices"))

    if not candidates:
        return (None, "insufficient data")

    regular, basis = max(candidates, key=lambda c: c[0])
    return (regular, basis)


def discount_pct(regular: Optional[float], price: float) -> Optional[float]:
    if not regular or regular <= 0:
        return None
    return round((regular - price) / regular * 100.0, 1)
