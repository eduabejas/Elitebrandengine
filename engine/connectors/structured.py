"""Structured-data connector — read the price the retailer itself publishes.

Most retailers embed **schema.org Product/Offer JSON-LD** in their product pages
(for Google/SEO): name, brand, GTIN/SKU, price, currency and availability. That
is *authoritative* data straight from the merchant — no scraping of search
results, no community rumor, no fake-news risk. This connector fetches the
product URLs the operator lists on a watch item (``urls``), politely (robots.txt
+ rate limits, backing off on any challenge), and parses that JSON-LD.

It is **off by default** and only acts on watch items that have ``urls``.
"""

from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import urlparse

from ..models import Offer, WatchItem
from ..normalize import canonical_brand, match_score, normalize_color, normalize_size
from .polite_html import PoliteHtmlConnector

_LD_BLOCK = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _availability(raw) -> str:
    s = str(raw or "").lower()
    if "outofstock" in s or "soldout" in s or "discontinued" in s:
        return "out_of_stock"
    if "instock" in s or "onlineonly" in s or "limitedavailability" in s:
        return "in_stock"
    return "unknown"


def _first(x):
    return x[0] if isinstance(x, list) and x else x


def _type_matches(node: dict, wanted: str) -> bool:
    t = node.get("@type")
    if isinstance(t, list):
        return any(str(x).lower() == wanted for x in t)
    return str(t or "").lower() == wanted


def _iter_nodes(data):
    """Walk a parsed JSON-LD document yielding every dict node once (handles
    arrays, @graph, and nesting; dedupes shared references)."""
    stack = [data]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, dict):
            yield node
            for v in node.values():
                if isinstance(v, (list, dict)):
                    stack.append(v)
        elif isinstance(node, list):
            for v in node:
                if isinstance(v, (list, dict)):
                    stack.append(v)


def _offers_from_product(product: dict) -> list[dict]:
    name = product.get("name")
    brand = product.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    gtin = (product.get("gtin13") or product.get("gtin12") or product.get("gtin")
            or product.get("mpn"))
    sku = product.get("sku")
    image = _first(product.get("image"))
    if isinstance(image, dict):
        image = image.get("url")

    out: list[dict] = []
    offers = product.get("offers")
    for off in (offers if isinstance(offers, list) else [offers] if offers else []):
        if not isinstance(off, dict):
            continue
        price = off.get("price") or off.get("lowPrice")  # AggregateOffer -> lowPrice
        if price is None:
            continue
        try:
            price = float(str(price).replace(",", ""))
        except ValueError:
            continue
        out.append({
            "name": name, "brand": brand, "gtin": gtin, "sku": sku, "image": image,
            "price": price,
            "currency": off.get("priceCurrency", "USD"),
            "availability": _availability(off.get("availability")),
            "url": off.get("url"),
        })
    return out


def extract_offers_from_jsonld(html: str) -> list[dict]:
    """Extract normalised offer dicts from every JSON-LD Product in ``html``."""
    results: list[dict] = []
    for block in _LD_BLOCK.findall(html or ""):
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _iter_nodes(data):
            if isinstance(node, dict) and _type_matches(node, "product"):
                results.extend(_offers_from_product(node))
    return results


def _region_from_url(url: Optional[str]) -> str:
    host = urlparse(url or "").netloc.lower()
    eu_tlds = (".eu", ".de", ".co.uk", ".uk", ".fr", ".it", ".es", ".se", ".no",
               ".nl", ".ch", ".at", ".dk", ".fi")
    if any(host.endswith(t) for t in eu_tlds):
        return "EU"
    if host.endswith(".ca"):
        return "CA"
    return "US"


def _source_label(url: Optional[str]) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host or "structured"


class StructuredDataConnector(PoliteHtmlConnector):
    name = "StructuredData"

    def available(self) -> bool:
        return True  # acts only on watch items that provide `urls`

    def search(self, watch: WatchItem) -> list[Offer]:
        urls = list(getattr(watch, "urls", []) or [])
        if not urls:
            return []
        min_score = float(self.cfg.get("detection.min_match_score", 0.6))
        offers: list[Offer] = []
        for url in urls:
            try:
                html = self.fetch(url)  # polite: robots.txt + rate limit + back-off
            except Exception as exc:  # noqa: BLE001 - BlockedError, network, etc.
                print(f"[StructuredData] skip {url}: {exc}")
                continue
            for raw in extract_offers_from_jsonld(html):
                title = raw.get("name") or watch.name
                score = match_score(watch, title, raw.get("brand"))
                if score < min_score:
                    continue
                offers.append(Offer(
                    watch_id=watch.id,
                    source=_source_label(raw.get("url") or url),
                    title=title,
                    url=raw.get("url") or url,
                    price=raw["price"],
                    currency=raw.get("currency", watch.currency),
                    size=normalize_size(raw.get("size")) if raw.get("size") else None,
                    color=normalize_color(raw.get("color")) if raw.get("color") else None,
                    condition="new",
                    region=_region_from_url(raw.get("url") or url),
                    availability=raw.get("availability", "unknown"),
                    seller=_source_label(raw.get("url") or url),
                    image=raw.get("image"),
                    match_score=score,
                ))
        return offers
