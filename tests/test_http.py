"""Unit tests for the resilient HTTP helper (no real network).

Runnable with pytest, or directly: ``python -m tests.test_http``.
"""

from __future__ import annotations

import requests

import engine.http as H
from engine.http import HttpError, RateLimiter, retry_request

# Stub out real sleeping; record the requested delays instead.
_SLEPT: list[float] = []
H.SLEEP = lambda s: _SLEPT.append(s)


class FakeResp:
    def __init__(self, status, text="", headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}


def make_send(outcomes):
    """A send() that yields the given outcomes (int status, FakeResp, or an
    Exception to raise) in order, repeating the last one."""
    state = {"n": 0}

    def send():
        i = state["n"]
        state["n"] += 1
        o = outcomes[i] if i < len(outcomes) else outcomes[-1]
        if isinstance(o, Exception):
            raise o
        return o if isinstance(o, FakeResp) else FakeResp(o)

    send.state = state
    return send


def test_retries_then_success():
    s = make_send([503, 503, 200])
    r = retry_request(s, attempts=3, base_delay=0.01)
    assert r.status_code == 200 and s.state["n"] == 3


def test_non_transient_no_retry():
    s = make_send([404])
    r = retry_request(s, attempts=3, base_delay=0.01)
    assert r.status_code == 404 and s.state["n"] == 1


def test_exhausts_and_raises():
    s = make_send([503])
    try:
        retry_request(s, attempts=3, base_delay=0.01)
        assert False, "expected HttpError"
    except HttpError as e:
        assert e.status == 503 and s.state["n"] == 3


def test_connection_error_retried():
    s = make_send([requests.ConnectionError("boom"), 200])
    r = retry_request(s, attempts=3, base_delay=0.01)
    assert r.status_code == 200 and s.state["n"] == 2


def test_retry_after_header_honoured():
    _SLEPT.clear()
    s = make_send([FakeResp(429, headers={"Retry-After": "2"}), 200])
    r = retry_request(s, attempts=3, base_delay=0.01)
    assert r.status_code == 200
    assert any(1.5 <= x <= 3.0 for x in _SLEPT), _SLEPT


def test_rate_limiter_spaces_requests():
    _SLEPT.clear()
    rl = RateLimiter()
    rl.wait("host", 5.0)   # first call: nothing to wait for
    rl.wait("host", 5.0)   # immediate second call: must wait ~5s
    assert _SLEPT and _SLEPT[-1] >= 4.5, _SLEPT


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
