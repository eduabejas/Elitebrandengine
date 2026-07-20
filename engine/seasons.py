"""Seasonality intelligence — buy off-season.

The single most reliable outdoor-gear discount is **counter-seasonal**: winter
kit (down, hardshells, mountaineering boots) is cleared in spring/summer, and
summer kit (hiking/climbing/trail) is cleared in fall/winter. So the engine:

1. infers each product's *use season* from its category (or an explicit
   ``season`` on the watch item);
2. knows the *current season* for the operator's hemisphere;
3. flags **off-season** opportunities and boosts their priority, and
4. recognises well-known **sale windows** (Black Friday, end-of-season
   clearances, REI Anniversary…) for extra context.

Everything here is pure date logic — no network, fully testable.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

SEASONS = ("winter", "spring", "summer", "fall")

# Month (1-12) -> season, northern hemisphere.
_NORTH_BY_MONTH = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "fall", 10: "fall", 11: "fall",
}
_OPPOSITE = {"winter": "summer", "summer": "winter", "spring": "fall", "fall": "spring"}


def current_season(d: Optional[date] = None, hemisphere: str = "north") -> str:
    d = d or date.today()
    season = _NORTH_BY_MONTH[d.month]
    if str(hemisphere).lower().startswith("s"):
        season = _OPPOSITE[season]
    return season


# Category keyword -> use-season. Checked in order (most specific first).
_CATEGORY_RULES: list[tuple[str, str]] = [
    ("down", "winter"), ("insulated", "winter"), ("puffer", "winter"),
    ("parka", "winter"), ("hardshell", "winter"), ("ski", "winter"),
    ("mountaineering", "winter"), ("alpine", "winter"), ("glove", "winter"),
    ("mitten", "winter"), ("fleece", "winter"),
    ("rain", "3season"), ("softshell", "3season"), ("wind", "3season"),
    ("climbing shoe", "summer"), ("approach", "summer"), ("sandal", "summer"),
    ("trail run", "summer"), ("hiking shoe", "summer"), ("short", "summer"),
    ("sun ", "summer"),
    ("harness", "3season"), ("daypack", "3season"), ("backpack", "3season"),
    ("pack", "3season"), ("tent", "3season"), ("sleeping", "3season"),
    ("pad", "3season"), ("trekking pole", "3season"), ("headlamp", "3season"),
    ("hiking boot", "3season"), ("boot", "3season"),
]


def use_season(category: Optional[str], explicit: str = "auto") -> str:
    """Return winter | summer | 3season for a product."""
    explicit = (explicit or "auto").lower()
    if explicit in ("winter", "summer", "3season", "all"):
        return explicit
    cat = (category or "").lower()
    for kw, season in _CATEGORY_RULES:
        if kw in cat:
            return season
    return "3season"


def offseason_status(product_season: str, d: Optional[date] = None,
                     hemisphere: str = "north") -> tuple[bool, int, Optional[str]]:
    """Is now a good counter-seasonal time to buy this product?

    Returns ``(is_offseason, strength, note)`` where strength is 2 (peak
    clearance), 1 (shoulder — season just ended) or 0 (in season / n/a).
    """
    d = d or date.today()
    cur = current_season(d, hemisphere)
    ps = (product_season or "3season").lower()

    if ps in ("3season", "all"):
        return (False, 0, None)

    if ps == "winter":
        if cur == "summer":
            return (True, 2, "Ropa de invierno en verano — ventana de liquidación "
                             "de fin de temporada (máximo valor).")
        if cur == "spring":
            return (True, 1, "Invierno saliendo de temporada — liquidaciones de primavera.")
        return (False, 0, None)  # fall/winter = in season, expect full price

    if ps == "summer":
        if cur == "winter":
            return (True, 2, "Equipo de verano en invierno — liquidación de "
                             "contra-temporada (máximo valor).")
        if cur == "fall":
            return (True, 1, "Verano saliendo de temporada — liquidaciones de otoño.")
        return (False, 0, None)

    return (False, 0, None)


# Well-known US outdoor sale windows (month, day) inclusive. First match wins.
_SALE_WINDOWS: list[tuple[str, tuple[int, int], tuple[int, int]]] = [
    ("Liquidación de fin de invierno", (2, 1), (4, 15)),
    ("REI Anniversary Sale", (5, 15), (5, 27)),
    ("Memorial Day sales", (5, 22), (5, 29)),
    ("Prime Day / mid-year sales", (7, 8), (7, 17)),
    ("Liquidación de fin de verano", (8, 15), (10, 15)),
    ("Labor Day sales", (8, 30), (9, 7)),
    ("Black Friday / Cyber Monday", (11, 20), (12, 2)),
]


def active_sale_window(d: Optional[date] = None) -> Optional[str]:
    d = d or date.today()
    md = (d.month, d.day)
    for name, start, end in _SALE_WINDOWS:
        if start <= md <= end:
            return name
    return None
