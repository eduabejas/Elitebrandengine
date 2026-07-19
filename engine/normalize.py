"""Normalisation & fuzzy matching.

Different sources spell brands, sizes and colours differently ("Arc'teryx" vs
"arcteryx", "Extra Large" vs "XL", "Fjällräven" vs "Fjallraven"). To compare
offers across REI, eBay, Amazon and brand stores we canonicalise everything to
a single representation, then score how well a found listing matches a tracked
product.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

# --------------------------------------------------------------------------- #
# Brands                                                                       #
# --------------------------------------------------------------------------- #
# Canonical name -> list of aliases/misspellings seen in the wild. The engine
# is deliberately scoped to these flagship mountaineering/alpinism brands: that
# focus is what makes matching accurate and the crawl cheap.
BRAND_ALIASES: dict[str, list[str]] = {
    "The North Face": ["the north face", "north face", "tnf", "thenorthface"],
    "Black Diamond": ["black diamond", "bd", "blackdiamond", "black diamond equipment"],
    "Patagonia": ["patagonia", "pata"],
    "Ansilta": ["ansilta"],
    "Deuter": ["deuter"],
    "Outdoor Research": ["outdoor research", "or gear", "outdoorresearch"],
    "Mammut": ["mammut"],
    "Arc'teryx": ["arc'teryx", "arcteryx", "arc teryx", "arcterix", "arc'terix"],
    "Mountain Hardwear": ["mountain hardwear", "mountain hardware", "mhw"],
    "Marmot": ["marmot"],
    "Rab": ["rab", "rab equipment"],
    "Fjällräven": ["fjällräven", "fjallraven", "fjall raven", "fjaellraeven"],
    "Norrøna": ["norrøna", "norrona", "norrøna"],
    "Salewa": ["salewa"],
    "Ortovox": ["ortovox"],
    "Montbell": ["montbell", "mont-bell", "mont bell"],
    "Columbia": ["columbia", "columbia sportswear"],
    "Helly Hansen": ["helly hansen", "hellyhansen", "helly-hansen", "hh"],
    "Petzl": ["petzl"],
    "La Sportiva": ["la sportiva", "sportiva", "lasportiva"],
    "Peak Performance": ["peak performance", "peakperformance"],
    "Osprey": ["osprey", "osprey packs"],
    "Gregory": ["gregory", "gregory mountain products"],
    "Exped": ["exped"],
    "Scarpa": ["scarpa", "scaroa"],  # "Scaroa" is a common typo of Scarpa
    "Salomon": ["salomon"],
    "Lowa": ["lowa"],
    "Asolo": ["asolo"],
    "Montagne": ["montagne"],
}

# Reverse lookup: alias -> canonical (longest aliases first so "north face"
# matches before "face" style partials).
_ALIAS_TO_BRAND: list[tuple[str, str]] = sorted(
    ((alias, brand) for brand, aliases in BRAND_ALIASES.items() for alias in aliases),
    key=lambda kv: len(kv[0]),
    reverse=True,
)

CANONICAL_BRANDS: list[str] = sorted(BRAND_ALIASES.keys())


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _slug(text: str) -> str:
    text = strip_accents(text or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def canonical_brand(raw: Optional[str]) -> Optional[str]:
    """Map any spelling to a canonical flagship brand, or ``None`` if unknown."""
    if not raw:
        return None
    s = _slug(raw)
    if not s:
        return None
    # exact alias slug match first
    for alias, brand in _ALIAS_TO_BRAND:
        if s == _slug(alias):
            return brand
    return None


def detect_brand_in_text(text: str) -> Optional[str]:
    """Find a known brand mentioned anywhere in a free-text listing title."""
    s = f" {_slug(text)} "
    for alias, brand in _ALIAS_TO_BRAND:
        if f" {_slug(alias)} " in s:
            return brand
    return None


# --------------------------------------------------------------------------- #
# Sizes                                                                        #
# --------------------------------------------------------------------------- #
_APPAREL_SIZE_MAP = {
    "xxs": "XXS", "2xs": "XXS", "xx small": "XXS", "xxsmall": "XXS",
    "xs": "XS", "x small": "XS", "xsmall": "XS", "extra small": "XS",
    "s": "S", "sm": "S", "small": "S",
    "m": "M", "md": "M", "medium": "M", "med": "M",
    "l": "L", "lg": "L", "large": "L",
    "xl": "XL", "x large": "XL", "xlarge": "XL", "extra large": "XL",
    "xxl": "XXL", "2xl": "XXL", "xx large": "XXL", "xxlarge": "XXL",
    "xxxl": "XXXL", "3xl": "XXXL",
}


def normalize_size(raw: Optional[str]) -> Optional[str]:
    """Canonicalise a size.

    Apparel letter sizes collapse to XS/S/M/L/XL/... ; numeric sizes (footwear
    US/EU, pack volume in litres) are kept as-is but tidied.
    """
    if raw is None:
        return None
    s = strip_accents(str(raw)).strip().lower()
    if not s:
        return None
    # normalise separators but KEEP '.' so footwear decimals (10.5) survive
    key = re.sub(r"[\s_-]+", " ", s).strip()
    if key in _APPAREL_SIZE_MAP:
        return _APPAREL_SIZE_MAP[key]
    # footwear / volume like "us 10.5", "eu 44", "42.5", "65l"
    m = re.search(r"(us|eu|uk)?\s*(\d{1,3}(?:\.\d)?)\s*(l|litre|liter|l\.)?", key)
    if m:
        region = (m.group(1) or "").upper()
        num = m.group(2)
        vol = m.group(3)
        if vol:
            return f"{num}L"
        return f"{region} {num}".strip()
    return raw.strip().upper()


def sizes_match(desired: Iterable[str], candidate: Optional[str]) -> bool:
    """True if ``candidate`` satisfies the desired set (empty desired = any)."""
    wanted = {normalize_size(x) for x in desired if x}
    if not wanted:
        return True
    if candidate is None:
        return False
    return normalize_size(candidate) in wanted


# --------------------------------------------------------------------------- #
# Colours                                                                      #
# --------------------------------------------------------------------------- #
# Map many marketing colour names to a base colour family so "Tnf Black",
# "Pirate Black" and "black" all match a desired "black".
_COLOR_FAMILIES = {
    "black": ["black", "pirate black", "tnf black", "asphalt", "anthracite", "caviar"],
    "white": ["white", "star white", "vaporous grey", "snow"],
    "grey": ["grey", "gray", "graphite", "slate", "charcoal", "zinc", "pewter", "smoke"],
    "blue": ["blue", "navy", "indigo", "cobalt", "steel blue", "shady blue", "teal", "denim"],
    "green": ["green", "olive", "forest", "khaki", "moss", "spruce", "fatigue", "sage"],
    "red": ["red", "crimson", "cardinal", "rococco red", "chili", "fire brick"],
    "orange": ["orange", "flame", "koi", "rust", "tangerine"],
    "yellow": ["yellow", "gold", "citrine", "sulphur"],
    "purple": ["purple", "violet", "plum", "eggplant"],
    "pink": ["pink", "magenta", "fuchsia", "rose"],
    "brown": ["brown", "coffee", "chocolate", "tan", "sand", "beige", "clay"],
}
_COLOR_TO_FAMILY: dict[str, str] = {
    name: fam for fam, names in _COLOR_FAMILIES.items() for name in names
}


def normalize_color(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    s = _slug(raw)
    if not s:
        return None
    if s in _COLOR_TO_FAMILY:
        return _COLOR_TO_FAMILY[s]
    # if any family keyword appears inside the marketing name, use that family
    for name, fam in _COLOR_TO_FAMILY.items():
        if re.search(rf"\b{name}\b", s):
            return fam
    return s  # unknown colour: keep normalised slug


def colors_match(desired: Iterable[str], candidate: Optional[str]) -> bool:
    wanted = {normalize_color(x) for x in desired if x}
    if not wanted:
        return True
    if candidate is None:
        return False
    return normalize_color(candidate) in wanted


# --------------------------------------------------------------------------- #
# Conservative extraction from free-text listing titles                        #
# --------------------------------------------------------------------------- #
# Only trust confident patterns; return None otherwise (so we never invent a
# size/colour that would wrongly include or exclude a deal).
_SIZE_LETTER_RE = re.compile(
    r"(?:\bsize[:\s]+|[\(\[\-,/]\s*)(xxs|xs|s|m|l|xl|xxl|xxxl|2xl|3xl)\b", re.I
)
_SIZE_FOOTWEAR_RE = re.compile(r"\b(us|eu|uk)\s?(\d{1,2}(?:\.\d)?)\b", re.I)
_SIZE_VOLUME_RE = re.compile(r"\b(\d{2,3})\s?l\b", re.I)


def extract_size_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _SIZE_LETTER_RE.search(text)
    if m:
        return normalize_size(m.group(1))
    m = _SIZE_VOLUME_RE.search(text)
    if m:
        return f"{m.group(1)}L"
    m = _SIZE_FOOTWEAR_RE.search(text)
    if m:
        return normalize_size(f"{m.group(1)} {m.group(2)}")
    return None


def extract_color_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    s = _slug(text)
    for name, fam in _COLOR_TO_FAMILY.items():
        if re.search(rf"\b{re.escape(name)}\b", s):
            return fam
    return None


# --------------------------------------------------------------------------- #
# Product matching                                                             #
# --------------------------------------------------------------------------- #
_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "of", "men", "mens", "women",
    "womens", "man", "woman", "unisex", "new", "size", "color", "colour",
}
# generic product-type words we keep but weight lightly (NOT dropped, so a
# "jacket" still contributes a little to the match while the model name dominates)
_GENERIC = {"jacket", "hoodie", "pant", "pants", "boot", "boots", "pack", "backpack",
            "tent", "glove", "gloves", "shell", "vest", "fleece", "shoe", "shoes"}


def tokenize(text: str) -> list[str]:
    s = _slug(text)
    return [t for t in s.split() if t and t not in {"the", "a", "an", "and", "or", "for", "with", "of"}]


def significant_tokens(text: str) -> set[str]:
    toks = tokenize(text)
    return {t for t in toks if t not in _STOPWORDS and len(t) > 1}


def match_score(watch, offer_title: str, offer_brand: Optional[str] = None) -> float:
    """Score 0..1 that ``offer_title`` is the product described by ``watch``.

    Brand must match (canonical). Then we measure how many of the watch item's
    distinctive tokens appear in the listing title, giving reduced weight to
    generic product-type words. UPC/MPN matches short-circuit to a perfect score.
    """
    brand_c = canonical_brand(watch.brand)
    title_brand = canonical_brand(offer_brand) or detect_brand_in_text(offer_title)
    if brand_c and title_brand and brand_c != title_brand:
        return 0.0
    if brand_c and not title_brand:
        # brand not visible in title: allow but cap confidence later
        pass

    # Hard identifiers win outright.
    slug_title = _slug(offer_title)
    if getattr(watch, "upc", None) and watch.upc and watch.upc.lower() in slug_title:
        return 1.0
    if getattr(watch, "mpn", None) and watch.mpn and _slug(watch.mpn) in slug_title:
        return 1.0

    want = significant_tokens(f"{watch.name} {' '.join(getattr(watch, 'keywords', []))}")
    if not want:
        return 0.5 if title_brand == brand_c else 0.0
    have = significant_tokens(offer_title)

    matched = want & have
    # weight: generic words count half
    def weight(tok: str) -> float:
        return 0.5 if tok in _GENERIC else 1.0

    want_w = sum(weight(t) for t in want) or 1.0
    got_w = sum(weight(t) for t in matched)
    overlap = got_w / want_w

    # brand confirmation bonus
    if title_brand and title_brand == brand_c:
        overlap = min(1.0, overlap + 0.1)
    elif not title_brand:
        overlap *= 0.85  # slight penalty when brand isn't confirmed in title

    return round(min(1.0, overlap), 3)
