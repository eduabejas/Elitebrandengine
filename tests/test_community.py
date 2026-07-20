"""Unit tests for the cautious community-signal handling.

Runnable with pytest, or directly: ``python -m tests.test_community``.
"""

from __future__ import annotations

from engine.community import (
    CommunitySignal,
    corroborate,
    corroborated_leads,
    match_signal,
    source_trust,
)
from engine.models import Offer, WatchItem

RATES = {"USD": 1.0}
WATCH = [WatchItem(id="beta", brand="Arc'teryx", name="Beta AR Jacket")]


def _offer(price):
    return Offer(watch_id="beta", source="REI Co-op", title="Arc'teryx Beta AR",
                 url="https://x", price=price)


def test_source_trust_defaults_low():
    assert source_trust("reddit:ULgeartrade") == 0.3
    assert source_trust("trusted", {"trusted": 0.9}) == 0.9


def test_match_signal():
    sig = CommunitySignal(source="reddit", text="Arc'teryx Beta AR Jacket 40% off!",
                          brand="Arc'teryx")
    w, s = match_signal(sig, WATCH)
    assert w is not None and w.id == "beta"


def test_corroborated_when_real_offer_backs_claim():
    sig = CommunitySignal(source="reddit", text="Beta AR", claimed_price=200.0)
    corro = corroborate(sig, [_offer(190.0)], rates=RATES, base="USD")
    assert corro is not None and corro.price == 190.0


def test_unbacked_claim_is_discarded():
    # Claims $120 but the cheapest real offer is $260 -> fake/stale -> None.
    sig = CommunitySignal(source="reddit", text="Beta AR", claimed_price=120.0)
    assert corroborate(sig, [_offer(260.0)], rates=RATES, base="USD") is None


def test_no_claim_uses_real_offer():
    sig = CommunitySignal(source="reddit", text="Beta AR")   # no price claimed
    corro = corroborate(sig, [_offer(250.0)], rates=RATES, base="USD")
    assert corro is not None and corro.price == 250.0


def test_corroborated_leads_filters_fakes():
    real = CommunitySignal(source="reddit:ULgeartrade", text="Arc'teryx Beta AR Jacket",
                           brand="Arc'teryx", claimed_price=300.0)
    fake = CommunitySignal(source="reddit:sketchy", text="Arc'teryx Beta AR Jacket",
                           brand="Arc'teryx", claimed_price=50.0)  # unbacked
    observed = {"beta": [_offer(280.0)]}
    leads = corroborated_leads([real, fake], WATCH, observed, rates=RATES, base="USD")
    assert len(leads) == 1 and leads[0]["source"] == "reddit:ULgeartrade"
    assert leads[0]["trust"] == 0.3


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
