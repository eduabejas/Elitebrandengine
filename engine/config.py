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
        "promos": "data/promos.json",
        "web_data": "web/data",
    },
    "detection": {
        # A drop of at least this % below the regular price is a deal (objective
        # sweet spot is 15-60%).
        "min_discount_pct": 15.0,
        # Above this %, a "discount" is treated as SUSPECT (likely a wrong match
        # or price error) and only surfaces if the match is near-certain.
        "suspect_discount_pct": 68.0,
        # Regular (non-sale) price = this percentile of recent prices (plus MSRP
        # / believable list price). Guards against sale-dragged medians.
        "baseline_percentile": 85.0,
        "baseline_window_days": 120,
        # Need at least this many history points before statistical baselining.
        "min_history_points": 4,
        # Only consider new, in-stock, fresh offers as "the same article".
        "require_in_stock": True,
        "include_used": False,
        "include_refurbished": True,   # outlet/refurb count (with a small penalty)
        "max_offer_age_days": 3,
        # Don't re-email the same deal within this many days.
        "alert_ttl_days": 7,
        # Match confidence required to trust an offer belongs to a product...
        "min_match_score": 0.6,
        # ...and the higher bar required to trust an unusually large discount.
        "suspect_min_match_score": 0.9,
        # Optional per-category threshold overrides (rarely-discounted lines):
        # {"Hardshell": 12, "Down Jacket": 15}
        "category_min_discount": {},
    },
    "search": {
        # standard = US only; expanded = US + Canada + Europe. European brands
        # (Peak Performance, Helly Hansen, Norrøna, Rab, Mammut…) and Arc'teryx
        # (Canada) are often cheapest in their home market — expanded surfaces it.
        # International shipping is the buyer's known cost and is NOT penalised.
        "scope": "standard",
    },
    "seasonality": {
        # Where the operator/buyers are (drives current-season logic).
        "hemisphere": "north",
        # Extra score for off-season (counter-seasonal) buys.
        "offseason_boost": 12.0,
        # Lower the discount threshold by this × strength when off-season, so we
        # catch end-of-season clearances a little earlier.
        "offseason_discount_relax": 3.0,
    },
    "fx": {
        # Static rates = value of 1 unit in USD. Update when feeds add non-USD
        # sources. All prices are normalised to `base` before comparison.
        "base": "USD",
        "rates": {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "ARS": 0.0011},
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
