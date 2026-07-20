"""Unit tests for watchlist validation.

Runnable with pytest, or directly: ``python -m tests.test_validate``.
"""

from __future__ import annotations

from engine.validate import validate_items


def test_valid_item_passes():
    items = [{"id": "a", "brand": "Patagonia", "name": "Nano Puff",
              "sizes": ["M"], "colors": ["black"], "target_price": 100}]
    errors, warnings = validate_items(items)
    assert errors == [] and warnings == []


def test_duplicate_id_is_error():
    items = [{"id": "a", "brand": "Rab", "name": "X"},
             {"id": "a", "brand": "Rab", "name": "Y"}]
    errors, _ = validate_items(items)
    assert any("duplicate" in e for e in errors)


def test_missing_name_is_error():
    items = [{"id": "a", "brand": "Rab"}]
    errors, _ = validate_items(items)
    assert any("name" in e for e in errors)


def test_unknown_brand_is_warning_not_error():
    items = [{"id": "a", "brand": "Totally Made Up", "name": "X"}]
    errors, warnings = validate_items(items)
    assert errors == [] and any("flagship" in w for w in warnings)


def test_bad_target_price_is_error():
    items = [{"id": "a", "brand": "Rab", "name": "X", "target_price": -5}]
    errors, _ = validate_items(items)
    assert any("target_price" in e for e in errors)


def test_sizes_must_be_list():
    items = [{"id": "a", "brand": "Rab", "name": "X", "sizes": "M"}]
    errors, _ = validate_items(items)
    assert any("sizes" in e for e in errors)


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
