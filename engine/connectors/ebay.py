"""eBay connector — official **Browse API** (legitimate, free).

Auth is the OAuth *client credentials* grant: your app's Client ID/Secret are
exchanged for an application token, which authorises keyword search across live
eBay listings. No scraping, no CAPTCHAs.

Setup:
    1. Create a free app at https://developer.ebay.com/ (Application keysets).
    2. Put the keys in GitHub Actions secrets / your env:
         EBAY_CLIENT_ID, EBAY_CLIENT_SECRET
    3. In config.yml set sources.ebay.enabled: true

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


class EbayConnector(Connector):
    name = "eBay"

    def __init__(self, cfg, settings):
        super().__init__(cfg, settings)
        self.client_id = os.getenv("EBAY_CLIENT_ID", "")
        self.client_secret = os.getenv("EBAY_CLIENT_SECRET", "")
        self.marketplace = self.settings.get("marketplace", "EBAY_US")
        self.limit = int(self.settings.get("limit", 8))
        self._token: Optional[str] = None
        self._token_exp = 0.0
        self.min_interval = float(self.settings.get("min_interval", 0.25))
        self.attempts = int(self.settings.get("attempts", 3))
        self._token_lock = threading.Lock()

    def available(self) -> bool:
        return bool(self.client_id and self.client_secret)

    # ------------------------------------------------------------------ #
    def _get_token(self) -> Optional[str]:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        with self._token_lock:
            if self._token and time.time() < self._token_exp - 60:
                return self._token  # another thread refreshed it
            return self._refresh_token()

    def _refresh_token(self) -> Optional[str]:
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
                    "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
                    "Content-Type": "application/json",
                },
                params=params,
                host="api.ebay.com", min_interval=self.min_interval,
                attempts=self.attempts, timeout=25,
            )
            r.raise_for_status()
            summaries = r.json().get("itemSummaries", []) or []
        except (requests.RequestException, http.HttpError, ValueError) as exc:
            print(f"[eBay] search error for {watch.id}: {exc}")
            return []

        offers: list[Offer] = []
        for it in summaries:
            title = it.get("title", "")
            price = it.get("price", {}) or {}
            value = price.get("value")
            if value is None:
                continue
            score = match_score(watch, title)
            if score < min_score:
                continue
            size, color = _guess_size_color(it, title)
            marketing = it.get("marketingPrice", {}) or {}
            list_price = marketing.get("originalPrice", {}).get("value")
            offers.append(
                Offer(
                    watch_id=watch.id,
                    source=self.name,
                    title=title,
                    url=it.get("itemWebUrl", ""),
                    price=float(value),
                    currency=price.get("currency", watch.currency),
                    size=size,
                    color=color,
                    condition=(it.get("condition") or "new").lower(),
                    availability="in_stock",
                    seller=(it.get("seller") or {}).get("username"),
                    image=(it.get("image") or {}).get("imageUrl"),
                    list_price=float(list_price) if list_price else None,
                    match_score=score,
                )
            )
        return offers


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
