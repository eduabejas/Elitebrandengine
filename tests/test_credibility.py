"""Unit tests for the credibility model (don't manufacture illusions).

Runnable with pytest, or directly: ``python -m tests.test_credibility``.
"""

from __future__ import annotations

from engine.credibility import assess, believable_ceiling, brand_tier, channel_class


def test_brand_tier():
    assert brand_tier("Peak Performance") == "cult"
    assert brand_tier("Helly Hansen") == "cult"
    assert brand_tier("Mammut") == "cult"
    assert brand_tier("The North Face") == "mass"
    assert brand_tier("Patagonia") == "premium"
    assert brand_tier("Totally Unknown") == "premium"


def test_channel_class():
    assert channel_class("eBay") == "marketplace"
    assert channel_class("REI Co-op") == "authorized"
    assert channel_class("REI Re/Supply (outlet)", "outlet") == "outlet"


def test_ceilings():
    assert believable_ceiling("cult", "marketplace") == 25
    assert believable_ceiling("mass", "marketplace") == 65


def test_cult_deep_resale_is_implausible():
    # THE benchmark to avoid: cult brand −50% new on a marketplace.
    c = assess("Peak Performance", "eBay", "new", 50.0, "new")
    assert c.implausible and c.credibility < 1.0 and c.note


def test_cult_moderate_authorized_is_credible():
    c = assess("Peak Performance", "REI Co-op", "new", 35.0, "new")
    assert not c.implausible and c.credibility == 1.0


def test_mass_deep_resale_is_credible():
    c = assess("The North Face", "eBay", "new", 55.0, "new")
    assert not c.implausible


def test_no_discount_or_used_not_implausible():
    assert assess("Peak Performance", "eBay", "new", None, "new").implausible is False
    assert assess("Peak Performance", "eBay", "used", 60.0, "used").implausible is False


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
