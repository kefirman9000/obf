"""1.47: the Signal school (every signal graded on the stock, and the move a contract needs to pay for itself), the
trade judge (one model learning from every finished trade), and option bots' blocked buys graded against what a
contract really costs."""
import random

import pytest

import engine as E
from test_feature_tests import market


@pytest.fixture(autouse=True)
def _clean_books():
    school, seen, judge, gates = dict(E.SCHOOL), dict(E.SCHOOL_SEEN), dict(E.JUDGE), dict(E.GATES)
    E.SCHOOL.clear()
    E.SCHOOL_SEEN.clear()
    E.JUDGE.update(w={}, n=0, wins=0.0, brier=[0.0, 0.0, 0.0])
    E.GATES.update(school=True, judge=True)
    yield
    E.SCHOOL.clear()
    E.SCHOOL.update(school)
    E.SCHOOL_SEEN.clear()
    E.SCHOOL_SEEN.update(seen)
    E.JUDGE.clear()
    E.JUDGE.update(judge)
    E.GATES.update(gates)


def _walks(k=4, n=1500, seed=5):
    _, ex = market(1, n)
    t = ex["SPY"]["t"]
    rng = random.Random(seed)
    closes, extra = {}, {}
    for j in range(k):
        p, xs = 100.0, []
        for _ in range(n):
            p *= 1 + rng.gauss(0, 0.0007)
            xs.append(p)
        closes[f"T{j}"] = xs
        extra[f"T{j}"] = dict(h=[x * 1.001 for x in xs], l=[x * 0.999 for x in xs], v=[1000.0] * n, t=t)
    return closes, extra


GENES = [("RSI", {"period": 14, "lo": 30, "hi": 70}, 1), ("Bollinger bands", {"n": 20, "k": 2.0}, 3),
         ("SMA crossover", {"fast": 5, "slow": 20}, 1)]


def test_signals_on_a_random_walk_grade_near_zero():
    res = E.school_study(*_walks(), GENES)
    assert res["signals"] > 200
    n = z = 0.0
    for hs in res["book"].values():
        s_ = hs.get("h60")
        if s_:
            n += s_[0]
            z += s_[1]
    assert n > 200 and abs(z / n) < 0.15  # no look-ahead: on a coin-flip market no signal knows the future


def test_live_runs_only_grade_new_candles():
    closes, extra = _walks(2, 1200)
    first = E.school_study(closes, extra, GENES)
    assert first["until"]
    again = E.school_study(closes, extra, GENES, since=first["until"])
    assert again["signals"] == 0  # the same candles are never graded twice


def test_grades_merge_fade_and_need_enough_signals():
    E.merge_school({"RSI|1-2|b": {"h60": [10, 2.0, 1.0, 6]}})
    assert E.school_grade("RSI|1-2|b", 60) is None  # under SCHOOL_MIN
    E.merge_school({"RSI|1-2|b": {"h60": [30, 6.0, 3.0, 18]}})
    n_, mean, se, hit = E.school_grade("RSI|1-2|b", 60)
    assert n_ == 40 and abs(mean - 0.2) < 1e-9 and se > 0 and hit == 0.6
    E.merge_school({"RSI|1-2|b": {"h60": [E.SCHOOL_FADE, 0.0, 0.0, 0]}})
    assert E.SCHOOL["RSI|1-2|b"]["h60"][0] < E.SCHOOL_FADE + 40  # older counts halved
    E.merge_school({"RSI|1-2|b": {"o:h60": [40, -8.0, 4.0, 10]}})
    assert E.school_grade("RSI|1-2|b", 60, "o")[1] == -0.2  # the time-of-day grade when it has enough


def test_far_out_contracts_need_bigger_moves():
    near = E.breakeven_move("NVDA", 150.0, "call", 1, 14, 0.5, 60)
    far = E.breakeven_move("NVDA", 150.0, "call", 12, 14, 0.5, 60)
    longer = E.breakeven_move("NVDA", 150.0, "call", 1, 14, 0.5, 240)
    assert 0 < near < far and longer > near
    assert E.breakeven_move("NVDA", 150.0, "put", 1, 14, 0.5, 60) > 0
    assert E.breakeven_move("NVDA", 0, "call", 1, 14, 0.5, 60) is None


class _Sim:
    now = None
    opt, pos = {}, {}

    def _vol(self, c):
        return 0.5


