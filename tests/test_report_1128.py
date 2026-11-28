"""Fixes from the 11/28 report: the coin-flip check counted replayed history, training camp graduates came back as
copies and were picked on the prices they replay, and the 1 pm close on half days was treated as mid-afternoon."""
from datetime import datetime, timedelta, timezone

import engine as E
from test_control_hold import _farm
from test_proven import make_proven


def _ny(y, mo, d, h, m):
    """A timestamp for h:m New York time on that day."""
    u = datetime(y, mo, d, h, m, tzinfo=timezone.utc)
    return (u + timedelta(hours=E._ny_offset(u))).timestamp()


# ---- half days ----

def test_half_days_are_known():
    assert E.half_day(datetime(2026, 11, 27))       # the day after Thanksgiving (the 11/28 report)
    assert E.half_day(datetime(2025, 11, 28))
    assert not E.half_day(datetime(2026, 11, 20))   # an ordinary Friday in November
    assert not E.half_day(datetime(2026, 11, 25))
    assert E.half_day(datetime(2026, 12, 24))       # Christmas Eve on a Thursday
    assert not E.half_day(datetime(2027, 12, 24))   # ...on a Friday it's the holiday itself
    assert E.half_day(datetime(2025, 7, 3))         # July 3 on a Thursday
    assert not E.half_day(datetime(2026, 7, 3))     # ...on a Friday it's the holiday itself


def test_the_close_is_1_pm_on_a_half_day():
    t = _ny(2026, 11, 27, 12, 54)
    assert E.minutes_to_close(t) == 6 and E.session_minutes(t) == 210
    assert E.minutes_since_open(_ny(2026, 11, 27, 9, 31)) == 1
    assert E.market_hours(t) and not E.market_hours(_ny(2026, 11, 27, 13, 20))
    assert not E.regular_hours(_ny(2026, 11, 27, 13, 20), 60)  # after-close prints aren't candles
    assert E.tod_bucket(_ny(2026, 11, 27, 12, 0)) == "l"
    # ordinary days are unchanged
    t = _ny(2026, 11, 25, 12, 54)
    assert E.minutes_to_close(t) == 186 and E.session_minutes(t) == 390
    assert E.market_hours(_ny(2026, 11, 25, 13, 20)) and E.regular_hours(_ny(2026, 11, 25, 13, 20), 60)
    assert E.minutes_since_open(_ny(2026, 11, 25, 9, 31)) == 1 and E.opening_rush(_ny(2026, 11, 25, 9, 31))


def test_no_new_contracts_in_the_closing_minutes_of_a_half_day():
    t, closes = _farm(n=200)
    v = next(x for x in t.vars if not E.is_kami(x))
    c = list(closes)[0]
    late = {c: {"t": [_ny(2026, 11, 27, 12, 54)]}}
    mid = {c: {"t": [_ny(2026, 11, 25, 12, 54)]}}
    assert E._veto(v, "closing", 48, c, closes, t.n, late, list(closes))  # 6 minutes before the 1 pm close
    assert not E._veto(v, "closing", 48, c, closes, t.n, mid, list(closes))


# ---- the coin-flip check and replayed history ----

def test_replayed_trades_stay_out_of_the_coin_flip_check_and_the_proven_count():
    t, closes = _farm(n=900)
    before = list(t.control_book["farm"])
    v = None
    for src in sorted(t.vars, key=lambda x: -(x.wins + x.losses)):  # a copy of a busy bot, replayed on the same prices
        v = t.add_variant(src.name, dict(src.params), closes, 1.0, note="test", origin="added", risk=dict(src.risk),
                          traits=dict(src.traits), vetoes=dict(src.vetoes), layers=src.layers)
        if v.wins + v.losses:
            break
    assert v is not None and v.wins + v.losses > 0  # its replay finished some trades
    assert v.replayed == v.wins + v.losses
    assert list(t.control_book["farm"]) == before  # ...and none of them count against the coin-flip bots
    make_proven(t, v)  # 12 finished trades and 20 on exam days
    t.o["proven_trades"] = 30
    v.replayed = 12  # ...but its 12 finished trades are all replayed
    assert any("more finished trade" in g for g in t.proven_gaps(v))
    v.replayed = 0
    assert not any("more finished trade" in g for g in t.proven_gaps(v))


def test_replayed_count_is_saved_and_restored():
    t, closes = _farm(n=600)
    v = t.add_variant("EMA crossover", {"fast": 6, "slow": 21}, closes, 1.0, note="test", origin="added")
    st = t.to_state()
    t2 = E.Tournament(list(t.coins), 10000.0, 0.006, 0.1, 24, opts=t.o, cap=30)
    assert t2.restore(st)
    assert next(x for x in t2.vars if x.uid == v.uid).replayed == v.replayed


# ---- graduates that are already on the farm ----

def test_a_graduate_already_on_the_farm_isnt_added_again():
    t, closes = _farm(n=400)
    g = dict(name="Bollinger bands", params={"n": 16, "k": 1.08}, risk={"sl": 0.0, "tp": 5.4}, traits={"minhold": 96})
    a = t.add_variant(g["name"], g["params"], closes, 1.0, note="camp", origin="training camp", risk=g["risk"],
                      traits=g["traits"])
    n = len(t.vars)
    for origin in ("training camp", "free roam"):
        assert t.add_variant(g["name"], g["params"], closes, 1.0, note="camp", origin=origin, risk=g["risk"],
                             traits=g["traits"]) is None
    assert a in t.vars and len(t.vars) == n  # nobody was pushed off the farm for the copy either
    b = t.add_variant(g["name"], {"n": 17, "k": 1.08}, closes, 1.0, note="camp", origin="training camp",
                      risk=g["risk"], traits=g["traits"])
    assert b is not None  # a different bot still joins
