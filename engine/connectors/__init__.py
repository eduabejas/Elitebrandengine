"""Connector registry.

``build_connectors`` reads ``config.yml`` and returns the connectors that are
both *enabled* and *available* (have their credentials/feeds). Missing
credentials downgrade gracefully — the run continues with whatever is ready.
"""

from __future__ import annotations

from ..config import Config
from .affiliate_feed import AffiliateFeedConnector
from .amazon import AmazonConnector
from .base import Connector
from .ebay import EbayConnector
from .sample import SampleConnector

_REGISTRY = {
    "sample": SampleConnector,
    "ebay": EbayConnector,
    "amazon": AmazonConnector,
    "affiliate_feed": AffiliateFeedConnector,
}


def build_connectors(cfg: Config) -> list[Connector]:
    sources = cfg.get("sources", {}) or {}
    built: list[Connector] = []
    for key, cls in _REGISTRY.items():
        settings = sources.get(key, {}) or {}
        if not settings.get("enabled"):
            continue
        conn = cls(cfg, settings)
        if not conn.available():
            print(f"[connectors] '{key}' enabled but not available "
                  f"(missing credentials/feeds) — skipping")
            continue
        built.append(conn)
    return built


__all__ = ["build_connectors", "Connector"]
