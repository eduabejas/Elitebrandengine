"""Unit tests for the seasonality engine.

Runnable with pytest, or directly: ``python -m tests.test_seasons``.
"""

from __future__ import annotations

from datetime import date

from engine.seasons import (
    active_sale_window,
    current_season,
    offseason_status,
    use_season,
)


def test_current_season_hemispheres():
    july = date(2026, 7, 15)
    assert current_season(july, "north") == "summer"
    assert current_season(july, "south") == "winter"
    assert current_season(date(2026, 1, 10), "north") == "winter"


def test_use_season_inference():
    assert use_season("Down Jacket") == "winter"
    assert use_season("Mountaineering Boots") == "winter"
    assert use_season("Backpack") == "3season"
    assert use_season("Climbing Shoes") == "summer"
    assert use_season("Hiking Boots") == "3season"
    assert use_season("Anything", explicit="summer") == "summer"   # override wins


def test_offseason_winter_gear_peaks_in_summer():
    is_off, strength, note = offseason_status("winter", date(2026, 7, 15), "north")
    assert is_off and strength == 2 and note


def test_winter_gear_in_winter_is_in_season():
    is_off, strength, _ = offseason_status("winter", date(2026, 1, 15), "north")
    assert not is_off and strength == 0


def test_summer_gear_offseason_in_winter():
    is_off, strength, note = offseason_status("summer", date(2026, 1, 15), "north")
    assert is_off and strength == 2 and note


def test_three_season_never_offseason():
    assert offseason_status("3season", date(2026, 7, 15), "north") == (False, 0, None)


def test_active_sale_window():
    assert active_sale_window(date(2026, 11, 25)) == "Black Friday / Cyber Monday"
    assert "invierno" in (active_sale_window(date(2026, 3, 1)) or "").lower()
    assert active_sale_window(date(2026, 6, 20)) is None


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
