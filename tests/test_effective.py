"""Unit tests for effective landed-cost stacking.

Runnable with pytest, or directly: ``python -m tests.test_effective``.
"""

from __future__ import annotations

from datetime import date

from engine.effective import compute_effective

RATES = {"USD": 1.0}
TODAY = date(2026, 7, 20)

PROMOS = {
    "sources": {
        "_default": {"shipping": {"free_over": 50, "flat": 7.0}},
        "REI Co-op": {"shipping": {"free_over": 60, "flat": 6.0}, "cashback_pct": 0.02, "rewards_pct": 0.10},
    },
    "coupons": [
        {"code": "C15", "source": "REI Co-op", "type": "percent", "value": 0.15, "min_subtotal": 100, "expires": "2099-01-01"},
        {"code": "OLD", "source": "*", "type": "percent", "value": 0.5, "min_subtotal": 0, "expires": "2000-01-01"},
        {"code": "EXBRAND", "source": "*", "type": "percent", "value": 0.20, "min_subtotal": 0, "brands_excluded": ["Patagonia"]},
    ],
}


def _eff(price, source, brand="Rab"):
    return compute_effective(price, "USD", source, brand, "Jacket", PROMOS, RATES, "USD", TODAY)


def test_no_promos_effective_equals_price():
    b = compute_effective(100, "USD", "REI Co-op", "Rab", "Jacket", None, RATES, "USD", TODAY)
    assert b.effective_price == 100 and b.coupon_code is None


def test_coupon_and_stack_numeric():
    # Patagonia is excluded from the wildcard 20% coupon, so C15 (15%) is chosen.
    b = _eff(200, "REI Co-op", brand="Patagonia")
    # subtotal 170, free ship, cashback 3.40, rewards 17.00 -> 149.60
    assert b.coupon_code == "C15" and b.coupon_savings == 30.0
    assert abs(b.effective_price - 149.60) < 0.01


def test_best_coupon_is_chosen():
    # For an allowed brand, the bigger wildcard coupon (20%) beats C15 (15%).
    b = _eff(200, "REI Co-op", brand="Rab")
    assert b.coupon_code == "EXBRAND" and b.coupon_savings == 40.0


def test_coupon_below_min_and_excluded_brand_no_coupon():
    b = _eff(80, "REI Co-op", brand="Patagonia")  # C15 below min, EXBRAND excludes Patagonia
    assert b.coupon_code is None


def test_excluded_brand_vs_allowed():
    excluded = compute_effective(100, "USD", "Amazon", "Patagonia", "Jacket", PROMOS, RATES, "USD", TODAY)
    allowed = compute_effective(100, "USD", "Amazon", "Rab", "Jacket", PROMOS, RATES, "USD", TODAY)
    assert excluded.coupon_code is None and allowed.coupon_code == "EXBRAND"


def test_shipping_threshold():
    # brand Patagonia is excluded from the only wildcard coupon -> isolates shipping.
    under = compute_effective(40, "USD", "SomeStore", "Patagonia", "Jacket", PROMOS, RATES, "USD", TODAY)
    over = compute_effective(60, "USD", "SomeStore", "Patagonia", "Jacket", PROMOS, RATES, "USD", TODAY)
    assert under.shipping == 7.0 and over.shipping == 0.0
    assert under.effective_price == 47.0   # 40 + 7 shipping, no other levers


def test_expired_coupon_ignored():
    # OLD (50%) is expired; must never be selected even though it's the biggest.
    b = _eff(300, "Amazon")   # only EXBRAND (20%) applies for Rab
    assert b.coupon_code == "EXBRAND"


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