def _bot(uid, name="RSI", tf=1, otm=5.0):
    b = E._bt_bot(dict(name=name, params=dict(E.STRATS[name]["params"]), tf=tf, traits={"otm": otm}, uid=uid),
                  ["NVDA"], 1000.0, 0.0, 0.1, 0.0)
    return b


def test_the_gate_blocks_signals_too_small_for_the_contract_on_half_the_bots():
    closes, extra = _walks(1, 600)
    closes = {"NVDA": [x * 1.5 for x in closes["T0"]]}
    extra = {"NVDA": extra["T0"]}
    key = E.school_key("RSI", 1, "buy")
    sim = _Sim()
    assert E.school_check(_bot(0), "NVDA", "buy", closes, extra, sim) == (False, None)  # nothing graded: never blocked
    E.merge_school({key: {"h60": [200, 4.0, 40.0, 104]}})  # +0.02 swings: real, but far too small for a contract
    blocked, edge = E.school_check(_bot(0), "NVDA", "buy", closes, extra, sim)
    assert blocked and abs(edge - 0.02) < 1e-9
    assert E.school_check(_bot(2), "NVDA", "buy", closes, extra, sim)[0] is False  # the comparison half
    E.GATES["school"] = False
    assert E.school_check(_bot(0), "NVDA", "buy", closes, extra, sim)[0] is False  # switched off
    E.GATES["school"] = True
    E.SCHOOL.clear()
    E.merge_school({key: {"h60": [200, 1000.0, 5100.0, 190]}})  # +5 swings: pays for the contract
    assert E.school_check(_bot(0), "NVDA", "buy", closes, extra, sim)[0] is False


def test_the_judge_learns_and_blocks_only_once_it_beats_guessing():
    rng = random.Random(3)
    sim = _Sim()
    assert E.judge_check(_bot(0), "NVDA", "buy", sim, "normal", None) == (False, None)  # untrained
    for _ in range(1200):
        far = rng.random() < 0.5
        won = rng.random() < (0.1 if far else 0.55)  # far-out contracts lose
        E.judge_learn(E.judge_features("call", 15 if far else 2, 14, None, "RSI", 1, "normal", None), won)
    assert E.JUDGE["n"] == 1200 and (E.judge_skill() or 0) > 0.03
    far_p = E.judge_prob(E.judge_features("call", 15, 14, None, "RSI", 1, "normal", None))
    near_p = E.judge_prob(E.judge_features("call", 2, 14, None, "RSI", 1, "normal", None))
    assert far_p < 0.2 < 0.4 < near_p
    assert E.judge_check(_bot(0, otm=15), "NVDA", "buy", sim, "normal", None)[0] is True
    assert E.judge_check(_bot(0, otm=2), "NVDA", "buy", sim, "normal", None)[0] is False
    assert E.judge_check(_bot(4, otm=15), "NVDA", "buy", sim, "normal", None)[0] is False  # the comparison half


def test_a_finished_trade_carries_what_the_judge_needs():
    t = dict(strat="RSI", tf=3, contract=dict(type="put", otm0=8.0, dte0=12, t0=None, reg0="spiking", edge0=0.05))
    f = E.trade_features(t)
    assert f["side:put"] == 1 and f["otm:7-12"] == 1 and f["dte:11+"] == 1 and f["reg:spiking"] == 1
    assert f["pace:3-5"] == 1 and f["strat:RSI"] == 1 and f["edge"] == pytest.approx(0.25)


def test_option_bots_grade_blocked_buys_against_the_contract():
    b = _bot(0)
    assert isinstance(b.sim, E.OptionSim)
    b.veto_wait = [("rsicap", "NVDA", "buy", 150.0, 5)]
    E._grade_vetoes(b, {"NVDA": [150.0] * 5 + [150.075]}, 10)  # +0.05%: a "cost" for a stock, too little for a call
    n_, saved = b.veto_stats["rsicap"]
    assert n_ == 1 and saved > 0
    b.veto_wait = [("rsicap", "NVDA", "buy", 150.0, 5)]
    E._grade_vetoes(b, {"NVDA": [150.0] * 5 + [165.0]}, 10)  # +10%: the blocked call would have paid
    assert b.veto_stats["rsicap"][1] < saved


