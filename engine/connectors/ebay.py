"""eBay connector — official **Browse API** (legitimate, free).

Auth is the OAuth *client credentials* grant: your app's Client ID/Secret are
exchanged for an application token, which authorises keyword search across live
eBay listings. No scraping, no CAPTCHAs.

Setup:
    1. Create a free app at https://developer.ebay.com/ (Application keysets).
    2. Put the keys in GitHub Actions secrets / your env:
         EBAY_CLIENT_ID, EBAY_CLIENT_SECRET
    3. In config.yml set sources.ebay.enabled: true

eBay is a **marketplace**, so condition is first-class here: each listing is
mapped to new / used / refurbished so the credibility+brain layer can flag (and
by default hide) the illusions we care about — e.g. a cult brand shown "−50%
new" that is really used. Region + currency are tagged per marketplace so the
expanded scope (US + Canada + Europe) surfaces home-market deals correctly.

Docs: https://developer.ebay.com/api-docs/buy/browse/overview.html
"""

from __future__ import annotations

import base64
import os
import threading
import time
from typing import Optional

import requests

from .. import http
from ..models import Offer, WatchItem
from ..normalize import (
    canonical_brand,
    extract_color_from_text,
    extract_size_from_text,
    match_score,
    normalize_color,
    normalize_size,
)
from .base import Connector

_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_SCOPE = "https://api.ebay.com/oauth/api_scope"

# eBay conditionId -> our canonical condition. Anything that is not pristine
# retail-new (incl. "New other", "Like new", "For parts") is deliberately NOT
# called "new", so the cautious brain never mistakes it for a genuine new deal.
_REFURB_IDS = {"2000", "2010", "2020", "2030", "2500"}
_NEW_IDS = {"1000"}

# Marketplace -> region bucket (US / CA / EU) used by scope filtering and the
# home-region-advantage logic.
_MARKET_REGION = {
    "EBAY_US": "US", "EBAY_CA": "CA",
    "EBAY_GB": "EU", "EBAY_DE": "EU", "EBAY_FR": "EU", "EBAY_IT": "EU",
    "EBAY_ES": "EU", "EBAY_AT": "EU", "EBAY_IE": "EU", "EBAY_NL": "EU",
    "EBAY_BE": "EU", "EBAY_PL": "EU",
}
# Default listing currency per marketplace (fallback only — the API states it).
_MARKET_CURRENCY = {
    "EBAY_US": "USD", "EBAY_CA": "CAD", "EBAY_GB": "GBP",
    "EBAY_DE": "EUR", "EBAY_FR": "EUR", "EBAY_IT": "EUR", "EBAY_ES": "EUR",
    "EBAY_AT": "EUR", "EBAY_IE": "EUR", "EBAY_NL": "EUR", "EBAY_BE": "EUR",
    "EBAY_PL": "PLN",
}
# Which marketplaces the expanded scope hits by default. Kept to currencies the
# engine has FX rates for (USD/GBP/EUR/CAD) so prices normalise correctly.
_EXPANDED_DEFAULT = ["EBAY_US", "EBAY_GB", "EBAY_DE", "EBAY_CA"]


def map_condition(item: dict) -> str:
    """eBay condition/conditionId -> 'new' | 'used' | 'refurbished'."""
    cid = str(item.get("conditionId") or "").strip()
    if cid in _NEW_IDS:
        return "new"
    if cid in _REFURB_IDS:
        return "refurbished"
    if cid:                      # any other known id (incl. 1500 "New other")
        return "used"
    text = (item.get("condition") or "").strip().lower()
    if not text:
        return "new"             # Browse always states it; treat absence as new
    if "refurb" in text or "renewed" in text:
        return "refurbished"
    if text in ("new", "brand new"):
        return "new"
    return "used"


