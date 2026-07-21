"""Credibility — don't create false hopes ("no ilusionar").

The hardest lesson from the field: a *deep* discount is not always an
opportunity. A **cult / niche** brand (Mammut, Helly Hansen, Peak Performance,
Arc'teryx, Norrøna…) shown at −50% *new* on a **resale marketplace** (eBay) is
almost certainly **not in good/new condition or not genuine** — surfacing it
wastes time and manufactures illusions. Meanwhile a **mass, high-circulation**
brand (The North Face, Columbia, REI Co-op) *can* legitimately turn up cheap on
resale, because uninformed owners dump it below its niche value.

So believability depends on **brand tier × channel × discount depth**:

* cult brands only discount modestly (≈25–40%) and through **authorized/official**
  channels (often flash, gone in an hour) — a deep cult discount on **resale** is
  implausible;
* mass brands can be deeply discounted anywhere, incl. resale;
* official **outlet** channels justify deeper cuts (past-season clearance).

When a discount exceeds the believable ceiling for its (tier, channel) it is
flagged **implausible** → the brain will not present it as a real opportunity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .normalize import canonical_brand

# --------------------------------------------------------------------------- #
# Brand tiers                                                                  #
# --------------------------------------------------------------------------- #
_TIER_BRANDS: dict[str, list[str]] = {
    # High circulation: deep resale discounts are plausible (uninformed sellers).
    "mass": ["The North Face", "Columbia", "REI Co-op", "Marmot", "Salomon"],
    # In-between: premium but widely sold.
    "premium": ["Patagonia", "Outdoor Research", "Mountain Hardwear",
                "Black Diamond", "Osprey", "Gregory", "Deuter", "Petzl",
                "Lowa", "Asolo", "Exped"],
    # Cult / niche: not mass-produced; deep *new* discounts on resale are suspect.
    "cult": ["Arc'teryx", "Mammut", "Norrøna", "Ortovox", "Salewa",
             "Peak Performance", "Helly Hansen", "Rab", "Fjällräven", "Montbell",
             "La Sportiva", "Scarpa", "Ansilta", "Montagne"],
}
_BRAND_TIER: dict[str, str] = {
    b: tier for tier, brands in _TIER_BRANDS.items() for b in brands
}

# Believable MAX % off for a *genuine new* item, by (tier, channel class).
_CEILINGS: dict[tuple[str, str], float] = {
    ("mass", "authorized"): 60, ("mass", "outlet"): 70, ("mass", "marketplace"): 65,
    ("premium", "authorized"): 50, ("premium", "outlet"): 60, ("premium", "marketplace"): 45,
    ("cult", "authorized"): 40, ("cult", "outlet"): 50, ("cult", "marketplace"): 25,
}

# Third-party resale marketplaces (condition uncertain).
_MARKETPLACES = {"ebay", "mercadolibre", "poshmark", "grailed", "vinted",
                 "marketplace", "reventa", "resale"}


def brand_tier(brand: Optional[str], overrides: Optional[dict] = None) -> str:
    b = canonical_brand(brand) or (brand or "")
    if overrides and b in overrides:
        return overrides[b]
    return _BRAND_TIER.get(b, "premium")


def channel_class(source: Optional[str], channel: str = "new") -> str:
    if channel == "outlet":
        return "outlet"
    s = (source or "").lower()
    if any(m in s for m in _MARKETPLACES):
        return "marketplace"
    return "authorized"


def believable_ceiling(tier: str, cclass: str, overrides: Optional[dict] = None) -> float:
    if overrides:
        # overrides keyed as "tier:cclass"
        key = f"{tier}:{cclass}"
        if key in overrides:
            return float(overrides[key])
    return float(_CEILINGS.get((tier, cclass), 55.0))


@dataclass
class Credibility:
    tier: str
    channel_class: str
    ceiling: float
    credibility: float       # 0..1 (1 = fully believable as genuine new)
    implausible: bool
    note: Optional[str] = None


def assess(brand: Optional[str], source: Optional[str], channel: str,
           discount_pct: Optional[float], condition: str = "new", *,
           tier_overrides: Optional[dict] = None,
           ceiling_overrides: Optional[dict] = None) -> Credibility:
    tier = brand_tier(brand, tier_overrides)
    cclass = channel_class(source, channel)
    ceiling = believable_ceiling(tier, cclass, ceiling_overrides)

    # No discount to judge, or a non-new item whose discount is condition-priced.
    if discount_pct is None or discount_pct <= 0 or condition != "new":
        return Credibility(tier, cclass, ceiling, 1.0, False, None)

    if discount_pct <= ceiling:
        return Credibility(tier, cclass, ceiling, 1.0, False, None)

    over = discount_pct - ceiling
    credibility = max(0.0, round(1.0 - over / 40.0, 2))  # fades past the ceiling
    note = (f"{tier} en {cclass} a −{discount_pct:.0f}% supera el techo creíble "
            f"(~{ceiling:.0f}%): probable no nuevo/no genuino — verificar condición")
    return Credibility(tier, cclass, ceiling, credibility, True, note)
