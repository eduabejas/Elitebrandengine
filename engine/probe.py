"""Probe a single source — inspect exactly what one connector returns.

Invaluable when turning on a real API: run it right after adding credentials to
see raw offers (or a clear "missing credential" message) before enabling the
source for scheduled runs.

    python -m engine.probe sample                       # works with no keys
    python -m engine.probe ebay --id arcteryx_beta_ar_jacket
    python -m engine.probe ebay --brand "Patagonia" --name "Nano Puff" --limit 5
    python -m engine.probe amazon --query "black diamond headlamp" --json
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import load_config
from .connectors import build_connector, registry_keys
from .models import WatchItem
from .store import load_watchlist

# What to set when a source isn't available yet.
_ENV_HINTS = {
    "ebay": "env: EBAY_CLIENT_ID, EBAY_CLIENT_SECRET",
    "amazon": "env: AMAZON_ACCESS_KEY, AMAZON_SECRET_KEY, AMAZON_PARTNER_TAG",
    "affiliate_feed": "config.yml: add entries under sources.affiliate_feed.feeds",
    "sample": "(always available)",
}


def _pick_watch(cfg, args) -> WatchItem | None:
    if args.name or args.query:
        return WatchItem(
            id="probe",
            brand=args.brand or "",
            name=args.name or args.query or "",
            keywords=(args.query.split() if args.query and args.name else []),
        )
    watch = load_watchlist(cfg)
    if args.id:
        for w in watch:
            if w.id == args.id:
                return w
        print(f"[probe] no watch item with id={args.id!r}")
        return None
    return watch[0] if watch else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Probe a single price source")
    ap.add_argument("source", choices=registry_keys(), help="source key")
    ap.add_argument("--id", help="watch item id from data/watchlist.json")
    ap.add_argument("--brand", help="brand for an ad-hoc query")
    ap.add_argument("--name", help="product name for an ad-hoc query")
    ap.add_argument("--query", help="free-text query (brand+name+keywords)")
    ap.add_argument("--limit", type=int, default=5, help="max offers to show")
    ap.add_argument("--json", action="store_true", help="print raw JSON")
    args = ap.parse_args(argv)

    cfg = load_config()
    conn = build_connector(cfg, args.source)
    if conn is None:
        print(f"[probe] unknown source {args.source!r}")
        return 2
    if not conn.available():
        print(f"[probe] source '{args.source}' is not available yet — "
              f"{_ENV_HINTS.get(args.source, '')}")
        return 3

    watch = _pick_watch(cfg, args)
    if watch is None:
        print("[probe] no product to query (use --id, or --name/--query)")
        return 4

    q = f"{watch.brand} {watch.name}".strip()
    print(f"[probe] source={conn.name}  query=\"{q}\"")
    try:
        offers = conn.search(watch) or []
    except Exception as exc:  # noqa: BLE001 - surface any connector failure
        print(f"[probe] search raised: {type(exc).__name__}: {exc}")
        return 5

    offers = sorted(offers, key=lambda o: o.price)[: args.limit]
    if args.json:
        print(json.dumps([o.to_dict() for o in offers], indent=2, ensure_ascii=False))
    else:
        if not offers:
            print("[probe] no offers returned (check query, min_match_score, or quotas)")
        for o in offers:
            print(f"  {o.price:>9.2f} {o.currency}  {o.source:<14} "
                  f"size={str(o.size or '-'):<7} color={str(o.color or '-'):<8} "
                  f"score={o.match_score:.2f}")
            print(f"    {o.title[:88]}")
            print(f"    {o.url}")
    print(f"[probe] {len(offers)} offer(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
