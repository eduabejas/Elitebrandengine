"""Affiliate datafeed connector — the legal backbone for REI, Backcountry,
Patagonia and brand DTC stores.

Affiliate networks (AvantLink, Impact, CJ, Sovrn) publish *product datafeeds*
— CSV/TSV/XML files listing every product with its brand, price, sale price,
buy URL and image — expressly so approved affiliates can build price-comparison
sites. This is exactly how legitimate deal engines get retailer pricing without
scraping or fighting anti-bot systems.

Configure one entry per feed in config.yml::

    sources:
      affiliate_feed:
        enabled: true
        feeds:
          - source: "REI Co-op"
            url: "https://datafeed.avantlink.com/....csv"   # or a local path
            format: csv            # csv | tsv | xml
            xml_item: "product"    # (xml only) repeating element name
            mapping:
              name: "Product Name"
              brand: "Brand"
              price: "Sale Price"
              list_price: "Retail Price"
              url: "Buy URL"
              image: "Image URL"
              size: "Size"
              color: "Color"
              upc: "UPC"

The connector downloads each feed once per run, keeps only rows for the
flagship brands, and matches them to watch items in memory.
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Optional

import requests

from ..config import ROOT
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


def _to_float(val) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip().replace("$", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


class AffiliateFeedConnector(Connector):
    name = "AffiliateFeed"

    def __init__(self, cfg, settings):
        super().__init__(cfg, settings)
        self.feeds = self.settings.get("feeds", []) or []
        # brand -> list[row], one index per feed, built lazily and cached.
        self._index: Optional[dict[int, dict[str, list[dict]]]] = None

    def available(self) -> bool:
        return bool(self.feeds)

    # ------------------------------------------------------------------ #
    def _read_raw(self, feed: dict) -> str:
        url = feed.get("url", "")
        if url.startswith("http://") or url.startswith("https://"):
            r = requests.get(url, timeout=60, headers={"User-Agent": "EliteBrandEngine/1.0"})
            r.raise_for_status()
            return r.text
        # treat as a local path (relative to repo root) — useful for fixtures
        p = Path(url)
        if not p.is_absolute():
            p = ROOT / url
        return p.read_text(encoding="utf-8")

    def _parse_rows(self, feed: dict) -> list[dict]:
        fmt = (feed.get("format") or "csv").lower()
        raw = self._read_raw(feed)
        if fmt in ("csv", "tsv"):
            delim = "\t" if fmt == "tsv" else ","
            reader = csv.DictReader(io.StringIO(raw), delimiter=delim)
            return [dict(r) for r in reader]
        if fmt == "xml":
            item_tag = feed.get("xml_item", "product")
            root = ET.fromstring(raw)
            rows = []
            for el in root.iter(item_tag):
                rows.append({child.tag: (child.text or "") for child in el})
            return rows
        raise ValueError(f"Unsupported feed format: {fmt}")

    def _build_index(self) -> dict[int, dict[str, list[dict]]]:
        index: dict[int, dict[str, list[dict]]] = {}
        for i, feed in enumerate(self.feeds):
            by_brand: dict[str, list[dict]] = defaultdict(list)
            try:
                rows = self._parse_rows(feed)
            except (requests.RequestException, OSError, ET.ParseError, ValueError) as exc:
                print(f"[AffiliateFeed] failed to load feed {feed.get('source')}: {exc}")
                index[i] = {}
                continue
            mapping = feed.get("mapping", {})
            for row in rows:
                brand_raw = row.get(mapping.get("brand", "brand"), "")
                brand_c = canonical_brand(brand_raw)
                if not brand_c:  # keep only flagship brands -> small & fast
                    continue
                by_brand[brand_c].append(row)
            index[i] = by_brand
            print(f"[AffiliateFeed] {feed.get('source')}: "
                  f"{sum(len(v) for v in by_brand.values())} flagship rows indexed")
        return index

    def _offer_from_row(self, watch: WatchItem, feed: dict, row: dict, score: float) -> Optional[Offer]:
        m = feed.get("mapping", {})
        price = _to_float(row.get(m.get("price", "price")))
        if price is None:
            return None
        list_price = _to_float(row.get(m.get("list_price", "list_price")))
        size_raw = row.get(m.get("size", "size"))
        color_raw = row.get(m.get("color", "color"))
        title = row.get(m.get("name", "name"), watch.name)
        return Offer(
            watch_id=watch.id,
            source=feed.get("source", self.name),
            title=title,
            url=row.get(m.get("url", "url"), ""),
            price=price,
            currency=watch.currency,
            size=normalize_size(size_raw) if size_raw else extract_size_from_text(title),
            color=normalize_color(color_raw) if color_raw else extract_color_from_text(title),
            condition="new",
            availability="in_stock",
            seller=feed.get("source", self.name),
            image=row.get(m.get("image", "image")),
            list_price=list_price if (list_price and list_price > price) else None,
            match_score=score,
        )

    def search(self, watch: WatchItem) -> list[Offer]:
        if self._index is None:
            self._index = self._build_index()
        brand_c = canonical_brand(watch.brand)
        if not brand_c:
            return []
        min_score = float(self.cfg.get("detection.min_match_score", 0.6))
        offers: list[Offer] = []
        for i, feed in enumerate(self.feeds):
            for row in self._index.get(i, {}).get(brand_c, []):
                title = row.get(feed.get("mapping", {}).get("name", "name"), "")
                score = match_score(watch, title, brand_c)
                if score < min_score:
                    continue
                offer = self._offer_from_row(watch, feed, row, score)
                if offer and offer.url:
                    offers.append(offer)
        return offers
