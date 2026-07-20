"""Lightweight, thread-safe run metrics + observability.

Records per-connector timing / offer counts / errors and per-phase durations so
we can *see* where a run spends its time as sources grow, and enforce a per-
source **time budget** (a soft circuit breaker: a slow source stops being called
once it has eaten its budget, instead of stalling the whole run).
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.connectors: dict[str, dict] = {}
        self.phases: dict[str, float] = {}
        self.started = time.monotonic()

    def record_connector(self, name: str, seconds: float, offers: int,
                         error: bool = False) -> None:
        with self._lock:
            m = self.connectors.setdefault(
                name, {"calls": 0, "offers": 0, "errors": 0, "seconds": 0.0})
            m["calls"] += 1
            m["offers"] += offers
            m["errors"] += 1 if error else 0
            m["seconds"] = round(m["seconds"] + seconds, 3)

    def over_budget(self, name: str, budget: float) -> bool:
        if not budget or budget <= 0:
            return False
        with self._lock:
            m = self.connectors.get(name)
            return bool(m and m["seconds"] >= budget)

    def phase(self, name: str, seconds: float) -> None:
        with self._lock:
            self.phases[name] = round(seconds, 3)

    def elapsed(self) -> float:
        return round(time.monotonic() - self.started, 3)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "phases": dict(self.phases),
                "connectors": {k: dict(v) for k, v in self.connectors.items()},
            }


@contextmanager
def timed(metrics: Metrics, phase: str):
    t = time.monotonic()
    try:
        yield
    finally:
        metrics.phase(phase, time.monotonic() - t)
