"""Legends: bots with a proven record are kept when they leave the farm, teach new eggs, and the miner re-tests them.
The Strategy miner doesn't give up after one batch: it keeps refining the near misses."""
import random

import engine as E
from test_feature_tests import market
from test_proving import farm, make_contender, plain


def _make_legend(t):
    v = plain(t)
    make_contender(t, v)
    v.wins, v.losses = max(v.wins, 4), 1
    v.eq.append(v.sim.start * 1.2)  # ahead over its life
    assert t.legend_case(v)
    return v


def test_a_proven_bot_becomes_a_legend_and_stays_after_it_leaves():
    t, closes = farm()
    v = _make_legend(t)
    made = t.sweep_legends()
    assert made and t.legends[0]["alive"] and t.legends[0]["uid"] == v.uid
    assert t.sweep_legends() == []  # only once
    t._remove(v, "retired")
    d = t.legends[0]
    assert not d["alive"] and d["why_left"] == "retired" and v not in t.vars
    st = t.to_state()
    t2 = E.Tournament(list(closes), 1000.0, 0.006, 0.1, 24, opts=t.o, cap=30)
    assert t2.restore(st) and t2.legends and t2.legends[0]["id"] == d["id"]


def test_kamikazes_and_losers_are_not_legends():
    t, _ = farm()
    v = plain(t)
    v.exams = []
    v.eq.append(v.sim.start * 0.8)
    assert t.legend_case(v) is None


def test_legends_hatch_eggs_and_are_graded_by_them():
    t, closes = farm()
    _make_legend(t)
    t.sweep_legends()
    assert t.legend_share() == t.o["legend_share"] > 0
    g = t.legend_genes()
    assert g["name"] == t.legends[0]["genes"]["name"] and g["_legend_id"] == t.legends[0]["id"]
    k = t.vars[1]
    k.legend_src = t.legends[0]["id"]
    t.grade_legend(k, True)
    assert t.legends[0]["kids"] == [1, 1] and k.legend_src is None


def test_a_legend_can_be_brought_back_and_merged_elsewhere():
    t, closes = farm()
    v = _make_legend(t)
    t.sweep_legends()
    t._remove(v, "retired")
    lid = t.legends[0]["id"]
    b = t.recall_legend(lid, {c: closes[c] for c in t.coins})
    assert b and b.origin == "legend" and t.legends[0]["alive"] and t.legends[0]["recalls"] == 1
    t2, _ = farm()
    assert t2.merge_legends(t.legends) == len(t.legends)
    assert t2.merge_legends(t.legends) == 0  # same genes: the same legend
    assert not any(d["alive"] for d in t2.legends)  # they live on another farm, not this one


def test_the_miner_retests_legends_and_counts_them_found_again():
    t, _ = farm()
    _make_legend(t)
    t.sweep_legends()
    g = t.legend_genes_for_miner()[0]
    res = dict(results=[dict(genes=g, ok=True)])
    assert t.legends_mined_again(res) == [t.legends[0]["nickname"]] and t.legends[0]["again"] == 1


def test_the_miner_keeps_going_until_it_finds_enough_or_runs_out():
    closes, extra = market(102, 1500)
    res = E.mine_study(closes, extra, 1000.0, 0.006, 0.1, 0.0005, random.Random(1), n=20, budget=120, want=50)
    assert res["rounds"] > 1 and res["tried"] == 120  # didn't stop after the first batch
    one = E.mine_study(closes, extra, 1000.0, 0.006, 0.1, 0.0005, random.Random(1), n=20, budget=20)
    assert one["rounds"] == 1 and one["tried"] == 20
    assert res["best_worked"] >= one["best_worked"]
    keys = [E._mine_key(r["genes"]) for r in res["results"]]
    assert len(keys) == len(set(keys))  # never tries the same settings twice


def test_the_miner_stops_early_once_enough_hold_up():
    closes, extra = market(55, 1500)
    res = E.mine_study(closes, extra, 1000.0, 0.006, 0.1, 0.0005, random.Random(1), budget=400, want=1)
    oks = [r for r in res["results"] if r["ok"]]
    assert oks and res["tried"] < 400


def test_legends_file_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "HOME_DIR", str(tmp_path))
    t, _ = farm()
    _make_legend(t)
    t.sweep_legends()
    assert E.save_legends(t.legends) == 1 and E.save_legends(t.legends) == 1
    back = E.load_legends()
    assert back[0]["id"] == t.legends[0]["id"]
    assert E.forget_legend(back[0]["id"]) == []
