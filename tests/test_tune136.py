"""1.36: Free roam's findings applied - fewer, tighter scalpers that must win at real prices first, Adaptive stops off
by default (still tested), and hindsight eggs that lean on what held up afterwards."""
import engine as E
from test_proving import farm, plain


def test_old_settings_move_to_the_new_defaults_once():
    s = E.merge_settings({"adapt_exits": True, "scalp_share": 25, "scalp_spread": 8.0})
    assert s["adapt_exits"] is False and s["scalp_share"] == 10 and s["scalp_spread"] == 3.0 and s["defaults_rev"] == 2
    s2 = E.merge_settings(dict(s, adapt_exits=True, scalp_share=30))  # chosen after the move: kept
    assert s2["adapt_exits"] is True and s2["scalp_share"] == 30
    assert E.merge_settings({"scalp_share": 5})["scalp_share"] == 5


def test_adaptive_stops_are_still_feature_tested_while_off():
    s = E.merge_settings({})
    assert s["adapt_exits"] is False
    assert "adapt_exits" in E.feature_candidates(s, ["adapt_exits"])


def test_switched_off_adaptive_stops_leave_existing_bots():
    t, closes = farm()
    v = plain(t)
    v.traits["adapt"] = 1
    t.o["adapt_exits"] = False
    t.step({c: E.View(closes[c], 900) for c in closes})
    assert "adapt" not in v.traits


def test_scalpers_need_winning_exam_days_at_real_prices():
    t, _ = farm()
    v = plain(t)
    v.name = E.SCALP_STRATS[0]
    assert any("real option prices" in g for g in t.proven_gaps(v))
    for k in range(2):
        E.add_exam(v, "day", 2.0, 5, f"2026-10-0{k + 1}", 60)
        v.exams[-1]["real"] = True
    assert E.real_exam_wins(v) == 2
    assert not any("real option prices" in g for g in t.proven_gaps(v))


def test_a_hindsight_egg_that_loses_its_first_exam_is_retired():
    t, _ = farm()
    v = plain(t)
    t.proven = lambda x: False
    v.origin, v.exams = "hindsight", []
    E.add_exam(v, "self-test", 1.5, 4)
    assert not t.hindsight_exam(v) and v in t.vars  # passed: stays
    v.exams = []
    E.add_exam(v, "self-test", -1.5, 4)
    assert t.hindsight_exam(v) and v not in t.vars


def test_hindsight_share_is_capped_lower():
    t, _ = farm()
    t.hindsight = {"x": dict(tries=10, wins=5, best=[], fwd=[40, 30])}
    assert t.hindsight_share() == 0.2
    t.hindsight = {"x": dict(tries=10, wins=5, best=[], fwd=[40, 1])}
    assert t.hindsight_share() == 0.05
