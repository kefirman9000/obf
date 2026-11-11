"""1.40: bots don't buy far-out contracts past their limit, a record carried by one trade isn't proof, and the farm
learns trade lessons (calls vs puts, how far out, how it sold, how long it held) that new eggs lean toward."""
import random

import engine as E
from test_proving import farm, plain


def _buy(S, traits, hi):
    E.set_prem_range(0, hi)
    try:
        sim = E.make_sim(10000.0, 0.0, 0.5, genes=traits)
        sim._vol = lambda c: 0.5
        ok = sim.buy("XYZ", S, 0)
        return ok, sim
    finally:
        E.set_prem_range(0, 0)


def test_far_out_contracts_are_skipped_past_the_limit():
    old = E.MAX_OTM[0]
    try:
        E.set_max_otm(15)
        ok, sim = _buy(800.0, {}, 0.5)  # only a contract under $50 fits: far out of the money on an $800 stock
        assert not ok and sim.too_far == 1
        ok, sim = _buy(800.0, {"kami": 1}, 0.5)  # kamikazes are exempt: cheap far-out bets are their whole idea
        assert ok and sim.opt["XYZ"]["otm0"] > 15
        E.set_max_otm(0)
        ok, _ = _buy(800.0, {}, 0.5)  # no ceiling: buys as before
        assert ok
        E.set_max_otm(15)
        ok, sim = _buy(100.0, {"otm": 2}, 0)  # near the money: fine
        assert ok and sim.opt["XYZ"]["otm0"] < 5
        ok, _ = _buy(100.0, {"otm": 10, "maxotm": 4}, 0)  # its own learned limit is tighter than the ceiling
        assert not ok
    finally:
        E.set_max_otm(old)


def test_limit_and_pick_contract():
    assert E.otm_limit({}) == E.MAX_OTM[0]
    assert E.otm_limit({"maxotm": 5}) == min(5, E.MAX_OTM[0] or 5)
    assert round(E.otm_dist("call", 110, 100), 6) == 10 and round(E.otm_dist("put", 90, 100), 6) == 10 and E.otm_dist("call", 95, 100) < 0
    now = 1.8e9
    chain = [dict(type="call", K=k, exp=now + 20 * 86400, ask=1.0, bid=0.95, symbol=f"C{k}") for k in (102, 140)]
    assert E.pick_contract(chain, 100, "call", 20, 40, now, max_otm=15)["K"] == 102
    assert E.pick_contract(chain, 100, "call", 20, 40, now, max_otm=0)["K"] == 140


def test_one_trade_wonders_are_not_proven_or_legends():
    t, _ = farm()
    v = plain(t)
    v.wins, v.losses = 2, 6
    v.best_tr, v.best_pl = 900.0, 500.0
    v.eq.append(v.sim.start + 300)  # +$300 overall, but only because of one +$500 trade
    assert t.one_hit(v)
    assert any("single trade" in g for g in t.proven_gaps(v))
    assert t.legend_case(v) is None
    v.best_pl = 200.0  # without its best trade it's still ahead: fine
    assert not t.one_hit(v)


def test_typical_trade_is_the_median():
    t, _ = farm()
    v = plain(t)
    v.trade_pcts = [-20, -20, -20, 500, 900]
    assert t.typical(v) == -20
    assert any("typical trade" in g for g in t.proven_gaps(v))
    v.trade_pcts = [1, 2]
    assert t.typical(v) is None


def _trade(typ, d, why, held, pc):
    return dict(contract=dict(type=typ, otm0=d), why=why, held=held), pc


def test_trade_lessons_and_eggs_lean_toward_them():
    t, _ = farm()
    t.lessons = {}
    rng = random.Random(3)
    for _ in range(300):
        far = rng.random() < 0.4
        typ = "put" if rng.random() < 0.4 else "call"
        sig = rng.random() < 0.6
        quick = rng.random() < 0.3
        pc = 5.0 - (12 if far else 0) - (6 if typ == "put" else 0) - (5 if sig else 0) - (6 if quick else 0) + rng.gauss(0, 5)
        tr, pc = _trade(typ, 25 if far else 3, "RSI said sell" if sig else "its own profit target (40%)",
                        5 if quick else 40, pc)
        t.learn_lesson(tr, pc)
    lv = t.lesson_view()
    assert lv["side"][0] == "call" and lv["maxotm"][0] in (5, 15) and lv["exit"][0] == "rules" and lv["minhold"][0] == 15
    eggs = [t.rand_traits(0.0) for _ in range(200)]
    share = lambda k: sum(1 for x in eggs if k in x) / len(eggs)
    assert 0.3 < share("maxotm") < 0.7 and 0.3 < share("omode") < 0.7 and share("minhold") > 0.3
    assert all(x.get("omode", 1) == 1 for x in eggs)  # calls did better: eggs that pick a side pick calls
    items = [i for i in E.farm_knowledge(t) if i["kind"] == "Trade lesson"]
    assert len(items) == 4
    t2, _ = farm()
    t2.lessons = {}
    E.apply_knowledge(t2, items)
    assert t2.lesson_view().keys() == lv.keys()  # another farm takes the evidence (at half weight)
    st = t.to_state()
    assert st["lessons"] and t2.restore(st) and t2.lessons == t.lessons


def test_a_fluke_trade_teaches_at_most_200_percent():
    t, _ = farm()
    t.lessons = {}
    tr, _ = _trade("call", 3, "RSI said sell", 40, 0)
    t.learn_lesson(tr, 1783.0)
    assert t.lessons["side:call"][1] == 200.0


def test_exit_kinds():
    assert E.exit_kind("its own profit target (40%)") == "target"
    assert E.exit_kind("its own safety stop (10.25%)") == "stop"
    assert E.exit_kind("its trailing stop (5%)") == "trail"
    assert E.exit_kind("it held as long as it allows") == "time"
    assert E.exit_kind("1 of its 3 buy studies agreed (needs 1)") == "signal"
