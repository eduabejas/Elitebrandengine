"""Effective landed cost — rank by what you *actually* pay, not the sticker.

Most tools compare the shown price. The edge here is comparing the **effective
price**: the real out-of-pocket after stacking every legitimate lever that
applies to a given retailer/product::

    effective = price
              − best applicable coupon
              + shipping (if under the free threshold)
              + sales tax / duty
              − cashback (portal/card %)
              − gift-card discount (paying with discounted gift cards)
              − loyalty rewards value (e.g. REI dividend)

A mediocre 10%-off sale plus a 15% coupon, 6% cashback and free shipping can beat
a flashier 25%-off sale elsewhere. The detector triggers and ranks on the
effective discount, while the *suspect* guard stays on the raw price (a stacked
discount is legitimate; an anomalously low raw price is not).

Modifiers and coupons come from ``data/promos.json`` (operator-maintained now,
auto-ingestible from coupon feeds later). With no promos configured, the
effective price equals the (currency-normalised) price — fully backward
compatible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from .normalize import canonical_brand
from .pricing import to_base

_ZERO_SHIPPING = {"free_over": 0.0, "flat": 0.0}


@dataclass
class EffectiveBreakdown:
    price_base: float                       # currency-normalised sticker price
    effective_price: float                  # real out-of-pocket
    coupon_code: Optional[str] = None
    coupon_savings: float = 0.0
    shipping: float = 0.0
    tax: float = 0.0
    cashback: float = 0.0
    giftcard_savings: float = 0.0
    rewards_value: float = 0.0
    note: str = ""


def _source_mod(promos: dict, source: str) -> dict[str, Any]:
    """Merge _default <- per-source modifiers over zeroed defaults."""
    base = {"shipping": dict(_ZERO_SHIPPING), "tax_rate": 0.0, "tax_shipping": False,
            "cashback_pct": 0.0, "giftcard_discount_pct": 0.0, "rewards_pct": 0.0}
    sources = (promos or {}).get("sources", {}) or {}
    for key in ("_default", source):
        override = sources.get(key)
        if isinstance(override, dict):
            for k, v in override.items():
                if k == "shipping" and isinstance(v, dict):
                    base["shipping"] = {**base["shipping"], **v}
                else:
                    base[k] = v
    return base


def _coupon_applies(c: dict, source: str, brand: Optional[str],
                    category: Optional[str], subtotal: float, today: date) -> bool:
    csrc = c.get("source", "*")
    if csrc not in ("*", source):
        return False
    exp = c.get("expires")
    if exp:
        try:
            if date.fromisoformat(exp) < today:
                return False
        except ValueError:
            pass
    if subtotal < float(c.get("min_subtotal", 0)):
        return False
    bcanon = canonical_brand(brand) or (brand or "")
    excluded_brands = {canonical_brand(b) or b for b in c.get("brands_excluded", [])}
    if bcanon in excluded_brands:
        return False
    if category and category in set(c.get("categories_excluded", [])):
        return False
    return True


def _coupon_savings(c: dict, subtotal: float) -> float:
    if c.get("type") == "fixed":
        return min(float(c.get("value", 0)), subtotal)
    return float(c.get("value", 0)) * subtotal     # percent (0.15 = 15%)


def _best_coupon(promos: dict, source: str, brand, category, subtotal, today):
    best = None
    best_savings = 0.0
    for c in (promos or {}).get("coupons", []) or []:
        if not _coupon_applies(c, source, brand, category, subtotal, today):
            continue
        s = _coupon_savings(c, subtotal)
        if s > best_savings:
            best, best_savings = c, s
    return best, best_savings


def _money(x: float) -> str:
    return f"${x:,.2f}"


def compute_effective(price: float, currency: str, source: str,
                      brand: Optional[str], category: Optional[str],
                      promos: Optional[dict], rates: dict, base: str,
                      today: date) -> EffectiveBreakdown:
    price_base = round(to_base(price, currency, rates, base), 2)
    if not promos:
        return EffectiveBreakdown(price_base=price_base, effective_price=price_base)

    coupon, coupon_savings = _best_coupon(promos, source, brand, category, price_base, today)
    coupon_savings = round(coupon_savings, 2)
    subtotal = max(0.0, price_base - coupon_savings)

    mod = _source_mod(promos, source)
    ship_cfg = mod.get("shipping", _ZERO_SHIPPING)
    shipping = 0.0 if subtotal >= float(ship_cfg.get("free_over", 0)) else float(ship_cfg.get("flat", 0))
    tax_base = subtotal + (shipping if mod.get("tax_shipping") else 0.0)
    tax = round(float(mod.get("tax_rate", 0.0)) * tax_base, 2)
    total_paid = subtotal + shipping + tax

    giftcard = round(float(mod.get("giftcard_discount_pct", 0.0)) * total_paid, 2)
    cashback = round(float(mod.get("cashback_pct", 0.0)) * subtotal, 2)
    rewards = round(float(mod.get("rewards_pct", 0.0)) * subtotal, 2)
    effective = round(total_paid - giftcard - cashback - rewards, 2)

    parts = []
    if coupon:
        parts.append(f"cupón {coupon.get('code', '?')} (−{_money(coupon_savings)})")
    parts.append("envío gratis" if shipping == 0 else f"envío {_money(shipping)}")
    if tax:
        parts.append(f"imp. {_money(tax)}")
    if cashback:
        parts.append(f"{float(mod['cashback_pct'])*100:.0f}% cashback (−{_money(cashback)})")
    if giftcard:
        parts.append(f"gift-card (−{_money(giftcard)})")
    if rewards:
        parts.append(f"{float(mod['rewards_pct'])*100:.0f}% recompensa (−{_money(rewards)})")

    return EffectiveBreakdown(
        price_base=price_base, effective_price=effective,
        coupon_code=(coupon or {}).get("code"), coupon_savings=coupon_savings,
        shipping=shipping, tax=tax, cashback=cashback,
        giftcard_savings=giftcard, rewards_value=rewards,
        note=" · ".join(parts),
    )
