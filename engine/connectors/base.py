"""Connector interface.

A *connector* knows how to query one source (eBay, Amazon, an affiliate feed,
a brand store) for a given watch item and return normalised :class:`Offer`
objects. Connectors must be *polite and legitimate*: use official APIs and
affiliate datafeeds where they exist, honour robots.txt and rate limits, and
identify themselves. They must never attempt to defeat CAPTCHAs or anti-bot
controls — see docs/ENFOQUE-LEGAL-Y-COMO-LO-HACE-HONEY.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Config
from ..models import Offer, WatchItem


class Connector(ABC):
    #: Human-readable label used as the offer's ``source`` ("website encontrado").
    name: str = "source"

    def __init__(self, cfg: Config, settings: dict):
        self.cfg = cfg
        self.settings = settings or {}

    def status_note(self) -> str | None:
        """Why this source produced nothing, in one line (None = healthy).

        Surfaced in status.json so a failed run is diagnosable from a single
        small file instead of a full CI log dump.
        """
        return None

    def available(self) -> bool:
        """Whether this connector has what it needs to run (keys, feeds, ...).

        Default: available. API connectors override this to check credentials
        so a missing key downgrades gracefully instead of crashing the run.
        """
        return True

    @abstractmethod
    def search(self, watch: WatchItem) -> list[Offer]:
        """Return candidate offers for ``watch`` (may be empty)."""
        raise NotImplementedError
