"""Sample connector — deterministic synthetic offers for demos & tests.

This ships **enabled** so the entire pipeline (collection → detection → email →
website) works the instant you clone the repo, with zero API keys. It fabricates
believable multi-source pricing for each watch item, including occasional sales
(``list_price`` > ``price``) so real deals surface on the very first run.

Swap it for the real connectors (eBay, Amazon, affiliate feeds) by editing
``config.yml``. Nothing here touches the network.
"""

from __future__ import annotations

import hashlib
from datetime import date

from ..models import Offer, WatchItem
from ..normalize import canonical_brand
from .base import Connector

# Simulated storefronts, mirroring the real targets (REI, official, eBay, Amazon).
_SOURCES = [
    ("REI Co-op", "https://www.rei.com/product/", 1.00, "new"),
    ("Backcountry", "https://www.backcountry.com/", 0.97, "new"),
    ("Brand Official", "https://example-brand.com/shop/", 1.03, "new"),
    ("Amazon", "https://www.amazon.com/dp/", 0.95, "new"),
    ("eBay", "https://www.ebay.com/itm/", 0.88, "used"),
]

_DEFAULT_SIZES = ["S", "M", "L", "XL"]
_DEFAULT_COLORS = ["Black", "Blue", "Green"]


def _rand01(*parts: str) -> float:
    """Deterministic pseudo-random float in [0,1) from a seed string."""
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _pick(seq, seed: str):
    return seq[int(_rand01(seed) * len(seq)) % len(seq)]


class SampleConnector(Connector):
    name = "sample"

    def search(self, watch: WatchItem) -> list[Offer]:
        # 'as_of' lets the seed script generate backdated history for the demo.
        today = self.settings.get("as_of") or date.today().isoformat()

        # Baseline MSRP: derive from target price if set (targets are ~25% off),
        # else a stable per-product figure in a plausible range.
        if watch.target_price:
            msrp = round(watch.target_price / 0.75, 2)
        else:
            msrp = round(80 + _rand01(watch.id, "msrp") * 570, 2)

        sizes = watch.sizes or _DEFAULT_SIZES
        colors = watch.colors or _DEFAULT_COLORS
        brand = canonical_brand(watch.brand) or watch.brand

        offers: list[Offer] = []
        for label, base_url, factor, cond in _SOURCES:
            seed = f"{watch.id}|{label}|{today}"
            # Each storefront: a small price spread + a chance of a real sale.
            spread = 0.9 + _rand01(seed, "spread") * 0.2  # 0.90..1.10
            on_sale = _rand01(seed, "sale") < 0.45
            sale_factor = (0.62 + _rand01(seed, "depth") * 0.23) if on_sale else 1.0

            price = round(msrp * factor * spread * sale_factor, 2)
            list_price = msrp if on_sale else None

            size = _pick(sizes, seed + "size")
            color = _pick(colors, seed + "color")
            slug = watch.id.replace("_", "-")
            offers.append(
                Offer(
                    watch_id=watch.id,
                    source=label,
                    title=f"{brand} {watch.name} — {color}, {size}",
                    url=f"{base_url}{slug}?v={size}-{color}".replace(" ", "-").lower(),
                    price=price,
                    currency=watch.currency,
                    size=size,
                    color=color,
                    condition=cond,
                    availability="in_stock",
                    seller=label,
                    list_price=list_price,
                    match_score=1.0,  # synthetic data is a guaranteed match
                )
            )
        return offers
