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



def _sell(why, held, pc, trail=0.0, tf=1):
    return dict(side="sell", why=why, held=held, contract={"type": "call"}, tf=tf, trail=trail), pc


def test_farm_learns_trail_and_pace_lessons():
    from test_proving import farm
    t, _ = farm()
    for _ in range(E.LESSON_MIN):
        t.learn_lesson(*_sell("its trailing stop (5%)", 30, -12.0, trail=5, tf=1))
        t.learn_lesson(*_sell("its own profit target", 30, 6.0, trail=0, tf=5))
    lv = t.lesson_view()
    assert lv["trail"][0] == 12 and lv["pace"][0] == 3
    t.rng.seed(1)
    eggs = [t.lesson_traits({"trail": 4.0}) for _ in range(200)]
    assert any("trail" not in e for e in eggs) and any(e.get("trail", 0) >= 12 for e in eggs)
    assert any(e.get("trail") == 4.0 for e in eggs)  # about half keep testing the other way
    paces = [t.lesson_tf(1) for _ in range(200)]
    assert any(p >= 3 for p in paces) and 1 in paces


def test_bot_tunes_its_own_exits():
    from test_proving import farm, plain
    t, _ = farm()
    v = plain(t)
    v.traits = {"trail": 6.0}
    for _ in range(E.SELF_TUNE_MIN):
        t.note_habit(v, {"why": "its trailing stop (6%)", "held": 40}, -10.0)
        t.note_habit(v, {"why": "its own profit target", "held": 40}, 8.0)
    assert "widened" in (t.self_tune(v) or "") and v.traits["trail"] == 9.0
    assert t.self_tune(v) is None  # its record starts over: judged again on new trades
    v.traits = {"trail": 25.0}
    for _ in range(E.SELF_TUNE_MIN):
        t.note_habit(v, {"why": "its trailing stop (25%)", "held": 40}, -10.0)
        t.note_habit(v, {"why": "RSI said sell", "held": 40}, 8.0)
    assert "dropped" in t.self_tune(v) and "trail" not in v.traits
    v.habits = {}
    for _ in range(E.SELF_TUNE_MIN):
        t.note_habit(v, {"why": "RSI said sell", "held": 3}, -9.0)
        t.note_habit(v, {"why": "RSI said sell", "held": 60}, 4.0)
    assert "holds at least" in t.self_tune(v) and v.traits["minhold"] >= 2
    t.o["self_tune"] = False
    v.traits, v.habits = {"trail": 6.0}, {"trail": [9, -90.0], "other": [9, 72.0]}
    assert t.self_tune(v) is None
