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
    # authorized retailer -> 36% is credible for a cult brand (ceiling ~40%)
    offers = [_offer("b", 160.0, list_price=250.0, size="L", source="Backcountry")]
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


def test_effective_stacking_turns_sub_threshold_sale_into_a_deal():
    w = WatchItem(id="c", brand="Rab", name="Microlight", msrp=200.0)
    offers = [_offer("c", 180.0, size="M", source="Backcountry", match_score=1.0)]
    # Sticker is only 10% off (< 15% threshold): not a deal on its own.
    a0, _ = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert a0 == []
    # Add a 15% coupon + 5% cashback + free shipping -> effective ~27% off = deal.
    promos = {
        "sources": {"Backcountry": {"shipping": {"free_over": 50, "flat": 0}, "cashback_pct": 0.05}},
        "coupons": [{"code": "TRAIL15", "source": "Backcountry", "type": "percent",
                     "value": 0.15, "min_subtotal": 0, "expires": "2099-01-01"}],
    }
    a1, _ = detect_deals(_cfg(), w, offers, history=[], ledger={}, promos=promos)
    assert len(a1) == 1
    assert a1[0].effective_discount_pct >= 15 and a1[0].coupon_code == "TRAIL15"
    assert a1[0].effective_price < 180 and a1[0].discount_pct == 10.0


def test_outlet_offer_counts_as_deal():
    w = WatchItem(id="ot", brand="Rab", name="Microlight", msrp=300.0)
    offers = [_offer("ot", 150.0, size="M", channel="outlet", match_score=1.0)]
    active, _ = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert len(active) == 1 and active[0].channel == "outlet" and not active[0].suspect


def test_home_region_advantage_marked_on_eu_offer():
    w = WatchItem(id="hr", brand="Rab", name="Microlight", msrp=300.0)  # EU brand
    offers = [_offer("hr", 220.0, size="M", region="US", source="REI Co-op", match_score=1.0),
              _offer("hr", 180.0, size="M", region="EU", source="Bergfreunde (EU)", match_score=1.0)]
    active, _ = detect_deals(_cfg(), w, offers, history=[], ledger={})
    eu = [a for a in active if a.region == "EU"]
    assert eu and eu[0].home_region_advantage is True


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


# --- the cautious brain: credibility + buy/wait/hold ----------------------- #
def test_cult_deep_discount_on_resale_is_suspect_and_hold():
    # THE benchmark to avoid: Peak Performance −50% "new" on eBay is not a real
    # opportunity — flag it, never present it as a buy.
    w = WatchItem(id="pp", brand="Peak Performance", name="Helium Down", msrp=300.0)
    offers = [_offer("pp", 150.0, size="M", source="eBay", match_score=1.0)]  # 50% off
    active, _ = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert active and active[0].suspect and active[0].recommendation == "hold"
    assert active[0].credibility < 1.0 and active[0].tier == "suspect"


def test_mass_brand_deep_discount_on_resale_is_credible():
    # A mass brand CAN legitimately be dumped cheap on resale by uninformed owners.
    w = WatchItem(id="tnf", brand="The North Face", name="Nuptse", msrp=300.0)
    offers = [_offer("tnf", 150.0, size="M", source="eBay", match_score=1.0)]  # 50% off
    active, _ = detect_deals(_cfg(), w, offers, history=[], ledger={})
    assert active and not active[0].suspect


def test_buy_at_historical_low():
    w = WatchItem(id="rl", brand="Rab", name="Microlight", msrp=300.0)
    hist = [PricePoint(ts=now_iso(), source="Backcountry", price=p) for p in (250, 255, 248, 252)]
    offers = [_offer("rl", 180.0, size="M", source="Backcountry", match_score=1.0)]  # new low
    active, _ = detect_deals(_cfg(), w, offers, history=hist, ledger={}, today=date(2026, 7, 20))
    assert active and active[0].recommendation == "buy"


def test_wait_when_price_is_mediocre_vs_history():
    w = WatchItem(id="rw", brand="Rab", name="Microlight", msrp=300.0)
    hist = [PricePoint(ts=now_iso(), source="Backcountry", price=p) for p in (140, 150, 145, 155)]
    offers = [_offer("rw", 200.0, size="M", source="Backcountry", match_score=1.0)]  # usually cheaper
    active, _ = detect_deals(_cfg(), w, offers, history=hist, ledger={}, today=date(2026, 7, 20))
    assert active and active[0].recommendation == "wait"


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
