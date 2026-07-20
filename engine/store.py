"""Persistence layer.

On the free tier there is no database — the git repository itself is the store.
Everything is JSON so it diffs cleanly and its history doubles as an audit log.

Layout::

    data/watchlist.json          # curated products to track (hand-edited)
    data/history/<watch_id>.jsonl# append-only price observations
    data/alerts_ledger.json      # which deals were already emailed (dedupe)
    web/data/*.json              # snapshot the static site reads
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .config import Config
from .models import Deal, Offer, PricePoint, WatchItem, now_iso


# --------------------------------------------------------------------------- #
# Watchlist                                                                    #
# --------------------------------------------------------------------------- #
def load_watchlist(cfg: Config) -> list[WatchItem]:
    p = cfg.path("watchlist")
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    return [WatchItem.from_dict(x) for x in items if x.get("active", True)]


# --------------------------------------------------------------------------- #
# Price history (append-only JSONL, one file per watch item)                   #
# --------------------------------------------------------------------------- #
def _history_path(cfg: Config, watch_id: str) -> Path:
    return cfg.path("history_dir") / f"{watch_id}.jsonl"


def load_history(cfg: Config, watch_id: str) -> list[PricePoint]:
    p = _history_path(cfg, watch_id)
    if not p.exists():
        return []
    out: list[PricePoint] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(PricePoint.from_dict(json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def append_history(cfg: Config, watch_id: str, points: Iterable[PricePoint]) -> None:
    p = _history_path(cfg, watch_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        for pt in points:
            fh.write(json.dumps(pt.to_dict(), ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# Alerts ledger (dedupe emails)                                               #
# --------------------------------------------------------------------------- #
def load_ledger(cfg: Config) -> dict[str, str]:
    p = cfg.path("alerts_ledger")
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_ledger(cfg: Config, ledger: dict[str, str]) -> None:
    p = cfg.path("alerts_ledger")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Web snapshot the static site reads                                          #
# --------------------------------------------------------------------------- #
def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def write_snapshot(
    cfg: Config,
    watchlist: list[WatchItem],
    offers_by_watch: dict[str, list[Offer]],
    deals: list[Deal],
    sources_status: list[dict],
    demo: bool = False,
) -> None:
    """Emit the JSON files consumed by the GitHub Pages front-end."""
    web = cfg.path("web_data")

    # Per-product roll-up with best price + all offers + a small history series.
    products = []
    for w in watchlist:
        offers = sorted(offers_by_watch.get(w.id, []), key=lambda o: o.price)
        best = offers[0] if offers else None
        hist = load_history(cfg, w.id)
        series = [
            {"ts": h.ts, "price": h.price, "source": h.source}
            for h in hist[-60:]  # cap for a lightweight page
        ]
        products.append(
            {
                **w.to_dict(),
                "best_price": best.price if best else None,
                "best_source": best.source if best else None,
                "offer_count": len(offers),
                "offers": [o.to_dict() for o in offers],
                "history": series,
            }
        )

    meta = {
        "generated_at": now_iso(),
        "currency": cfg.currency,
        "demo": demo,
        "product_count": len(products),
        "offer_count": sum(len(v) for v in offers_by_watch.values()),
        "deal_count": len(deals),
        "sources": sources_status,
        "site": cfg.get("site", {}),
    }

    ranked = sorted(deals, key=lambda d: d.score, reverse=True)
    write_json(web / "products.json", {"products": products})
    write_json(web / "deals.json", {"deals": [d.to_dict() for d in ranked]})
    write_json(web / "meta.json", meta)
