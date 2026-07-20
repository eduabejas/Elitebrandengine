"""Unit tests for deal detection.

Runnable with pytest, or directly: ``python -m tests.test_dealdetector``.
"""

from __future__ import annotations

from datetime import date

from engine.config import DEFAULTS, Config
from engine.dealdetector import detect_deals
from engine.models import Offer, PricePoint, WatchItem, now_iso


def _cfg() -> Config:
    return Config(raw=DEFAULTS)   # hermetic: min_discount 15, min_history 4


def _offer(watch_id, price, **kw) -> Offer:
    base = dict(source="eBay", title="t", url="https://x", price=price)
    base.update(kw)
    return Offer(watch_id=watch_id, **base)


def test_target_price_hit():
    w = WatchItem(id="a", brand="Patagonia", name="Nano Puff", target_price=150.0)
    offers = [_offer("a", 140.0, size="M")]
    active, new = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert len(active) == 1
    assert "objetivo" in active[0].reason.lower()
    assert active[0].tier in ("target", "good", "great", "excellent")
    assert len(new) == 1


def test_list_price_discount():
    w = WatchItem(id="b", brand="Rab", name="Microlight")   # no target
    offers = [_offer("b", 160.0, list_price=250.0, size="L")]  # 36% off
    active, _ = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert len(active) == 1
    assert active[0].discount_pct and active[0].discount_pct >= 15


def test_below_threshold_is_not_a_deal():
    w = WatchItem(id="c", brand="Rab", name="Microlight")
    offers = [_offer("c", 240.0, list_price=250.0)]           # only 4% off
    active, _ = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert active == []


def test_size_filter_excludes():
    w = WatchItem(id="d", brand="Lowa", name="Renegade", target_price=200.0,
                  sizes=["US 10"])
    offers = [_offer("d", 150.0, size="US 11")]              # wrong size
    active, _ = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert active == []


def test_ledger_dedupe():
    w = WatchItem(id="e", brand="Osprey", name="Atmos", target_price=220.0)
    offers = [_offer("e", 200.0, size="65L")]
    active, new = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert len(new) == 1
    # feed the emitted key back into the ledger => no longer "new"
    ledger = {new[0].key: now_iso()}
    active2, new2 = detect_deals(_cfg(), w, offers, history=[], ledger=ledger)
    assert len(active2) == 1 and new2 == []


def test_new_historical_low():
    w = WatchItem(id="f", brand="Deuter", name="Aircontact")   # no target
    hist = [PricePoint(ts=now_iso(), source="eBay", price=p) for p in
            (210, 205, 208, 212)]                              # 4 points
    offers = [_offer("f", 150.0, size="70L")]                  # new low
    active, _ = detect_deals(_cfg(), w, offers, history=hist, ledger={})
    assert len(active) == 1
    assert "lowest" in active[0].reason.lower() or (active[0].discount_pct or 0) >= 15


# --- v2: false-positive guards & seasonality ------------------------------- #
def test_suspect_discount_dropped_when_match_uncertain():
    w = WatchItem(id="s", brand="Rab", name="Microlight", msrp=300.0)
    offers = [_offer("s", 80.0, size="M", match_score=0.6)]   # 73% off, unsure
    active, _ = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert active == []                                        # dropped, no false alarm


def test_suspect_discount_kept_but_flagged_when_match_certain():
    w = WatchItem(id="s2", brand="Rab", name="Microlight", msrp=300.0)
    offers = [_offer("s2", 80.0, size="M", match_score=0.96)]
    active, _ = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert len(active) == 1 and active[0].suspect and active[0].tier == "suspect"


def test_used_offer_excluded_by_default():
    w = WatchItem(id="u", brand="Rab", name="Microlight", msrp=300.0)
    offers = [_offer("u", 150.0, size="M", condition="used", match_score=1.0)]  # 50% off
    active, _ = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert active == []


def test_out_of_stock_excluded():
    w = WatchItem(id="o", brand="Rab", name="Microlight", msrp=300.0)
    offers = [_offer("o", 150.0, size="M", availability="out_of_stock")]
    active, _ = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert active == []


def test_fake_inflated_list_price_is_ignored():
    # Real regular price ~200; a fake "$500 was" must not create a 62% deal.
    w = WatchItem(id="f", brand="Rab", name="Microlight")
    hist = [PricePoint(ts=now_iso(), source="eBay", price=p) for p in (200, 200, 201, 199)]
    offers = [_offer("f", 190.0, size="M", list_price=500.0)]  # only ~5% off real
    active, _ = detect_deals(_cfg(), w, offers, history=hist, ledger={})
    assert active == []


def test_offseason_winter_gear_in_summer_is_boosted():
    summer = date(2026, 7, 15)
    w_winter = WatchItem(id="w", brand="Rab", name="Down Jacket",
                         category="Down Jacket", target_price=200.0)
    w_3season = WatchItem(id="a", brand="Osprey", name="Atmos",
                          category="Backpack", target_price=200.0)
    aw, _ = detect_deals(_cfg(), w_winter, [_offer("w", 150.0, size="M", match_score=1.0)],
                         history=[], ledger={}, today=summer)
    a3, _ = detect_deals(_cfg(), w_3season, [_offer("a", 150.0, size="M", match_score=1.0)],
                         history=[], ledger={}, today=summer)
    assert aw[0].seasonal is True and a3[0].seasonal is False
    assert aw[0].score > a3[0].score


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
