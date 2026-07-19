"""Seed backdated demo price history so the website's sparklines look real.

This is a DEMO helper, not part of production. It clears data/history and
regenerates ~30 days of synthetic observations using the sample connector, then
you run ``python -m engine.run`` to produce today's snapshot on top.

    python scripts/seed_demo.py [days]
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

# allow running as `python scripts/seed_demo.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import load_config          # noqa: E402
from engine.connectors.sample import SampleConnector  # noqa: E402
from engine.models import PricePoint            # noqa: E402
from engine.store import append_history, load_watchlist  # noqa: E402


def main(days: int = 30) -> None:
    cfg = load_config()
    watch = load_watchlist(cfg)

    # Wipe any existing history for a clean, reproducible demo.
    hist_dir = cfg.path("history_dir")
    if hist_dir.exists():
        for f in hist_dir.glob("*.jsonl"):
            f.unlink()
    ledger = cfg.path("alerts_ledger")
    if ledger.exists():
        ledger.unlink()

    for days_ago in range(days, 0, -1):
        d = (date.today() - timedelta(days=days_ago)).isoformat()
        conn = SampleConnector(cfg, {"as_of": d})
        ts = f"{d}T12:00:00+00:00"
        for w in watch:
            best_by_source: dict[str, float] = {}
            variant: dict[str, tuple] = {}
            for o in conn.search(w):
                if o.source not in best_by_source or o.price < best_by_source[o.source]:
                    best_by_source[o.source] = o.price
                    variant[o.source] = (o.size, o.color, o.condition)
            points = [
                PricePoint(ts=ts, source=src, price=price,
                           size=variant[src][0], color=variant[src][1],
                           condition=variant[src][2])
                for src, price in best_by_source.items()
            ]
            append_history(cfg, w.id, points)

    print(f"Seeded {days} days of history for {len(watch)} products into {hist_dir}")
    print("Now run:  python -m engine.run --no-email")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    main(n)
