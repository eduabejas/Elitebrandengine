"""Unit tests for the eBay Browse connector — fully offline (HTTP is stubbed).

Covers the parts that matter for a marketplace source: condition mapping (so a
used/refurbished listing can never masquerade as genuine new), per-marketplace
region/currency tagging, match-score gating, token caching and 401 re-auth.

Runnable with pytest, or directly: ``python -m tests.test_ebay``.
"""

from __future__ import annotations

import os

import requests

import engine.http as http
from engine.config import DEFAULTS, Config, _deep_merge
from engine.connectors.ebay import EbayConnector, map_condition, _diagnose_auth_failure
from engine.models import WatchItem


class _Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, ""

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class _FakeHttp:
    """Patch engine.http.get/post; record calls; script GET responses."""

    def __init__(self, get_responses, token_status=200):
        self._get_responses = list(get_responses)   # one _Resp per GET call
        self._token_status = token_status
        self.calls: list[tuple] = []

    def __enter__(self):
        self._orig = (http.get, http.post)
        http.get = self._get
        http.post = self._post
        return self

    def __exit__(self, *exc):
        http.get, http.post = self._orig
        return False

    def _post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if self._token_status != 200:
            return _Resp({"error": "invalid_client"}, status=self._token_status)
        return _Resp({"access_token": "TOK", "expires_in": 7200})

    def _get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        idx = sum(1 for c in self.calls if c[0] == "GET") - 1
        return self._get_responses[min(idx, len(self._get_responses) - 1)]

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]

    def gets(self):
        return [c for c in self.calls if c[0] == "GET"]


def _cfg(**detection) -> Config:
    return Config(raw=_deep_merge(DEFAULTS, {"detection": detection}))


def _conn(cfg, **settings) -> EbayConnector:
    os.environ["EBAY_CLIENT_ID"] = "id"
    os.environ["EBAY_CLIENT_SECRET"] = "secret"
    return EbayConnector(cfg, {"enabled": True, **settings})


def _summary(title, value, cid=None, cond=None, currency=None, **extra):
    price = {"value": value}
    if currency:
        price["currency"] = currency
    it = {"title": title, "price": price, "itemWebUrl": "https://ebay/x"}
    if cid is not None:
        it["conditionId"] = cid
    if cond is not None:
        it["condition"] = cond
    it.update(extra)
    return it


def _search_resp(summaries, status=200):
    return _Resp({"itemSummaries": summaries}, status=status)


# --------------------------------------------------------------------------- #
def test_map_condition_all_buckets():
    assert map_condition({"conditionId": "1000"}) == "new"
    assert map_condition({"conditionId": "2000"}) == "refurbished"   # Certified
    assert map_condition({"conditionId": "2500"}) == "refurbished"   # Seller refurb
    assert map_condition({"conditionId": "3000"}) == "used"
    assert map_condition({"conditionId": "1500"}) == "used"          # "New other"
    assert map_condition({"conditionId": "7000"}) == "used"          # for parts
    # Text fallback when no id:
    assert map_condition({"condition": "New"}) == "new"
    assert map_condition({"condition": "Certified - Refurbished"}) == "refurbished"
    assert map_condition({"condition": "Seller Refurbished"}) == "refurbished"
    assert map_condition({"condition": "Used"}) == "used"
    assert map_condition({}) == "new"


