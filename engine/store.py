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
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .config import Config
from .identity import channel_region_summary
from .models import Deal, Offer, PricePoint, WatchItem, now_iso


def _atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a killed run can't corrupt the
    store (a truncated JSONL/JSON file would poison every later run)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


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


def load_promos(cfg: Config) -> dict:
    """Retailer modifiers + active coupons for effective-price stacking.
    Returns {} when data/promos.json is absent (=> effective price == price)."""
    p = cfg.path("promos")
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError:
        return {}


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


def _downsample_daily(points: list[PricePoint]) -> list[PricePoint]:
    """Collapse to one observation per (day, source), keeping the latest.

    Runs happen every few hours; without this the file would grow by one line
    per source per run forever. Daily resolution is more than enough for the
    percentile baseline and historical-low logic."""
    kept: dict[tuple[str, str], PricePoint] = {}
    # Ascending by ts => the last write for a (day, source) wins (latest price).
    for pt in sorted(points, key=lambda x: x.ts):
        dt = _parse_ts(pt.ts)
        day = dt.date().isoformat() if dt else pt.ts   # unparsable => keep as-is
        kept[(day, pt.source)] = pt
    return sorted(kept.values(), key=lambda x: x.ts)


def _trim_history(cfg: Config, points: list[PricePoint]) -> list[PricePoint]:
    d = cfg.get("detection", {}) or {}
    if d.get("history_daily_downsample", True):
        points = _downsample_daily(points)
    else:
        points = sorted(points, key=lambda x: x.ts)

    retention_days = int(d.get("history_retention_days", 180) or 0)
    if retention_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        kept = []
        for pt in points:
            dt = _parse_ts(pt.ts)
            if dt is None or dt >= cutoff:   # keep unparsable rather than lose data
                kept.append(pt)
        points = kept

    max_points = int(d.get("history_max_points", 5000) or 0)
    if max_points > 0 and len(points) > max_points:
        points = points[-max_points:]        # keep the most recent
    return points


def append_history(cfg: Config, watch_id: str, points: Iterable[PricePoint]) -> None:
    """Append this run's observations, then trim so the file can never grow
    without bound (daily downsample + retention window + hard cap). Rewrites
    the file atomically."""
    new = list(points)
    p = _history_path(cfg, watch_id)
    merged = load_history(cfg, watch_id) + new
    trimmed = _trim_history(cfg, merged)
    body = "".join(json.dumps(pt.to_dict(), ensure_ascii=False) + "\n" for pt in trimmed)
    _atomic_write_text(p, body)


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


def prune_ledger(ledger: dict[str, str], ttl_days: int) -> dict[str, str]:
    """Drop entries older than the alert TTL. Past the TTL an entry no longer
    suppresses a re-alert, so keeping it is pure dead weight — without this the
    ledger grows by every distinct deal key ever seen, forever."""
    if ttl_days <= 0:
        return dict(ledger)
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    out: dict[str, str] = {}
    for key, ts in ledger.items():
        dt = _parse_ts(ts)
        if dt is not None and dt >= cutoff:
            out[key] = ts        # unparsable timestamps are treated as expired
    return out


def save_ledger(cfg: Config, ledger: dict[str, str]) -> None:
    p = cfg.path("alerts_ledger")
    _atomic_write_text(p, json.dumps(ledger, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Web snapshot the static site reads                                          #
# --------------------------------------------------------------------------- #
def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def write_status(cfg: Config, status: dict) -> None:
    """Write run observability (timings, per-source health, counts) to a served
    copy (web/data/status.json) and a persisted copy (data/status.json)."""
    write_json(cfg.path("web_data") / "status.json", status)
    write_json(cfg.path("status"), status)


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
                "summary": channel_region_summary(offers),  # best per channel/region
                "history": series,
            }
        )

    meta = {
        "generated_at": now_iso(),
        "currency": cfg.currency,
        "demo": demo,
        "scope": cfg.get("search.scope", "standard"),
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
