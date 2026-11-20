"""Fixes from the 11/19 report: implied volatility kept past a weekend, the opening calm, affordable tickers, and the
far-out lesson reaching bots already in the farm."""
import time
from datetime import datetime, timedelta, timezone

import engine as E


def _ny(h, m):
    d = datetime(2026, 11, 16, h, m, tzinfo=timezone.utc)
    return (d + timedelta(hours=E._ny_offset(d))).timestamp()


def _held_call(vol_now_measured, bought_on_implied):
    old = dict(E.IV_HINT)
    E.IV_HINT.clear()
    E.IV_HINT["XYZ"] = 0.80
    try:
        sim = E.make_sim(10000.0, 0.0, 0.5, genes={})
        sim.now = time.time()
        if not bought_on_implied:
            E.IV_HINT.clear()
            sim.vol_src["XYZ"] = 0.80
        assert sim.buy("XYZ", 57.0, 0)
        E.IV_HINT.clear()  # a restart: the market's implied volatility isn't known yet
        sim.vol_src["XYZ"] = vol_now_measured
        return sim
    finally:
        E.IV_HINT.clear()
        E.IV_HINT.update(old)


def test_a_held_contract_keeps_the_implied_volatility_it_was_bought_at():
    sim = _held_call(0.57, bought_on_implied=True)
    assert sim.opt["XYZ"].get("iv") is True
    assert sim._vol("XYZ") == sim.opt["XYZ"]["vol"] == 0.8
    # no fake "collapse" from the switch to measured volatility (0.80 -> 0.57 is 29%)
    assert E.option_exit(sim, "XYZ", 57.0, {"ivdrop": 12}) is None


def test_contracts_bought_on_measured_volatility_still_follow_it():
    sim = _held_call(0.40, bought_on_implied=False)
    assert not sim.opt["XYZ"].get("iv")
    assert sim._vol("XYZ") == 0.40  # (backtests: their collapse exit keeps working)
    assert E.option_exit(sim, "XYZ", 57.0, {"ivdrop": 40}) == "ivdrop"


def test_implied_volatility_is_kept_past_a_long_weekend():
    friday_close_to_tuesday_open = (3 * 24 + 17.5) * 3600
    assert E.IV_KEEP_S > friday_close_to_tuesday_open


def test_opening_calm_and_deep_stops():
    old = E.OPEN_CALM[0]
    try:
        E.tournament_opts(dict(E.DEFAULT_SETTINGS, open_calm=5))
        assert E.opening_calm(_ny(9, 31)) and not E.opening_calm(_ny(9, 36)) and not E.opening_calm(_ny(12, 0))
        E.tournament_opts(dict(E.DEFAULT_SETTINGS, open_calm=0))
        assert not E.opening_calm(_ny(9, 31))  # 0 = off
    finally:
        E.OPEN_CALM[0] = old
    assert E.deep_stop(10) == 20 and E.deep_stop(30) == 60 and E.deep_stop(45) == 60 and E.deep_stop(80) == 80


def test_unaffordable_tickers_rank_last():
    cheap = dict(coin="RIVN", price=11.4, volume_usd=2e8, change_24h=2.0)
    dear = dict(coin="NVDA", price=151.0, volume_usd=3e10, change_24h=2.0)  # far busier, but $500+ a contract
    assert E.scout_score(cheap, 100)[0] > E.scout_score(dear, 100)[0]
    assert E.scout_score(dear, 1000)[0] > E.scout_score(cheap, 1000)[0]  # a big enough trade size opens it up again


def test_old_settings_move_to_the_tighter_far_out_limit_once():
    s = E.merge_settings({"max_otm": 15.0, "defaults_rev": 2})
    assert s["max_otm"] == 10.0 and s["defaults_rev"] == E.DEFAULT_SETTINGS["defaults_rev"]
    assert E.merge_settings({"max_otm": 0, "defaults_rev": 2})["max_otm"] == 0  # no limit, on purpose: kept
    assert E.merge_settings(dict(s, max_otm=20.0))["max_otm"] == 20.0  # chosen after the move: kept
    assert E.DEFAULT_SETTINGS["max_otm"] == 10.0 and E.DEFAULT_SETTINGS["open_calm"] == 5


def test_far_out_lesson_reaches_half_the_existing_bots():
    from test_proving import farm, plain
    t, _ = farm()
    t.lessons = {}  # (only these trades)
    for _ in range(E.LESSON_MIN):
        t.learn_lesson(dict(side="sell", why="its own profit target", held=30, contract={"type": "call", "otm0": 3}), 6.0)
        t.learn_lesson(dict(side="sell", why="its own profit target", held=30, contract={"type": "call", "otm0": 20}), -10.0)
    assert t.lesson_view()["maxotm"][0] == 5
    t._adopt_budget = 10
    even = plain(t)
    odd = next(x for x in t.vars if x is not even and not E.is_scalp(x.name) and not E.is_kami(x))
    even.uid, odd.uid = 4, 5
    for b in (even, odd):
        b.risk = E.clean_risk({"sl": 30.0})
        b.traits = {"minhold": 3}
    assert "within" in (t.self_tune(even) or "") and 4 <= even.traits["maxotm"] <= 6
    assert t.self_tune(odd) is None and "maxotm" not in odd.traits  # the comparison side keeps buying as before
    assert t.self_tune(even) is None  # each lesson only once
