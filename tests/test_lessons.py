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


def test_rotation_scores_a_ticker_on_its_real_swing():
    d = dict(coin="ZZZX", price=61.78, change_24h=3.0, volume_usd=5e9)
    guess, _ = E.scout_score(d, 100.0)
    real, why = E.scout_score(d, 100.0, vol=1.85)  # a 3x ETF: its contracts cost several times the guess
    assert real < guess * 0.5 and "more than the $100 trade size" in why


def _run(genes, seed=102, n=2400):
    from test_feature_tests import market
    closes, extra = market(seed, n)
    coins = list(closes)
    b = E._bt_bot(genes, coins, 10000.0, 0.0, 0.2, 0.0)
    out = []
    for i in range(E.WARM, n):
        for c, t in E.bot_step(b, {x: E.View(closes[x], i + 1) for x in coins}, i, coins, E.slice_extra(extra, i + 1)):
            if t["side"] == "sell":
                out.append(t)
    return out


def test_flat_before_the_close_never_holds_overnight():
    g = dict(name="RSI", params=dict(E.STRATS["RSI"]["params"]), tf=1, risk={}, traits={"night": 2}, vetoes={}, layers={})
    sells = _run(g)
    assert sells
    for t in sells:
        t0 = (t.get("contract") or {}).get("t0")
        assert t0 and E.ny_date(t0) == E.ny_date(t["at"]), t.get("why")


def test_holding_overnight_carries_positions_into_the_next_day():
    base = dict(name="RSI", params=dict(E.STRATS["RSI"]["params"]), tf=1, risk={}, vetoes={}, layers={})
    over = lambda ts: sum(1 for t in ts if E.ny_date(t["contract"]["t0"]) != E.ny_date(t["at"]))
    assert over(_run(dict(base, traits={"night": 1}))) >= over(_run(dict(base, traits={})))


def test_time_expiry_and_instinct_lessons():
    t, _ = farm()
    t.lessons = {}
    day = E.ny_time("2026-11-09", 9, 30)  # a Monday's open, New York
    rng = random.Random(5)
    for i in range(300):
        night = rng.random() < 0.3
        short = rng.random() < 0.3
        late = rng.random() < 0.3
        good = rng.random() < 0.5
        t0 = day + (5.0 if late else 1.0) * 3600  # 2:30 pm or 10:30 am
        t1 = t0 + (86400 if night else 1800)
        pc = (8 if night else -6) - (6 if short else 0) - (5 if late else 0) + (6 if good else -6) + rng.gauss(0, 3)
        tr = dict(contract=dict(type="call", otm0=2, t0=t0, dte0=2 if short else 14), at=t1, why="RSI said sell", held=40,
                  strat="RSI" if good else "Momentum")
        t.learn_lesson(tr, pc)
    lv = t.lesson_view()
    assert lv["night"][0] == 1 and lv["dte"][0] == 7 and "late" in lv
    eggs = [t.rand_traits(0.0) for _ in range(200)]
    assert 0.3 < sum(1 for x in eggs if x.get("night") == 1) / 200 < 0.7
    vt = [t.lesson_vetoes({}) for _ in range(200)]
    assert 0.3 < sum(1 for x in vt if "closing" in x) / 200 < 0.7
    w = dict(zip(["RSI", "Momentum", "MACD"], t.strat_weights(["RSI", "Momentum", "MACD"])))
    assert w["RSI"] > w["MACD"] == 1.0 > w["Momentum"] >= 0.33
    assert E.ny_hour(day + 3600) == 10
    titles = [i["title"] for i in E.farm_knowledge(t) if i["kind"] == "Trade lesson"]
    assert "Hold overnight" in titles
