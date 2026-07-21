"""Unit tests for the decision brain (buy / wait / hold).

Runnable with pytest, or directly: ``python -m tests.test_brain``.
"""

from __future__ import annotations

from engine.brain import percentile_rank, price_stats, recommend
from engine.credibility import Credibility


def _cred(implausible=False, tier="cult", cc="authorized", credibility=1.0):
    return Credibility(tier, cc, 40.0, credibility, implausible, None)


def _rec(disc, price, hist, cred, is_off=False, window=None):
    return recommend(disc, price, hist, cred, is_offseason=is_off,
                     sale_window=window, min_discount=15, min_points=4, match_score=1.0)


def test_price_stats_and_percentile():
    assert price_stats([]) is None
    s = price_stats([100, 200, 300])
    assert s["min"] == 100 and s["median"] == 200 and s["n"] == 3
    assert percentile_rank([100, 200, 300], 90) == 0.0
    assert percentile_rank([100, 200, 300], 250) == round(2 / 3, 2)


def test_implausible_is_hold():
    rec, flash, conf, note, pr = _rec(50, 150, [], _cred(implausible=True))
    assert rec == "hold"


def test_buy_at_historical_low():
    rec, *_ = _rec(35, 180, [250, 255, 248, 252], _cred())
    assert rec == "buy"


def test_wait_when_mediocre_vs_history():
    rec, *_ = _rec(30, 200, [140, 150, 145, 155], _cred())
    assert rec == "wait"


def test_below_min_discount_is_hold():
    rec, *_ = _rec(5, 200, [140, 150, 145, 155], _cred())
    assert rec == "hold"


def test_flash_for_cult_authorized_offseason():
    rec, flash, *_ = _rec(35, 180, [250, 255, 248, 252],
                          _cred(tier="cult", cc="authorized"), is_off=True)
    assert flash is True and rec == "buy"


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} test(s) passed")


if __name__ == "__main__":
    _run()
