"""Core data structures for the Elite Brand Engine.

Everything is a plain dataclass so it serialises cleanly to/from JSON (the
engine's only storage format on the free tier). Money is stored as a float in
a single ``currency`` (USD by default); prices are always normalised to that
currency before comparison.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


def now_iso() -> str:
    """UTC timestamp in ISO-8601, second precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Watchlist                                                                    #
# --------------------------------------------------------------------------- #
@dataclass
class WatchItem:
    """A single product the company wants to track.

    Empty ``sizes`` / ``colors`` mean "any variant qualifies". ``target_price``
    is the price at or below which the operator wants an alert; if it is ``None``
    the engine falls back to statistical deal detection (drop vs. history).
    """

    id: str
    brand: str
    name: str
    category: str = "general"
    sizes: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    target_price: Optional[float] = None
    currency: str = "USD"
    keywords: list[str] = field(default_factory=list)  # extra search terms
    upc: Optional[str] = None                           # GTIN/UPC/EAN if known
    mpn: Optional[str] = None                           # manufacturer part no.
    image: Optional[str] = None                         # optional image URL
    active: bool = True
    # Seasonality & pricing hints (all optional):
    season: str = "auto"          # winter | summer | 3season | all | auto(=infer from category)
    msrp: Optional[float] = None  # explicit regular price anchor (else inferred)
    min_discount_pct: Optional[float] = None  # per-item override of the threshold

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "WatchItem":
        known = {f for f in WatchItem.__dataclass_fields__}  # type: ignore[attr-defined]
        return WatchItem(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Offers                                                                       #
# --------------------------------------------------------------------------- #
@dataclass
class Offer:
    """A concrete price found for a watch item at one source."""

    watch_id: str
    source: str                       # human label: "REI", "eBay", "Amazon"...
    title: str                        # the listing's own title
    url: str                          # direct link to the product/listing
    price: float
    currency: str = "USD"
    size: Optional[str] = None
    color: Optional[str] = None
    condition: str = "new"            # new | used | refurbished
    availability: str = "unknown"     # in_stock | out_of_stock | unknown
    seller: Optional[str] = None
    image: Optional[str] = None
    list_price: Optional[float] = None  # source's own "was" price, if provided
    match_score: float = 0.0          # 0..1 confidence this is the right product
    fetched_at: str = field(default_factory=now_iso)

    @property
    def id(self) -> str:
        raw = f"{self.source}|{self.url}|{self.size}|{self.color}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        return d


# --------------------------------------------------------------------------- #
# Price history                                                                #
# --------------------------------------------------------------------------- #
@dataclass
class PricePoint:
    """One observation in a product's price history (append-only JSONL)."""

    ts: str
    source: str
    price: float
    size: Optional[str] = None
    color: Optional[str] = None
    condition: str = "new"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "PricePoint":
        known = {f for f in PricePoint.__dataclass_fields__}  # type: ignore[attr-defined]
        return PricePoint(**{k: v for k, v in d.items() if k in known})


# --------------------------------------------------------------------------- #
# Deals                                                                        #
# --------------------------------------------------------------------------- #
@dataclass
class Deal:
    """A qualifying price drop worth alerting on.

    These are exactly the fields the alert email needs: product name, size,
    website, direct link and price — plus context (colour, discount, reason).
    """

    watch_id: str
    brand: str
    product_name: str
    source: str                        # "website encontrado"
    url: str                           # "link directo"
    price: float                       # "precio"
    currency: str
    size: Optional[str]                # "talla"
    color: Optional[str]
    condition: str
    reason: str                        # why it qualified (human readable)
    discount_pct: Optional[float]      # vs reference_price, if known
    reference_price: Optional[float]   # the "regular" (non-sale) anchor used
    target_price: Optional[float]
    # Deal-intelligence fields (v2):
    score: float = 0.0                 # 0..100 ranking (higher = act sooner)
    tier: str = "good"                 # good | great | excellent | suspect | target
    seasonal: bool = False             # True = off-season clearance opportunity
    season_note: Optional[str] = None  # human context, e.g. end-of-winter clearance
    suspect: bool = False              # discount too large to trust (verify first)
    lowest_in_days: Optional[int] = None
    detected_at: str = field(default_factory=now_iso)

    @property
    def key(self) -> str:
        """Stable identity used to avoid emailing the same deal twice."""
        raw = f"{self.watch_id}|{self.source}|{self.size}|{self.color}|{round(self.price, 2)}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["key"] = self.key
        return d
