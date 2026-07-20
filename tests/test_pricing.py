"""Unit tests for currency + robust regular-price estimation.

Runnable with pytest, or directly: ``python -m tests.test_pricing``.
"""

from __future__ import annotations

from engine.pricing import discount_pct, percentile, regular_price, to_base

RATES = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27}


def test_to_base():
    assert to_base(100, "USD", RATES) == 100
    assert round(to_base(100, "EUR", RATES), 2) == 108.0
    assert to_base(50, "XYZ", RATES) == 50   # unknown => treat as base


def test_percentile():
    assert percentile([], 50) is None
    assert percentile([5], 50) == 5
    assert percentile([1, 2, 3, 4], 0) == 1
    assert percentile([1, 2, 3, 4], 100) == 4
    assert percentile([1, 2, 3, 4], 50) == 2.5


def test_regular_price_prefers_msrp():
    reg, basis = regular_price([190, 195], [], 300.0)
    assert reg == 300.0 and basis == "MSRP"


def test_regular_price_ignores_fake_inflated_list():
    # regular should track the real ~200, not a fake $500 "was"
    reg, basis = regular_price([200, 200, 201, 199], [500.0], None)
    assert reg < 260 and "recent" in basis


def test_regular_price_trusts_believable_list():
    reg, _ = regular_price([200, 200, 201, 199], [260.0], None)
    assert reg == 260.0


def test_regular_price_insufficient_data():
    reg, basis = regular_price([], [], None)
    assert reg is None and basis == "insufficient data"


def test_discount_pct():
    assert discount_pct(200, 150) == 25.0
    assert discount_pct(None, 150) is None
    assert discount_pct(0, 150) is None


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
