"""1.49: the overlord, one model that watches every kind of bot and learns whether a call or a put bought then would
have paid for itself an hour later (watch and report only)."""
import random

import pytest

import engine as E
from test_feature_tests import market

GENES = [(n, dict(E.STRATS[n]["params"]), tf) for n in ("RSI", "Mean reversion", "Momentum", "Bollinger bands", "Breakout",
                                                         "Rate of change", "Stochastic", "MACD") for tf in (1, 3)]


@pytest.fixture(autouse=True)
def _clean():
    saved = {k: dict(v) for k, v in E.OVERLORD.items()}
    E.OVERLORD.clear()
    yield
    E.OVERLORD.clear()
    E.OVERLORD.update(saved)


def _prices(seed, n=6000, trend=False):
    _, ex = market(1, n)
    t = ex["SPY"]["t"]
    rng = random.Random(seed)
    closes, extra = {}, {}
    for j in range(4):
        p, xs, d = 50.0, [], 0.0
        for k in range(n):
            if trend and k % 120 == 0:
                d = rng.choice((-1, 1)) * 0.0006  # two-hour runs up or down: something the bots' signals can see
            p *= 1 + d + rng.gauss(0, 0.0011)
            xs.append(p)
        closes[f"T{j}"] = xs
        extra[f"T{j}"] = dict(h=[x * 1.001 for x in xs], l=[x * 0.999 for x in xs], v=[1000.0] * n, t=t)
    return closes, extra


def _learn(closes, extra):
    res = E.school_study(closes, extra, GENES)
    assert E.merge_overlord(res["overlord"]) == len(res["overlord"]) > 1000
    return E.overlord_status()


def test_on_a_random_walk_it_finds_no_skill():
    st = _learn(*_prices(3))
    assert st["calls"]["hours"] >= E.OL_MIN_EFF
    assert st["calls"]["skill"] < 0.02 and st["puts"]["skill"] < 0.02  # nothing to know, and it doesn't pretend to
    assert st["verdict"].startswith("No skill")


def test_it_learns_a_pattern_the_bots_can_see():
    st = _learn(*_prices(9, trend=True))
    assert st["calls"]["skill"] > 0.1 and st["puts"]["skill"] > 0.1
    assert st["verdict"].startswith("It knows something") and st["calls"]["listens"]


def test_examples_never_look_ahead():
    closes, extra = _prices(5, n=2500)
    full = {(e[0], e[1]): e[2] for e in E.school_study(closes, extra, GENES)["overlord"]}
    cut = 1800  # the same history, ending earlier: every example both have must see exactly the same features
    short = E.school_study({c: p[:cut] for c, p in closes.items()},
                           {c: {k: x[:cut] for k, x in v.items()} for c, v in extra.items()}, GENES)["overlord"]
    assert short
    for e in short:
        assert full[(e[0], e[1])] == e[2]


def test_examples_are_on_a_15_minute_clock_and_each_has_its_hour_ahead():
    closes, extra = _prices(6, n=2000)
    ex = E.school_study(closes, extra, GENES)["overlord"]
    t = extra["T0"]["t"]
    assert all(int(e[0] // 60) % E.OL_STRIDE == 0 for e in ex)
    assert max(e[0] for e in ex) <= t[len(t) - 1 - E.OL_H]


def test_it_can_be_switched_off_and_reads_the_latest_candles():
    closes, extra = _prices(7, n=1500)
    assert E.school_study(closes, extra, GENES, overlord=False)["overlord"] == []
    E.merge_overlord(E.school_study(closes, extra, GENES)["overlord"])
    now = E.overlord_now({c: p[-700:] for c, p in closes.items()},
                         {c: {k: x[-700:] for k, x in v.items()} for c, v in extra.items()}, GENES)
    assert set(now) == set(closes) and all(0 < r["call"] < 1 and 0 < r["put"] < 1 for r in now.values())


def test_it_is_kept_in_the_learning_book_and_shows_in_the_report(tmp_path, monkeypatch):
    pytest.importorskip("tkinter")
    import types

    import main as M
    monkeypatch.setattr(E, "HOME_DIR", str(tmp_path))
    a = types.SimpleNamespace(logs=[], settings=dict(E.DEFAULT_SETTINGS))
    a.learning_path = lambda: M.App.learning_path(a)
    a.save_learning_book = lambda: M.App.save_learning_book(a)
    a.write = lambda msg, tag=None: a.logs.append(msg)
    closes, extra = _prices(8, n=1500)
    res = E.school_study(closes, extra, GENES)
    M.App._school_apply(a, res, "a stretch", False)
    n = E.OVERLORD["b"]["n"]
    assert n == len(res["overlord"]) > 0
    E.OVERLORD.clear()
    M.App.load_learning_book(a)
    assert E.OVERLORD["b"]["n"] == n and E.OVERLORD["s"]["w"]
    d = dict(account={}, farms={}, free_roam=dict(on=False, studies=0, days_trained=[], log=[]),
             overlord=dict(E.overlord_status(), now={"T0": dict(call=0.4, put=0.3, usual_call=0.35, usual_put=0.35)}))
    text = M.App._report_summary(d)
    assert "--- Overlord" in text and "now T0: call 40%" in text
