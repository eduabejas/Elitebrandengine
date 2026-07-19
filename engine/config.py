"""Configuration loading.

Reads ``config.yml`` (non-secret settings) and layers environment variables on
top for anything sensitive (API keys, SMTP passwords). Secrets NEVER live in
the repo — on GitHub they arrive as Actions secrets exposed as env vars.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


DEFAULTS: dict[str, Any] = {
    "currency": "USD",
    "paths": {
        "watchlist": "data/watchlist.json",
        "history_dir": "data/history",
        "alerts_ledger": "data/alerts_ledger.json",
        "web_data": "web/data",
    },
    "detection": {
        # A drop of at least this % below the reference price is a deal.
        "min_discount_pct": 15.0,
        # Need at least this many history points before statistical detection.
        "min_history_points": 4,
        # Don't re-email the same deal within this many days.
        "alert_ttl_days": 7,
        # Match confidence required to trust an offer belongs to a product.
        "min_match_score": 0.6,
    },
    "sources": {
        # Demo source ships enabled so the whole system works with zero setup.
        "sample": {"enabled": True},
        "ebay": {"enabled": False, "marketplace": "EBAY_US", "limit": 8},
        "amazon": {"enabled": False, "marketplace": "www.amazon.com", "region": "us-east-1"},
        "affiliate_feed": {"enabled": False, "feeds": []},
    },
    "email": {
        "enabled": True,
        "subject_prefix": "[Elite Brand Engine] ",
        "from_name": "Elite Brand Engine",
        # recipients can be set here or via ALERT_EMAIL_TO env var
        "to": [],
    },
    "site": {
        "title": "Elite Brand Engine",
        "tagline": "Deal radar for mountaineering & alpinism gear",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    # convenient absolute-path helpers -------------------------------------- #
    def path(self, key: str) -> Path:
        return ROOT / self.get(f"paths.{key}")

    @property
    def currency(self) -> str:
        return self.get("currency", "USD")


def load_config(config_file: str | os.PathLike | None = None) -> Config:
    """Load DEFAULTS <- config.yml <- config.local.yml (if present)."""
    merged = dict(DEFAULTS)
    for candidate in (config_file, ROOT / "config.yml", ROOT / "config.local.yml"):
        if not candidate:
            continue
        p = Path(candidate)
        if p.exists():
            with open(p, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            merged = _deep_merge(merged, data)

    # Environment overrides for email recipients (handy in CI).
    env_to = os.getenv("ALERT_EMAIL_TO")
    if env_to:
        merged.setdefault("email", {})["to"] = [
            x.strip() for x in env_to.replace(";", ",").split(",") if x.strip()
        ]
    return Config(raw=merged)
