"""Amazon connector — official **Product Advertising API 5.0** (SearchItems).

This is the legitimate way to read Amazon prices. It requires an approved
Amazon Associates account plus PA-API access, and requests are signed with AWS
Signature V4.

Setup (env / GitHub secrets):
    AMAZON_ACCESS_KEY, AMAZON_SECRET_KEY, AMAZON_PARTNER_TAG
Then in config.yml set sources.amazon.enabled: true

Docs: https://webservices.amazon.com/paapi5/documentation/

NOTE: signing is implemented per Amazon's documented SigV4 flow but should be
validated against your live keys the first time — failures here are caught and
logged, never fatal to the run.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
from typing import Optional

import requests

from ..models import Offer, WatchItem
from ..normalize import (
    canonical_brand,
    extract_color_from_text,
    extract_size_from_text,
    match_score,
)
from .base import Connector

_SERVICE = "ProductAdvertisingAPI"
_TARGET = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"
_RESOURCES = [
    "ItemInfo.Title",
    "ItemInfo.ByLineInfo",
    "Offers.Listings.Price",
    "Offers.Listings.Condition",
    "Images.Primary.Medium",
]
# marketplace host -> AWS region for PA-API
_REGION_BY_HOST = {
    "www.amazon.com": "us-east-1",
    "www.amazon.co.uk": "eu-west-1",
    "www.amazon.de": "eu-west-1",
    "www.amazon.co.jp": "us-west-2",
    "www.amazon.ca": "us-east-1",
    "www.amazon.com.au": "us-west-2",
}


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


class AmazonConnector(Connector):
    name = "Amazon"

    def __init__(self, cfg, settings):
        super().__init__(cfg, settings)
        self.access_key = os.getenv("AMAZON_ACCESS_KEY", "")
        self.secret_key = os.getenv("AMAZON_SECRET_KEY", "")
        self.partner_tag = os.getenv("AMAZON_PARTNER_TAG", "")
        self.marketplace = self.settings.get("marketplace", "www.amazon.com")
        self.host = self.settings.get("host", "webservices.amazon.com")
        self.region = self.settings.get("region") or _REGION_BY_HOST.get(
            self.marketplace, "us-east-1"
        )
        self.item_count = int(self.settings.get("item_count", 5))
        self.search_index = self.settings.get("search_index", "SportingGoods")

    def available(self) -> bool:
        return bool(self.access_key and self.secret_key and self.partner_tag)

    # ------------------------------------------------------------------ #
    def _signed_headers(self, payload: str) -> dict[str, str]:
        now = _dt.datetime.now(_dt.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        canonical_uri = "/paapi5/searchitems"
        canonical_headers = (
            f"content-encoding:amz-1.0\n"
            f"host:{self.host}\n"
            f"x-amz-date:{amz_date}\n"
            f"x-amz-target:{_TARGET}\n"
        )
        signed_headers = "content-encoding;host;x-amz-date;x-amz-target"
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = (
            f"POST\n{canonical_uri}\n\n{canonical_headers}\n"
            f"{signed_headers}\n{payload_hash}"
        )
        algorithm = "AWS4-HMAC-SHA256"
        scope = f"{date_stamp}/{self.region}/{_SERVICE}/aws4_request"
        string_to_sign = (
            f"{algorithm}\n{amz_date}\n{scope}\n"
            f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
        )
        k_date = _sign(("AWS4" + self.secret_key).encode("utf-8"), date_stamp)
        k_region = _sign(k_date, self.region)
        k_service = _sign(k_region, _SERVICE)
        k_signing = _sign(k_service, "aws4_request")
        signature = hmac.new(
            k_signing, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        authorization = (
            f"{algorithm} Credential={self.access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return {
            "content-encoding": "amz-1.0",
            "content-type": "application/json; charset=utf-8",
            "host": self.host,
            "x-amz-date": amz_date,
            "x-amz-target": _TARGET,
            "Authorization": authorization,
        }

    def search(self, watch: WatchItem) -> list[Offer]:
        brand = canonical_brand(watch.brand) or watch.brand
        keywords = " ".join(p for p in ([brand, watch.name] + watch.keywords) if p)
        payload = json.dumps(
            {
                "Keywords": keywords,
                "SearchIndex": self.search_index,
                "ItemCount": self.item_count,
                "PartnerTag": self.partner_tag,
                "PartnerType": "Associates",
                "Marketplace": self.marketplace,
                "Resources": _RESOURCES,
            }
        )
        try:
            r = requests.post(
                f"https://{self.host}/paapi5/searchitems",
                headers=self._signed_headers(payload),
                data=payload,
                timeout=25,
            )
            r.raise_for_status()
            items = (r.json().get("SearchResult") or {}).get("Items", []) or []
        except (requests.RequestException, ValueError) as exc:
            print(f"[Amazon] search error for {watch.id}: {exc}")
            return []

        min_score = float(self.cfg.get("detection.min_match_score", 0.6))
        offers: list[Offer] = []
        for it in items:
            title = (
                ((it.get("ItemInfo") or {}).get("Title") or {}).get("DisplayValue")
                or ""
            )
            if not title:
                continue
            listings = ((it.get("Offers") or {}).get("Listings") or [])
            if not listings:
                continue
            listing = listings[0]
            amount = ((listing.get("Price") or {}).get("Amount"))
            if amount is None:
                continue
            score = match_score(watch, title)
            if score < min_score:
                continue
            image = (
                ((it.get("Images") or {}).get("Primary") or {}).get("Medium") or {}
            ).get("URL")
            condition = (
                (listing.get("Condition") or {}).get("Value") or "new"
            ).lower()
            offers.append(
                Offer(
                    watch_id=watch.id,
                    source=self.name,
                    title=title,
                    url=it.get("DetailPageURL", ""),
                    price=float(amount),
                    currency=((listing.get("Price") or {}).get("Currency"))
                    or watch.currency,
                    size=extract_size_from_text(title),
                    color=extract_color_from_text(title),
                    condition=condition,
                    availability="in_stock",
                    seller="Amazon",
                    image=image,
                    match_score=score,
                )
            )
        return offers
