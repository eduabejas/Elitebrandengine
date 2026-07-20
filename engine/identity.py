"""Product identity graph — resolve "the same article" across channels & regions.

Two jobs:

1. **Channel & region tagging.** Classify each offer as new / outlet /
   refurbished / used, and tag the retailer's region (US / CA / EU / ...). This
   lets the engine count outlet & previous-season deals as the same product, and
   power a **regional search scope**: standard (US) vs expanded (US + CA + EU).

2. **Home-region advantage.** Many brands are cheapest in their home market —
   Peak Performance, Helly Hansen, Norrøna, Rab, Mammut, Scarpa… are European;
   Arc'teryx is Canadian. In expanded scope the engine surfaces the home-market
   price even though it ships internationally. Per the operator's instruction,
   **international shipping is taken as a known cost of the buyer's business and
   is NOT used to penalise or hide these opportunities.**

Model *lineage* (previous-season / renamed SKUs matching the same article) is
handled in ``normalize.match_score`` via the watch item's ``lineage`` aliases.
"""

from __future__ import annotations

from typing import Optional

from .normalize import canonical_brand

# --------------------------------------------------------------------------- #
# Channel classification                                                       #
# --------------------------------------------------------------------------- #
_CHANNEL_RULES: list[tuple[str, list[str]]] = [
    ("refurbished", ["refurb", "renewed", "regear", "re/gear", "re-gear",
                     "reconditioned", "certified pre"]),
    ("used", ["pre-owned", "preowned", "second hand", "open box", "open-box", "used"]),
    ("outlet", ["outlet", "last chance", "worn wear", "re/supply", "resupply",
                "re-supply", "clearance", "past season", "prior season",
                "steep & cheap", "steep and cheap", "overstock"]),
]


def classify_channel(source: Optional[str], title: str = "",
                     condition: Optional[str] = None) -> str:
    text = f"{source or ''} {title or ''}".lower()
    for channel, kws in _CHANNEL_RULES:
        if any(k in text for k in kws):
            return channel
    if condition in ("used", "refurbished"):
        return condition
    return "new"


# --------------------------------------------------------------------------- #
# Regions                                                                      #
# --------------------------------------------------------------------------- #
BRAND_HOME_REGION: dict[str, str] = {
    "Arc'teryx": "CA",
    "The North Face": "US", "Black Diamond": "US", "Patagonia": "US",
    "Outdoor Research": "US", "Mountain Hardwear": "US", "Marmot": "US",
    "Columbia": "US", "Osprey": "US", "Gregory": "US",
    "Mammut": "EU", "Deuter": "EU", "Rab": "EU", "Fjällräven": "EU",
    "Norrøna": "EU", "Salewa": "EU", "Ortovox": "EU", "Peak Performance": "EU",
    "Helly Hansen": "EU", "Petzl": "EU", "La Sportiva": "EU", "Scarpa": "EU",
    "Salomon": "EU", "Lowa": "EU", "Asolo": "EU", "Exped": "EU",
    "Montbell": "JP",
    "Ansilta": "AR", "Montagne": "AR",
}

SOURCE_REGION: dict[str, str] = {
    "REI Co-op": "US", "Backcountry": "US", "Amazon": "US", "eBay": "US",
    "Brand Official": "US", "REI Re/Supply (outlet)": "US", "Moosejaw": "US",
    "Steep & Cheap": "US",
    "MEC (CA)": "CA", "Altitude Sports (CA)": "CA",
    "Bergfreunde (EU)": "EU", "Alpinetrek (EU)": "EU", "Addnature (EU)": "EU",
    "Bergzeit (EU)": "EU", "Brand Official EU": "EU",
}

_SCOPES: dict[str, set[str]] = {
    "standard": {"US"},
    "expanded": {"US", "CA", "EU"},
}


def home_region(brand: Optional[str], explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit.upper()
    return BRAND_HOME_REGION.get(canonical_brand(brand) or (brand or ""), "US")


def source_region(source: Optional[str], default: str = "US") -> str:
    if source in SOURCE_REGION:
        return SOURCE_REGION[source]
    s = (source or "").lower()
    if "(eu)" in s or "europe" in s:
        return "EU"
    if "(ca)" in s or "canada" in s:
        return "CA"
    return default


def regions_for_scope(scope: Optional[str]) -> set[str]:
    return set(_SCOPES.get((scope or "standard").lower(), {"US"}))


# --------------------------------------------------------------------------- #
# Enrichment & grouping                                                        #
# --------------------------------------------------------------------------- #
def enrich_offer(offer):
    """Tag an offer with its channel and region (in place)."""
    offer.channel = classify_channel(offer.source, offer.title, offer.condition)
    # Respect a region the connector set explicitly; else derive from the source.
    if not getattr(offer, "region", None) or offer.region == "US":
        offer.region = source_region(offer.source, offer.region or "US")
    return offer


def home_region_advantage(watch, offers) -> tuple[bool, str]:
    """Is the brand's home market cheaper than the US price? Returns (flag, hr)."""
    hr = home_region(getattr(watch, "brand", None), getattr(watch, "home_region", None))
    if hr == "US":
        return (False, hr)
    us = [o.price for o in offers if o.region == "US"]
    home = [o.price for o in offers if o.region == hr]
    if not us or not home:
        return (False, hr)
    return (min(home) < min(us) * 0.98, hr)  # home meaningfully cheaper


def channel_region_summary(offers) -> dict:
    """Best price per channel and per region — for the product snapshot."""
    best_channel: dict[str, float] = {}
    best_region: dict[str, float] = {}
    for o in offers:
        if o.channel not in best_channel or o.price < best_channel[o.channel]:
            best_channel[o.channel] = o.price
        if o.region not in best_region or o.price < best_region[o.region]:
            best_region[o.region] = o.price
    return {"by_channel": best_channel, "by_region": best_region}