def test_search_maps_conditions_region_currency_and_listprice():
    cfg = _cfg(min_match_score=0.4)
    conn = _conn(cfg, marketplace="EBAY_US")
    w = WatchItem(id="arc", brand="Arc'teryx", name="Beta AR Jacket")
    summaries = [
        _summary("Arc'teryx Beta AR Jacket Men's Medium Black", "365.79",
                 cid="1000", cond="New", currency="USD",
                 marketingPrice={"originalPrice": {"value": "600.00"}},
                 seller={"username": "gearshop"},
                 image={"imageUrl": "http://img/1.jpg"},
                 localizedAspects=[{"name": "Size", "value": "M"},
                                   {"name": "Color", "value": "Black"}]),
        _summary("Arc'teryx Beta AR Jacket Large Used", "210.00", cid="3000", cond="Used"),
        _summary("Arc'teryx Beta AR Jacket Certified Refurbished", "250.00",
                 cid="2000", cond="Certified - Refurbished"),
        _summary("Arc'teryx Beta AR Jacket New Other In Box", "300.00",
                 cid="1500", cond="New other (see details)"),
        _summary("Random Unrelated Trekking Poles Aluminum Pair", "20.00", cid="1000"),
    ]
    with _FakeHttp([_search_resp(summaries)]) as fake:
        offers = conn.search(w)

    conds = {o.title.split()[-1] if False else o.condition for o in offers}
    assert len(offers) == 4                       # unrelated poles filtered by score
    by_price = {round(o.price): o for o in offers}
    new = by_price[366]
    assert new.condition == "new" and new.region == "US" and new.currency == "USD"
    assert new.list_price == 600.0 and new.size == "M" and new.color == "black"
    assert new.seller == "gearshop" and new.availability == "in_stock"
    assert by_price[210].condition == "used"
    assert by_price[250].condition == "refurbished"
    assert by_price[300].condition == "used"      # "New other" is NOT genuine new
    assert conds == {"new", "used", "refurbished"}
    # FIXED_PRICE filter + correct marketplace header were sent.
    get = fake.gets()[0][2]
    assert get["params"]["filter"] == "buyingOptions:{FIXED_PRICE}"
    assert get["headers"]["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"


def test_expanded_scope_queries_multiple_marketplaces():
    cfg = Config(raw=_deep_merge(DEFAULTS, {"search": {"scope": "expanded"},
                                            "detection": {"min_match_score": 0.4}}))
    conn = _conn(cfg)   # no explicit marketplace => scope-driven
    assert conn._marketplaces() == ["EBAY_US", "EBAY_GB", "EBAY_DE", "EBAY_CA"]


def test_marketplace_region_and_currency_fallback():
    cfg = _cfg(min_match_score=0.4)
    conn = _conn(cfg, marketplaces=["EBAY_DE"])
    w = WatchItem(id="rab", brand="Rab", name="Microlight Alpine")
    # No currency in the price => falls back to the marketplace default (EUR).
    summaries = [_summary("Rab Microlight Alpine Down Jacket Medium", "180.00",
                          cid="1000", cond="New")]
    with _FakeHttp([_search_resp(summaries)]):
        offers = conn.search(w)
    assert len(offers) == 1
    assert offers[0].region == "EU" and offers[0].currency == "EUR"


def test_token_is_cached_across_searches():
    cfg = _cfg(min_match_score=0.4)
    conn = _conn(cfg, marketplace="EBAY_US")
    w = WatchItem(id="x", brand="Rab", name="Microlight")
    resp = _search_resp([])
    with _FakeHttp([resp, resp]) as fake:
        conn.search(w)
        conn.search(w)
    assert len(fake.posts()) == 1        # one token fetch, reused


def test_reauth_on_401():
    cfg = _cfg(min_match_score=0.4)
    conn = _conn(cfg, marketplace="EBAY_US")
    w = WatchItem(id="x", brand="Rab", name="Microlight Alpine")
    ok = _search_resp([_summary("Rab Microlight Alpine Jacket M", "150.00", cid="1000")])
    with _FakeHttp([_search_resp([], status=401), ok]) as fake:
        offers = conn.search(w)
    assert len(offers) == 1              # recovered after re-auth
    assert len(fake.posts()) == 2        # initial token + forced re-auth
    assert len(fake.gets()) == 2         # 401 then success


def test_diagnose_detects_sandbox_app_id():
    resp = _Resp({"error": "invalid_client", "error_description": "client authentication failed"}, status=401)
    msg = _diagnose_auth_failure(resp, "MyCo-MyApp-SBX-1a2b3c4d5-6e7f8g9h")
    assert "SANDBOX" in msg and "-SBX-" in msg
    assert "eBay dijo:" in msg and "client authentication failed" in msg


def test_diagnose_production_id_points_at_secret_not_id():
    resp = _Resp({"error": "invalid_client"}, status=401)
    msg = _diagnose_auth_failure(resp, "MyCo-MyApp-PRD-1a2b3c4d5-6e7f8g9h")
    assert "-PRD-" in msg and "EBAY_CLIENT_SECRET" in msg


def test_diagnose_unrecognized_id_shape():
    resp = _Resp({"error": "invalid_client"}, status=401)
    msg = _diagnose_auth_failure(resp, "not-a-real-app-id")
    assert "valor equivocado" in msg


def test_diagnose_falls_back_to_raw_text_without_json_body():
    resp = _Resp({}, status=401)
    resp.json = lambda: (_ for _ in ()).throw(ValueError("no json"))
    resp.text = "Unauthorized"
    msg = _diagnose_auth_failure(resp, "MyCo-MyApp-PRD-x")
    assert "Unauthorized" in msg


def test_auth_failure_trips_breaker_once_not_per_item():
    """Bad credentials must not re-hammer eBay's OAuth endpoint for all 22
    watch items — one rejection stops the source for the whole run."""
    cfg = _cfg(min_match_score=0.4)
    conn = _conn(cfg, marketplace="EBAY_US")
    w = WatchItem(id="x", brand="Rab", name="Microlight Alpine")
    with _FakeHttp([_search_resp([])], token_status=401) as fake:
        for _ in range(22):                      # simulate the full watchlist
            assert conn.search(w) == []
    assert len(fake.posts()) == 1                # exactly ONE token attempt
    assert len(fake.gets()) == 0                 # never reached the search API
    assert conn._auth_failed is True
    assert "invalid_client" in conn.status_note()  # eBay's own reason, not a guess


def test_transient_token_error_does_not_trip_breaker():
    """A 5xx is transient — the breaker must stay closed so a later run (or
    watch item) can still succeed once eBay recovers."""
    cfg = _cfg(min_match_score=0.4)
    conn = _conn(cfg, marketplace="EBAY_US")
    w = WatchItem(id="x", brand="Rab", name="Microlight Alpine")
    with _FakeHttp([_search_resp([])], token_status=503):
        conn.search(w)
    assert conn._auth_failed is False


def test_unavailable_without_credentials():
    os.environ.pop("EBAY_CLIENT_ID", None)
    os.environ.pop("EBAY_CLIENT_SECRET", None)
    conn = EbayConnector(_cfg(), {"enabled": True})
    assert conn.available() is False
    assert conn.search(WatchItem(id="x", brand="Rab", name="Microlight")) == []


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