class EbayConnector(Connector):
    name = "eBay"

    def __init__(self, cfg, settings):
        super().__init__(cfg, settings)
        self.client_id = os.getenv("EBAY_CLIENT_ID", "")
        self.client_secret = os.getenv("EBAY_CLIENT_SECRET", "")
        self.limit = int(self.settings.get("limit", 8))
        self._token: Optional[str] = None
        self._token_exp = 0.0
        self.min_interval = float(self.settings.get("min_interval", 0.25))
        self.attempts = int(self.settings.get("attempts", 3))
        self._token_lock = threading.Lock()

    def available(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _marketplaces(self) -> list[str]:
        """One marketplace for standard scope; US+EU+CA for expanded. An
        explicit `marketplaces` list in config overrides both."""
        explicit = self.settings.get("marketplaces")
        if explicit:
            return list(explicit)
        scope = (self.cfg.get("search.scope", "standard") or "standard").lower()
        if scope == "expanded":
            return list(self.settings.get("expanded_marketplaces", _EXPANDED_DEFAULT))
        return [self.settings.get("marketplace", "EBAY_US")]

    # ------------------------------------------------------------------ #
    def _get_token(self, force: bool = False) -> Optional[str]:
        if not force and self._token and time.time() < self._token_exp - 60:
            return self._token
        with self._token_lock:
            if not force and self._token and time.time() < self._token_exp - 60:
                return self._token  # another thread refreshed it
            return self._refresh_token()

    def _refresh_token(self) -> Optional[str]:
        if not (self.client_id and self.client_secret):
            return None                 # no creds => never hit the network
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        try:
            r = http.post(
                _OAUTH_URL,
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials", "scope": _SCOPE},
                host="api.ebay.com", min_interval=self.min_interval,
                attempts=self.attempts, timeout=20,
            )
            r.raise_for_status()
            body = r.json()
            self._token = body["access_token"]
            self._token_exp = time.time() + int(body.get("expires_in", 7200))
            return self._token
        except (requests.RequestException, http.HttpError, KeyError, ValueError) as exc:
            print(f"[eBay] token error: {exc}")
            self._token, self._token_exp = None, 0.0
            return None

    def _query(self, watch: WatchItem) -> str:
        brand = canonical_brand(watch.brand) or watch.brand
        extra = " ".join(watch.keywords) if watch.keywords else ""
        return " ".join(p for p in (brand, watch.name, extra) if p).strip()

    def search(self, watch: WatchItem) -> list[Offer]:
        token = self._get_token()
        if not token:
            return []
        min_score = float(self.cfg.get("detection.min_match_score", 0.6))
        offers: list[Offer] = []
        for mp in self._marketplaces():
            offers.extend(self._search_one(watch, mp, min_score))
        return offers

    def _search_one(self, watch: WatchItem, marketplace: str,
                    min_score: float, _reauthed: bool = False) -> list[Offer]:
        token = self._get_token()
        if not token:
            return []
        region = _MARKET_REGION.get(marketplace, "US")
        currency = _MARKET_CURRENCY.get(marketplace, watch.currency)
        params = {
            "q": self._query(watch),
            "limit": str(self.limit),
            "filter": "buyingOptions:{FIXED_PRICE}",
        }
        if watch.upc:
            params["gtin"] = watch.upc
        try:
            r = http.get(
                _SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": marketplace,
                    "Content-Type": "application/json",
                },
                params=params,
                host="api.ebay.com", min_interval=self.min_interval,
                attempts=self.attempts, timeout=25,
            )
            if r.status_code == 401 and not _reauthed:
                self._get_token(force=True)     # token expired mid-run
                return self._search_one(watch, marketplace, min_score, _reauthed=True)
            r.raise_for_status()
            summaries = r.json().get("itemSummaries", []) or []
        except (requests.RequestException, http.HttpError, ValueError) as exc:
            print(f"[eBay] search error for {watch.id} @ {marketplace}: {exc}")
            return []

        offers: list[Offer] = []
        for it in summaries:
            offer = self._to_offer(watch, it, marketplace, region, currency, min_score)
            if offer is not None:
                offers.append(offer)
        return offers

    def _to_offer(self, watch: WatchItem, it: dict, marketplace: str,
                  region: str, currency: str, min_score: float) -> Optional[Offer]:
        title = it.get("title", "")
        price = it.get("price", {}) or {}
        value = price.get("value")
        if value is None:
            return None
        try:
            price_val = float(value)
        except (TypeError, ValueError):
            return None
        score = match_score(watch, title)
        if score < min_score:
            return None
        size, color = _guess_size_color(it, title)
        marketing = it.get("marketingPrice", {}) or {}
        list_price = (marketing.get("originalPrice", {}) or {}).get("value")
        try:
            list_val = float(list_price) if list_price else None
        except (TypeError, ValueError):
            list_val = None
        return Offer(
            watch_id=watch.id,
            source=self.name,
            title=title,
            url=it.get("itemWebUrl", ""),
            price=price_val,
            currency=price.get("currency") or currency,
            size=size,
            color=color,
            condition=map_condition(it),
            region=region,
            availability="in_stock",
            seller=(it.get("seller") or {}).get("username"),
            image=(it.get("image") or {}).get("imageUrl"),
            list_price=list_val,
            match_score=score,
        )


def _guess_size_color(item: dict, title: str):
    """Best-effort variant extraction from item aspects or the title."""
    size = color = None
    for asp in item.get("localizedAspects", []) or []:
        name = (asp.get("name") or "").lower()
        val = asp.get("value")
        if not val:
            continue
        if "size" in name and size is None:
            size = normalize_size(val)
        elif ("color" in name or "colour" in name) and color is None:
            color = normalize_color(val)
    if size is None:
        size = extract_size_from_text(title)  # only confident patterns
    if color is None:
        color = extract_color_from_text(title)
    return size, color
