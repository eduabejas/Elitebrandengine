"""Orchestrator — one collection cycle.

Flow per run:
    load config + watchlist
    build enabled/available connectors
    for each watch item:
        gather offers from every connector (dedupe, filter by match score)
        detect deals against PRIOR price history
        append this run's observations to history
    update the alert ledger, write the website snapshot, email new deals

Run locally::
    python -m engine.run                 # collect + (dry-run) email
    python -m engine.run --no-email      # collect only
    python -m engine.run --limit 5       # first 5 watch items (debugging)
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from .config import load_config
from .connectors import build_connectors
from .dealdetector import detect_deals
from .models import Deal, Offer, PricePoint, WatchItem, now_iso
from .normalize import match_score
from .pricing import to_base
from .notify import send_deal_alerts
from .store import (
    append_history,
    load_history,
    load_ledger,
    load_promos,
    load_watchlist,
    save_ledger,
    write_snapshot,
)


def _gather_offers(connectors, watch: WatchItem, min_score: float) -> list[Offer]:
    seen: dict[str, Offer] = {}
    for conn in connectors:
        try:
            found = conn.search(watch) or []
        except Exception as exc:  # noqa: BLE001 - one bad source must not kill the run
            print(f"[run] connector {getattr(conn, 'name', conn)} failed on "
                  f"{watch.id}: {exc}")
            continue
        for o in found:
            if o.match_score < min_score:
                continue
            prev = seen.get(o.id)
            if prev is None or o.price < prev.price:
                seen[o.id] = o
    return list(seen.values())


def _history_points(offers: list[Offer], rates: dict, base: str) -> list[PricePoint]:
    """One point per source (its lowest price this run) to bound history size.
    Prices are normalised to the base currency so history stays comparable."""
    best_by_source: dict[str, Offer] = {}
    for o in offers:
        cur = best_by_source.get(o.source)
        if cur is None or o.price < cur.price:
            best_by_source[o.source] = o
    ts = now_iso()
    return [
        PricePoint(ts=ts, source=o.source,
                   price=round(to_base(o.price, o.currency, rates, base), 2),
                   size=o.size, color=o.color, condition=o.condition)
        for o in best_by_source.values()
    ]


def run(config_file: str | None = None, send_email: bool = True,
        limit: int | None = None) -> dict:
    cfg = load_config(config_file)
    watchlist = load_watchlist(cfg)
    if limit:
        watchlist = watchlist[:limit]
    connectors = build_connectors(cfg)
    min_score = float(cfg.get("detection.min_match_score", 0.6))
    rates = cfg.get("fx.rates", {}) or {}
    base = cfg.get("fx.base", "USD")

    print(f"[run] {len(watchlist)} watch item(s), "
          f"{len(connectors)} source(s): {[c.name for c in connectors]}")

    ledger = load_ledger(cfg)
    promos = load_promos(cfg)
    offers_by_watch: dict[str, list[Offer]] = {}
    all_active: list[Deal] = []
    all_new: list[Deal] = []
    source_offer_counts: dict[str, int] = defaultdict(int)

    for w in watchlist:
        offers = _gather_offers(connectors, w, min_score)
        offers_by_watch[w.id] = offers
        for o in offers:
            source_offer_counts[o.source] += 1

        history = load_history(cfg, w.id)  # PRIOR history = the reference
        active, new = detect_deals(cfg, w, offers, history, ledger, promos=promos)
        all_active.extend(active)
        all_new.extend(new)

        append_history(cfg, w.id, _history_points(offers, rates, base))
        if offers:
            cheapest = min(offers, key=lambda o: o.price)
            print(f"  · {w.id}: {len(offers)} offer(s), "
                  f"best {cheapest.price:.2f} @ {cheapest.source}"
                  + (f"  [{len(active)} deal(s)]" if active else ""))

    # Record newly-alerted deals so we don't email them again within the TTL.
    ts = now_iso()
    for d in all_new:
        ledger[d.key] = ts
    save_ledger(cfg, ledger)

    sources_status = _sources_status(cfg, connectors, source_offer_counts)
    demo = [c.name for c in connectors] == ["sample"]
    write_snapshot(cfg, watchlist, offers_by_watch, all_active, sources_status,
                   demo=demo)

    print(f"[run] active deals: {len(all_active)} | new to alert: {len(all_new)}")
    if send_email:
        send_deal_alerts(cfg, all_new)

    return {
        "watch_items": len(watchlist),
        "offers": sum(len(v) for v in offers_by_watch.values()),
        "active_deals": len(all_active),
        "new_deals": len(all_new),
    }


def _sources_status(cfg, connectors, counts) -> list[dict]:
    """Per-storefront status for the website footer (what actually produced
    offers), plus any configured-but-unavailable connectors for transparency."""
    status = [{"name": name, "available": True, "offers": n}
              for name, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    configured = cfg.get("sources", {}) or {}
    label_by_key = {"ebay": "eBay", "amazon": "Amazon",
                    "affiliate_feed": "AffiliateFeed"}
    ran_conn = {c.name for c in connectors}
    for key, s in configured.items():
        if key == "sample":
            continue
        label = label_by_key.get(key, key)
        if s.get("enabled") and label not in ran_conn:
            status.append({"name": label, "available": False, "offers": 0})
    return status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Elite Brand Engine — collection cycle")
    ap.add_argument("--config", default=None, help="path to a config file")
    ap.add_argument("--no-email", action="store_true", help="collect without sending")
    ap.add_argument("--limit", type=int, default=None, help="limit watch items")
    args = ap.parse_args(argv)
    summary = run(args.config, send_email=not args.no_email, limit=args.limit)
    print(f"[run] done: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