def test_switches_reach_the_engine_and_are_feature_tested():
    E.tournament_opts(dict(E.DEFAULT_SETTINGS, signal_school=False, trade_judge=False))
    assert E.GATES == {"school": False, "judge": False}
    E.tournament_opts(E.DEFAULT_SETTINGS)
    assert E.GATES == {"school": True, "judge": True}
    cands = E.feature_candidates(dict(E.DEFAULT_SETTINGS), ["signal_school", "trade_judge"])
    assert set(cands) == {"signal_school", "trade_judge"}


def test_a_gated_bot_stops_buying_what_the_school_marks_down():
    closes, extra = market(3, 1200)
    genes = None
    for name in ("RSI", "Bollinger bands", "Mean reversion", "Stochastic"):
        g = dict(name=name, params=dict(E.STRATS[name]["params"]), tf=1, traits={"otm": 5.0}, uid=0)
        if E.backtest_bot(g, closes, extra, segments=1)["trades"] >= 4:
            genes = g
            break
    assert genes, "no plain bot traded on the test market"
    for side in ("buy", "sell"):  # its kind of signal, graded as far too small to pay for a contract
        E.merge_school({E.school_key(genes["name"], 1, side): {f"h{h}": [500, 0.0, 500.0, 250] for h in E.SCHOOL_HORIZONS}})
    gated = E.backtest_bot(genes, closes, extra, segments=1)
    free = E.backtest_bot(dict(genes, uid=2), closes, extra, segments=1)
    assert gated["trades"] < free["trades"]
    assert gated["layer_stats"].get("school", [0])[0] > 0  # and each blocked buy is graded in hindsight


def test_the_learning_book_survives_a_restart_and_shows_in_the_report(tmp_path, monkeypatch):
    pytest.importorskip("tkinter")
    import types

    import main as M
    monkeypatch.setattr(E, "HOME_DIR", str(tmp_path))
    a = types.SimpleNamespace(logs=[])
    a.learning_path = lambda: M.App.learning_path(a)
    a.save_learning_book = lambda: M.App.save_learning_book(a)
    a.write = lambda msg, tag=None: a.logs.append(msg)
    E.merge_school({"RSI|1-2|b": {f"h{h}": [40, 4.0, 2.0, 24] for h in E.SCHOOL_HORIZONS}})
    E.judge_learn(E.judge_features("call", 2, 14, None, "RSI", 1, "normal", 0.1), True)
    M.App._school_apply(a, dict(book={"RSI|1-2|s": {"h60": [35, -3.5, 2.0, 12]}}, until={"NVDA": 123.0}, signals=75),
                        "the session's candles", True)
    assert E.SCHOOL_SEEN == {"NVDA": 123.0} and "75 signals" in a.logs[-1]
    E.SCHOOL.clear()
    E.SCHOOL_SEEN.clear()
    E.JUDGE.update(w={}, n=0, wins=0.0)
    M.App.load_learning_book(a)
    assert E.school_grade("RSI|1-2|b", 60)[0] == 40 and E.school_grade("RSI|1-2|s", 60)[1] == -0.1
    assert E.SCHOOL_SEEN == {"NVDA": 123.0} and E.JUDGE["n"] == 1 and E.JUDGE["w"]
    rows = E.school_rows(60)
    d = dict(account={}, farms={}, free_roam=dict(on=False, studies=0, days_trained=[], log=[]),
             signal_school=dict(families=len(E.SCHOOL), h60=[dict(strategy=r[0], pace=r[1], side=r[2], signals=r[3],
                                                                     swings=r[4], se=r[5], right=r[6]) for r in rows]),
             trade_judge=dict(trades=1, won=1.0, skill=None))
    text = M.App._report_summary(d)
    assert "Signal school" in text and "RSI (1-2) buy: 40 signals, +0.100" in text and "Trade judge" in text


def test_a_self_tuned_bot_gets_a_new_identity():
    from test_proving import farm, plain
    t, _ = farm()
    t.lessons = {}
    for _ in range(E.LESSON_MIN):
        t.learn_lesson(dict(side="sell", why="its own profit target", held=5, contract={"type": "call"}), -8.0)
        t.learn_lesson(dict(side="sell", why="its own profit target", held=40, contract={"type": "call"}), 4.0)
    t._adopt_budget = 10
    v = plain(t)
    v.uid = 4
    v.risk = E.clean_risk({"sl": 30.0})
    v.traits = {}
    v.__dict__.pop("_key", None)
    before = v.key()
    assert "holds at least" in (t.self_tune(v) or "")
    assert v.key() != before and dict(v.key()[4]).get("minhold")  # (it kept its old identity until a restart)
