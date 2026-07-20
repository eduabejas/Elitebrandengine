"""Resilient HTTP helper shared by the API connectors.

Wraps ``requests`` with:

* **Retries + exponential backoff** on transient failures (connection errors,
  timeouts, and 429/5xx responses), honouring ``Retry-After`` on 429.
* **Per-host rate limiting** so we stay polite and under API quotas.
* **Sane defaults** (timeout, truthful User-Agent).

Connectors that must rebuild the request each attempt (e.g. Amazon re-signs with
a fresh timestamp) pass a ``send`` closure to :func:`retry_request`; simpler
callers use :func:`get` / :func:`post`.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Callable, Optional
from urllib.parse import urlparse

import requests

DEFAULT_UA = ("EliteBrandEngine/1.0 "
              "(+https://github.com/eduabejas/Elitebrandengine; price comparison)")
TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Indirection so tests can stub out real sleeping.
SLEEP: Callable[[float], None] = time.sleep


class HttpError(RuntimeError):
    """A non-2xx/3xx response we chose to treat as a failure."""

    def __init__(self, status: int, message: str = ""):
        super().__init__(f"HTTP {status}: {message}".strip())
        self.status = status


class RateLimiter:
    """Enforce a minimum interval between requests to the same host.

    Thread-safe: the next slot is reserved atomically under a lock, but the
    actual sleep happens outside it so different hosts never block each other.
    """

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: Optional[str], min_interval: float) -> None:
        if not host or min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            last = self._last.get(host)
            wait_for = 0.0
            if last is not None:
                gap = min_interval - (now - last)
                if gap > 0:
                    wait_for = gap
            self._last[host] = now + wait_for   # reserve the slot
        if wait_for > 0:
            SLEEP(wait_for)


_LIMITER = RateLimiter()


def _parse_retry_after(resp: requests.Response) -> Optional[float]:
    if resp.status_code != 429:
        return None
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return min(float(raw), 60.0)  # only support the seconds form
    except ValueError:
        return None


def retry_request(
    send: Callable[[], requests.Response],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    max_delay: float = 30.0,
    host: Optional[str] = None,
    min_interval: float = 0.0,
    label: str = "request",
) -> requests.Response:
    """Call ``send`` with retries. Returns the first non-transient response.

    Raises the last error (``requests.RequestException`` or :class:`HttpError`)
    if every attempt fails.
    """
    attempts = max(1, attempts)
    last_err: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        _LIMITER.wait(host, min_interval)
        resp: Optional[requests.Response] = None
        try:
            resp = send()
        except requests.RequestException as exc:
            last_err = exc

        if resp is not None:
            if resp.status_code not in TRANSIENT_STATUS:
                return resp
            last_err = HttpError(resp.status_code, (resp.text or "")[:180])
            retry_after = _parse_retry_after(resp)
        else:
            retry_after = None

        if attempt >= attempts:
            break
        if retry_after is not None:
            delay = retry_after
        else:
            delay = min(max_delay, base_delay * (backoff ** (attempt - 1)))
        delay += random.uniform(0, 0.25)
        print(f"[http] {label} failed (attempt {attempt}/{attempts}: {last_err}); "
              f"retrying in {delay:.1f}s")
        SLEEP(min(delay, max_delay))

    raise last_err if last_err else HttpError(0, "no response")


def request(method: str, url: str, *, headers: Optional[dict] = None,
            host: Optional[str] = None, min_interval: float = 0.0,
            timeout: float = 25, attempts: int = 3, **kwargs) -> requests.Response:
    """Convenience wrapper: build + send a fresh request each attempt."""
    hdrs = {"User-Agent": DEFAULT_UA}
    if headers:
        hdrs.update(headers)
    host = host or urlparse(url).netloc
    return retry_request(
        lambda: requests.request(method, url, headers=hdrs, timeout=timeout, **kwargs),
        attempts=attempts, host=host, min_interval=min_interval,
        label=f"{method} {url}",
    )


def get(url: str, **kwargs) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    return request("POST", url, **kwargs)
