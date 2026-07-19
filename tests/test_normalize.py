"""Unit tests for normalisation & matching.

Runnable with pytest, or directly: ``python -m tests.test_normalize``.
"""

from __future__ import annotations

from engine.models import WatchItem
from engine.normalize import (
    canonical_brand,
    colors_match,
    extract_color_from_text,
    extract_size_from_text,
    match_score,
    normalize_color,
    normalize_size,
    sizes_match,
)


def test_canonical_brand():
    assert canonical_brand("arcteryx") == "Arc'teryx"
    assert canonical_brand("Arc'teryx") == "Arc'teryx"
    assert canonical_brand("scaroa") == "Scarpa"          # common typo
    assert canonical_brand("fjallraven") == "Fjällräven"
    assert canonical_brand("sportiva") == "La Sportiva"
    assert canonical_brand("tnf") == "The North Face"
    assert canonical_brand("Some Random Brand") is None


def test_normalize_size():
    assert normalize_size("Extra Large") == "XL"
    assert normalize_size("medium") == "M"
    assert normalize_size("xxl") == "XXL"
    assert normalize_size("65l") == "65L"
    assert normalize_size("US 10.5") == "US 10.5"


def test_sizes_match():
    assert sizes_match(["M", "L"], "medium") is True
    assert sizes_match(["M", "L"], "XL") is False
    assert sizes_match([], "anything") is True       # empty desired = any
    assert sizes_match(["M"], None) is False


def test_colors():
    assert normalize_color("Pirate Black") == "black"
    assert normalize_color("TNF Navy") == "blue"
    assert colors_match(["black"], "TNF Black") is True
    assert colors_match(["blue"], "black") is False
    assert colors_match([], None) is True


def test_extract_size_from_text():
    assert extract_size_from_text("Men's Jacket Size XL Black") == "XL"
    assert extract_size_from_text("Backpack 65L Blue") == "65L"
    assert extract_size_from_text("Hiking Boot US 10.5 Brown") == "US 10.5"
    assert extract_size_from_text("Just a plain jacket, no size") is None


def test_extract_color_from_text():
    assert extract_color_from_text("Arc'teryx Beta AR Jacket Black") == "black"
    assert extract_color_from_text("Nano Puff Forest Green") == "green"
    assert extract_color_from_text("Product with no colour word") is None


def test_match_score():
    w = WatchItem(id="x", brand="Arc'teryx", name="Beta AR Jacket",
                  keywords=["gore-tex"])
    good = match_score(w, "Arc'teryx Beta AR Jacket Men's Gore-Tex Black")
    assert good >= 0.6
    # brand mismatch => zero
    assert match_score(w, "Patagonia Nano Puff Jacket") == 0.0
    # different Arc'teryx product => low
    assert match_score(w, "Arc'teryx Cerium LT Hoody") < 0.6


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
