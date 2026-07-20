"""Community signals — handled *with tweezers*.

Deal communities (Reddit, forums, deal aggregators) surface human-found deals
fast, but they also carry **fake, stale or exaggerated** claims. So a community
post is treated only as a **low-trust LEAD**, never as a deal:

* the **claimed price is never trusted** on its own;
* a lead only counts if it is **corroborated** by an independently *observed*
  offer (from a structured/API source) at or below the claimed price within a
  small tolerance — otherwise it is discarded as noise/fake;
* processing is **bounded** (a cap per run) so no volume of posts can slow the
  engine.

This module is the pure logic (fully tested). Live ingestion of any community
source is **off by default** and deferred; when added, it must feed through
:func:`corroborated_leads` so the anti-fake-news gate always applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import Offer, WatchItem
from .normalize import match_score
from .pricing import to_base

DEFAULT_TRUST = 0.3  # community posts start low-trust


@dataclass
class CommunitySignal:
    source: str                       # e.g. "reddit:ULgeartrade"
    text: str                         # post title / body
    url: str = ""
    brand: Optional[str] = None
    name: Optional[str] = None
    claimed_price: Optional[float] = None
    currency: str = "USD"
    posted_at: str = ""


def source_trust(source: str, trust_table: Optional[dict] = None) -> float:
    if trust_table and source in trust_table:
        return float(trust_table[source])
    return DEFAULT_TRUST


def match_signal(signal: CommunitySignal, watchlist: list[WatchItem],
                 min_score: float = 0.6) -> tuple[Optional[WatchItem], float]:
    """Which watch item (if any) this post likely refers to."""
    hint = f"{signal.brand or ''} {signal.name or signal.text}"
    best: Optional[WatchItem] = None
    best_s = 0.0
    for w in watchlist:
        s = match_score(w, hint, signal.brand)
        if s > best_s:
            best, best_s = w, s
    return (best, best_s) if best_s >= min_score else (None, best_s)


def corroborate(signal: CommunitySignal, observed_offers: list[Offer], *,
                rates: dict, base: str, tolerance: float = 0.10) -> Optional[Offer]:
    """Return a real observed offer that BACKS the claim, or ``None``.

    The anti-fake-news gate: a claim only survives if an independently observed
    offer actually exists at/below the claimed price (within tolerance). A post
    with no supporting reality is discarded.
    """
    if not observed_offers:
        return None
    cheapest = min(observed_offers, key=lambda o: to_base(o.price, o.currency, rates, base))
    cheap_base = to_base(cheapest.price, cheapest.currency, rates, base)
    if signal.claimed_price is None:
        return cheapest  # no price claimed — the real offer stands on its own
    claim_base = to_base(signal.claimed_price, signal.currency, rates, base)
    return cheapest if cheap_base <= claim_base * (1 + tolerance) else None


def corroborated_leads(signals: list[CommunitySignal], watchlist: list[WatchItem],
                       observed_by_watch: dict[str, list[Offer]], *, rates: dict,
                       base: str, min_score: float = 0.6,
                       trust_table: Optional[dict] = None,
                       max_signals: int = 200) -> list[dict]:
    """Turn raw community posts into a bounded list of *corroborated* leads.

    Only signals that (a) match a tracked product and (b) are backed by a real
    observed offer become leads. Everything else is dropped.
    """
    leads: list[dict] = []
    for sig in signals[:max_signals]:
        w, s = match_signal(sig, watchlist, min_score)
        if w is None:
            continue
        corro = corroborate(sig, observed_by_watch.get(w.id, []), rates=rates, base=base)
        if corro is None:
            continue  # unbacked claim -> discard (likely fake/stale)
        leads.append({
            "watch_id": w.id,
            "source": sig.source,
            "url": sig.url,
            "trust": round(source_trust(sig.source, trust_table), 2),
            "match": round(s, 3),
            "corroborated_price": round(to_base(corro.price, corro.currency, rates, base), 2),
            "corroborating_source": corro.source,
        })
    return leads
