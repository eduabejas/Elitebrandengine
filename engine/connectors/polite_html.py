"""Polite HTML base connector — compliant scraping for sources without an API
or affiliate feed.

This is deliberately a *base class*, not a ready-made scraper: real scrapers are
site-specific and brittle, so you subclass this and implement ``search`` for a
particular store — but only where the site's Terms of Service and robots.txt
permit it.

The rules this base enforces (and that the whole project commits to):

* **Respect robots.txt** — ``allowed()`` refuses disallowed paths.
* **Identify yourself** — a truthful User-Agent with contact info.
* **Rate-limit** — a minimum delay between requests to the same host.
* **Never defeat protections** — if a page returns a CAPTCHA/anti-bot
  challenge or 403/429, we BACK OFF and skip. We do not rotate identities,
  solve CAPTCHAs, or spoof to evade detection. That path is legally risky
  (ToS/CFAA/DMCA) and technically unsustainable; see
  docs/ENFOQUE-LEGAL-Y-COMO-LO-HACE-HONEY.md.
"""

from __future__ import annotations

import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

from ..models import WatchItem
from .base import Connector

# Truthful, contactable UA. Change the URL to your own project/contact page.
USER_AGENT = "EliteBrandEngine/1.0 (+https://github.com/; price comparison; contact: set-me@example.com)"


class BlockedError(RuntimeError):
    """Raised when a source signals we should stop (403/429/CAPTCHA)."""


class PoliteHtmlConnector(Connector):
    name = "PoliteHTML"

    def __init__(self, cfg, settings):
        super().__init__(cfg, settings)
        self.min_delay = float(self.settings.get("min_delay_seconds", 3.0))
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_hit: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    def _robot(self, url: str) -> urllib.robotparser.RobotFileParser:
        host = urlparse(url).netloc
        rp = self._robots.get(host)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{urlparse(url).scheme}://{host}/robots.txt")
            try:
                rp.read()
            except OSError:
                # If robots.txt is unreachable, be conservative: disallow.
                rp.parse(["User-agent: *", "Disallow: /"])
            self._robots[host] = rp
        return rp

    def allowed(self, url: str) -> bool:
        """True only if robots.txt permits our UA to fetch this URL."""
        try:
            return self._robot(url).can_fetch(USER_AGENT, url)
        except Exception:  # noqa: BLE001 - any robots error => be safe, disallow
            return False

    def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host, 0.0)
        wait = self.min_delay - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.time()

    def fetch(self, url: str) -> str:
        """Fetch a URL politely, or raise. Honours robots.txt and rate limits."""
        if not self.allowed(url):
            raise BlockedError(f"robots.txt disallows {url}")
        host = urlparse(url).netloc
        self._throttle(host)
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
        if resp.status_code in (401, 403, 429) or _looks_like_challenge(resp):
            # The site is telling us to stop. Respect it — do not evade.
            raise BlockedError(f"{resp.status_code} / challenge at {url}; backing off")
        resp.raise_for_status()
        return resp.text

    def search(self, watch: WatchItem):  # pragma: no cover - abstract-ish base
        raise NotImplementedError(
            "PoliteHtmlConnector is a base class; subclass it for a specific, "
            "ToS-permitted store and implement search()."
        )


def _looks_like_challenge(resp: requests.Response) -> bool:
    body = (resp.text or "")[:4000].lower()
    markers = ("captcha", "verify you are human", "cf-challenge", "are you a robot",
               "px-captcha", "unusual traffic")
    return any(m in body for m in markers)
