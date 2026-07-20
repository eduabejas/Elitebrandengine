"""Unit tests for the product identity graph (channels, regions, lineage).

Runnable with pytest, or directly: ``python -m tests.test_identity``.
"""

from __future__ import annotations

from engine.identity import (
    channel_region_summary,
    classify_channel,
    enrich_offer,
    home_region,
    home_region_advantage,
    regions_for_scope,
    source_region,
)
from engine.models import Offer, WatchItem
from engine.normalize import match_score


def _offer(source, price, region="US", condition="new", title="x"):
    return Offer(watch_id="w", source=source, title=title, url="https://x",
                 price=price, region=region, condition=condition)


def test_classify_channel():
    assert classify_channel("REI Re/Supply (outlet)", "jacket") == "outlet"
    assert classify_channel("TNF", "Renewed down jacket") == "refurbished"
    assert classify_channel("eBay", "used arcteryx jacket") == "used"
    assert classify_channel("eBay", "arcteryx jacket", condition="used") == "used"
    assert classify_channel("REI Co-op", "brand new jacket") == "new"


def test_home_region():
    assert home_region("Peak Performance") == "EU"
    assert home_region("Helly Hansen") == "EU"
    assert home_region("Arc'teryx") == "CA"
    assert home_region("Patagonia") == "US"
    assert home_region("Patagonia", explicit="EU") == "EU"     # override


def test_source_region():
    assert source_region("Bergfreunde (EU)") == "EU"
    assert source_region("MEC (CA)") == "CA"
    assert source_region("REI Co-op") == "US"
    assert source_region("Some Shop (EU)") == "EU"             # suffix heuristic


def test_regions_for_scope():
    assert regions_for_scope("standard") == {"US"}
    assert regions_for_scope("expanded") == {"US", "CA", "EU"}


def test_enrich_offer_tags_channel_and_region():
    o = _offer("Bergfreunde (EU)", 100, region="US")   # region not set by connector
    enrich_offer(o)
    assert o.region == "EU" and o.channel == "new"
    o2 = _offer("REI Re/Supply (outlet)", 80)
    enrich_offer(o2)
    assert o2.channel == "outlet"


def test_home_region_advantage():
    w = WatchItem(id="w", brand="Rab", name="Microlight")      # EU brand
    offers = [_offer("REI Co-op", 200, "US"), _offer("Bergfreunde (EU)", 150, "EU")]
    adv, hr = home_region_advantage(w, offers)
    assert adv is True and hr == "EU"
    # US brand: no home advantage concept
    w2 = WatchItem(id="w2", brand="Patagonia", name="Nano Puff")
    assert home_region_advantage(w2, offers)[0] is False


def test_lineage_matching():
    w = WatchItem(id="w", brand="Arc'teryx", name="Beta AR Jacket",
                  lineage=["beta ar 2023"])
    # a previous-season title resolves via the lineage alias
    assert match_score(w, "Arc'teryx Beta AR 2023 Men's Gore-Tex Black") >= 0.6
    # the current name still matches
    assert match_score(w, "Arc'teryx Beta AR Jacket Black") >= 0.6


def test_channel_region_summary():
    offers = [_offer("REI Co-op", 200, "US"), _offer("Bergfreunde (EU)", 150, "EU"),
              _offer("REI Re/Supply (outlet)", 120, "US", title="outlet")]
    for o in offers:
        enrich_offer(o)
    s = channel_region_summary(offers)
    assert s["by_region"]["EU"] == 150 and s["by_region"]["US"] == 120


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
