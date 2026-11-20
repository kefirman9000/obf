"""1.48, from the 11/19 report: coin-flip control bots (does the farm's picking beat chance?), a minimum hold before
anything but a target, a deep loss or the close sells a contract, and fewer bots that live longer."""
import json
import random

import pytest

import engine as E
from test_feature_tests import market


@pytest.fixture(autouse=True)
def _hold_back():
    old = E.MIN_HOLD[0]
    yield
    E.MIN_HOLD[0] = old


def _held(trail=5.0, sl=20.0, tp=200.0, hold_s=5 * 60, extra_traits=None):
    """A bot holding a call on SPY bought hold_s seconds before the candle it's about to decide on."""
    closes, ex = market(3, 300)
    i = 200
    tr = dict(trail=trail, otm=1.0, **(extra_traits or {}))
    v = E._bt_bot(dict(name="RSI", params=dict(E.STRATS["RSI"]["params"]), tf=1, risk=dict(sl=sl, tp=tp), traits=tr,
                       uid=2), ["SPY"], 10000.0, 0.0, 0.1, 0.0)
    x = E.slice_extra(ex, i + 1)
    now = E.data_now(x, ["SPY"])
    v.sim.now = now - hold_s
    v.sim.genes = v.traits
    assert v.sim.buy("SPY", closes["SPY"][i], i)
    v.sim.opt["SPY"]["t0"] = now - hold_s
    v.since["SPY"] = i - 1
    return v, {"SPY": E.View(closes["SPY"], i + 1)}, x, i


def _sold(v, cl, x, i):
    return [t["why"] for c, t in E.bot_step(v, cl, i, ["SPY"], x) if t["side"] == "sell"]


def test_young_contracts_wait_for_the_minimum_hold():
    E.MIN_HOLD[0] = 60
    v, cl, x, i = _held()
    v.hi["SPY"] = 10 ** 6  # far above: its trailing stop would fire at once
    assert _sold(v, cl, x, i) == []  # 5 minutes old: the trailing stop waits
    E.MIN_HOLD[0] = 0
    v, cl, x, i = _held()
    v.hi["SPY"] = 10 ** 6
    assert any("trailing stop" in w for w in _sold(v, cl, x, i))  # switched off: as before
    E.MIN_HOLD[0] = 60
    v, cl, x, i = _held(hold_s=61 * 60)
    v.hi["SPY"] = 10 ** 6
    assert any("trailing stop" in w for w in _sold(v, cl, x, i))  # held over an hour: free to go


def test_a_deep_loss_and_a_profit_target_still_sell_a_young_contract():
    E.MIN_HOLD[0] = 60
    v, cl, x, i = _held(trail=0, sl=20.0)
    v.sim.cost["SPY"] *= 3  # down about 67%: past twice its 20% stop
    assert any("safety stop" in w for w in _sold(v, cl, x, i))
    v, cl, x, i = _held(trail=0, sl=20.0)
    v.sim.cost["SPY"] *= 1.3  # down about 23%: past its stop, short of a deep loss
    assert _sold(v, cl, x, i) == []
    v, cl, x, i = _held(trail=0, sl=0, tp=10.0)
    v.sim.cost["SPY"] *= 0.5  # up 100%
    assert any("profit target" in w for w in _sold(v, cl, x, i))


def test_scalpers_and_kamikazes_are_exempt():
    E.MIN_HOLD[0] = 60

    class S:
        now = 1_000_000.0
        opt = {"SPY": {"t0": 1_000_000.0 - 60}}
    assert E.too_young(S, "SPY", {})
    assert not E.too_young(S, "SPY", {"flatby": 10}) and not E.too_young(S, "SPY", {"kami": 1})
    E.MIN_HOLD[0] = 0
    assert not E.too_young(S, "SPY", {})


def _farm(n=1100, **opts):
    closes, extra = market(102, n)
    o = E.opts_for_bars(E.tournament_opts(dict(E.DEFAULT_SETTINGS, **opts)), 60)
    t = E.Tournament(list(closes), 10000.0, 0.006, 0.1, 24, opts=o, cap=30)
    for i in range(E.WARM, n):
        t.step({c: E.View(closes[c], i + 1) for c in closes}, E.slice_extra(extra, i + 1))
    return t, closes


def test_coin_flip_bots_run_beside_the_farm_and_stay_out_of_it():
    t, _ = _farm()
    assert len(t.controls) == E.CONTROL_N
    ids = {id(v) for v in t.vars}
    for c in t.controls:
        assert c.traits.get("flip") and id(c) not in ids and not c.vetoes and not c.layers
        assert set(c.traits) <= set(E.FLIP_COPY) | {"flip"}  # contracts and exits only, no entry filters
    assert t.control_book["flip"] and t.control_book["farm"]  # both sides are counting finished trades
    assert all(c not in t.active for c in t.controls) and all(c not in [v for v, _ in t.ranking()] for c in t.controls)
    cf = t.control_check()
    assert cf["farm"]["n"] == len(t.control_book["farm"]) and "Coin-flip check" in cf["text"]
    st = json.loads(json.dumps(t.to_state()))
    assert all(st["control_book"][k] for k in ("farm", "flip"))
    t2 = E.Tournament(list(t.coins), 10000.0, 0.006, 0.1, 24, opts=t.o, cap=30)
    assert t2.restore(st) and list(t2.control_book["flip"]) == list(t.control_book["flip"])


def test_coin_flip_bots_can_be_switched_off():
    t, _ = _farm(n=500, controls=False)
    assert not t.controls and not t.control_book["flip"]


def test_the_verdict_needs_enough_trades_and_a_clear_gap():
    assert E.control_verdict({"farm": [1.0] * 5, "flip": [0.0] * 5})["verdict"] == "too few"
    rng = random.Random(4)
    same = E.control_verdict({"farm": [rng.gauss(-5, 20) for _ in range(300)],
                              "flip": [rng.gauss(-5, 20) for _ in range(300)]})
    assert same["verdict"] == "no clear difference"
    better = E.control_verdict({"farm": [rng.gauss(5, 20) for _ in range(300)],
                                "flip": [rng.gauss(-5, 20) for _ in range(300)]})
    assert better["verdict"] == "beats" and "beat coin flips" in better["text"]
    worse = E.control_verdict({"farm": [rng.gauss(-9, 20) for _ in range(300)],
                               "flip": [rng.gauss(-2, 20) for _ in range(300)]})
    assert worse["verdict"] == "loses to"


def test_big_farms_move_to_fewer_bots_that_live_longer_once():
    s = E.merge_settings({"max_bots": 175, "retire_hours": 12.0, "defaults_rev": 3})
    assert s["max_bots"] == E.FARM_SIZE_MOVE and s["retire_hours"] == 48.0
    again = E.merge_settings(dict(s, max_bots=120, retire_hours=6.0))
    assert again["max_bots"] == 120 and again["retire_hours"] == 6.0  # chosen after the move: kept
    small = E.merge_settings({"max_bots": 24, "retire_hours": 0, "defaults_rev": 3})
    assert small["max_bots"] == 24 and small["retire_hours"] == 0  # already small, and "never": kept
    assert E.DEFAULT_SETTINGS["retire_hours"] == 48.0 and E.DEFAULT_SETTINGS["min_hold"] == 60
