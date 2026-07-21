"""Unit tests for storage hygiene — the repo IS the database, so it must stay
bounded. Covers price-history retention/downsample and alert-ledger pruning.

Runnable with pytest, or directly: ``python -m tests.test_store``.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.config import DEFAULTS, Config, _deep_merge
from engine.models import PricePoint, now_iso
from engine.store import (
    append_history,
    load_history,
    prune_ledger,
    save_ledger,
    load_ledger,
)


def _cfg(tmp: str, **detection) -> Config:
    raw = _deep_merge(DEFAULTS, {
        "paths": {
            "history_dir": str(Path(tmp) / "history"),      # absolute => ignores ROOT
            "alerts_ledger": str(Path(tmp) / "ledger.json"),
        },
        "detection": detection,
    })
    return Config(raw=raw)


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _pt(ts: str, source: str, price: float) -> PricePoint:
    return PricePoint(ts=ts, source=source, price=price, size="M",
                      color="black", condition="new")


def test_daily_downsample_keeps_latest_per_source_per_day():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, history_daily_downsample=True)
        day = "2026-03-01"
        # Two runs same day/source (06:00 then 18:00) + a second source.
        append_history(cfg, "w", [
            _pt(f"{day}T06:00:00+00:00", "eBay", 100.0),
            _pt(f"{day}T06:00:00+00:00", "REI Co-op", 120.0),
        ])
        append_history(cfg, "w", [
            _pt(f"{day}T18:00:00+00:00", "eBay", 90.0),   # same day+source => wins
        ])
        pts = load_history(cfg, "w")
        assert len(pts) == 2                              # one per source, not 3
        ebay = [p for p in pts if p.source == "eBay"]
        assert len(ebay) == 1 and ebay[0].price == 90.0   # latest kept


def test_many_runs_same_day_stay_bounded():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, history_daily_downsample=True)
        for hour in range(0, 24, 2):                       # 12 runs in one day
            append_history(cfg, "w", [_pt(f"2026-04-01T{hour:02d}:00:00+00:00",
                                          "eBay", 100.0 - hour)])
        pts = load_history(cfg, "w")
        assert len(pts) == 1                               # collapsed to a single day


def test_retention_drops_old_points():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, history_retention_days=180, history_daily_downsample=True)
        append_history(cfg, "w", [
            _pt(_iso(400), "eBay", 200.0),                 # ~13 months old => drop
            _pt(_iso(10), "eBay", 150.0),                  # recent => keep
        ])
        pts = load_history(cfg, "w")
        assert len(pts) == 1 and pts[0].price == 150.0


def test_max_points_hard_cap():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, history_max_points=3, history_daily_downsample=True,
                   history_retention_days=0)               # cap is the only limiter
        # 5 distinct days => 5 points, capped to the most recent 3.
        pts = [_pt(f"2026-05-0{d}T12:00:00+00:00", "eBay", 100.0 + d) for d in range(1, 6)]
        append_history(cfg, "w", pts)
        kept = load_history(cfg, "w")
        assert len(kept) == 3
        assert [p.price for p in kept] == [103.0, 104.0, 105.0]   # newest survive


def test_atomic_write_leaves_no_tmp_and_valid_file():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        append_history(cfg, "w", [_pt(now_iso(), "eBay", 100.0)])
        hist_dir = Path(tmp) / "history"
        assert not list(hist_dir.glob("*.tmp"))            # no partial temp files
        assert (hist_dir / "w.jsonl").exists()
        assert len(load_history(cfg, "w")) == 1


def test_prune_ledger_drops_expired_and_unparsable():
    ledger = {
        "recent": _iso(1),                                 # within TTL => keep
        "old": _iso(30),                                   # past TTL => drop
        "corrupt": "not-a-timestamp",                      # unparsable => drop
    }
    out = prune_ledger(ledger, ttl_days=7)
    assert set(out) == {"recent"}


def test_prune_ledger_ttl_zero_keeps_all():
    ledger = {"a": _iso(1), "b": _iso(999)}
    assert prune_ledger(ledger, ttl_days=0) == ledger


def test_ledger_roundtrip_atomic():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        save_ledger(cfg, {"k": now_iso()})
        assert not list(Path(tmp).glob("*.tmp"))
        assert set(load_ledger(cfg)) == {"k"}


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
