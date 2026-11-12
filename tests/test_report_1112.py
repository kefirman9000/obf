"""Fixes from the 11/12 report: the volatility smile, windfall-capped scores, the opening rush."""
from collections import deque
from datetime import datetime, timedelta, timezone

import engine as E


def _ny(h, m):
    d = datetime(2026, 11, 12, h, m, tzinfo=timezone.utc)
    return (d + timedelta(hours=E._ny_offset(d))).timestamp()


def test_smile_prices_far_puts_dearer():
    E.SKEW_FIT.pop("ZZZ", None)
    assert E.smile("ZZZ", 100, 100) == 1.0
    assert E.smile("ZZZ", 90, 100) > 1.2      # 10% below the stock: crash insurance costs more
    assert 1.0 < E.smile("ZZZ", 110, 100) < E.smile("ZZZ", 90, 100)
    assert E.smile("ZZZ", 10, 100) <= 2.2     # held in a sane range
    # the 11/12 NVDA put: flat volatility priced it near $67, the smile prices it well above that
    T = 9.1 / 365
    flat = E.bs_price(175.14, 158, T, 0.52, "put") * 100
    smiled = E.bs_price(175.14, 158, T, E.strike_vol("ZZZ", 158, 175.14, 0.52), "put") * 100
    assert flat < 70 and smiled > 1.5 * flat


def test_learn_skew_from_chain():
    S, now = 100.0, E.time.time()
    exp = now + 7 * 86400
    rows = []
    for K in range(80, 121, 2):
        k = E.math.log(K / S)
        iv = 0.5 * (1 + (3.0 * -k if k < 0 else 0.5 * k))
        rows.append(dict(K=float(K), exp=exp, type="put" if K <= S else "call", iv=iv))
    fit = E.learn_skew("ZZY", rows, S)
    assert fit and abs(fit[0] - 3.0) < 0.2 and abs(fit[1] - 0.5) < 0.2
    E.SKEW_FIT.pop("ZZY", None)


def test_windfall_doesnt_carry_a_score():
    class V:
        pass
    v = V()
    v.eq = deque([1000.0] * 9 + [1900.0], maxlen=10)
    v.age = 50
    v.windfalls = [[48, 760.0]]
    assert E.windfall_excess(v) == 760.0
    v.windfalls = [[30, 760.0]]  # out of the scoring window: no longer taken off
    assert E.windfall_excess(v) == 0.0


def test_opening_rush():
    assert E.opening_rush(_ny(9, 30) + 35)
    assert not E.opening_rush(_ny(9, 40))
    assert E.open_spread_mult(_ny(9, 31)) == 2.0
    assert E.open_spread_mult(_ny(9, 40)) == 1.5
    assert E.open_spread_mult(_ny(11, 0)) == 1.0

