"""Strategy miner: finds settings that worked in most parts of a stretch, keeps them in a book and hatches eggs."""
import random

import engine as E
from test_feature_tests import market
from test_proving import farm


def test_mine_study_scores_parts_and_checks():
    closes, extra = market(102, 1500)
    res = E.mine_study(closes, extra, 1000.0, 0.006, 0.1, 0.0005, random.Random(1), n=10, parts=6)
    assert res["parts"] == 6 and res["need"] == 4 and res["results"]
    for r in res["results"]:
        assert len(r["part_rets"]) == 6 and 0 <= r["worked"] <= 6
        assert r["ok"] == (r["worked"] >= 4 and r["look_ret"] > 0 and r["check_ret"] > 0)


def test_the_book_hatches_and_grades_mined_eggs():
    t, closes = farm()
    g = dict(name=E.WILDCARD_STRATS[0], params=dict(E.STRATS[E.WILDCARD_STRATS[0]]["params"]), tf=1, risk={}, traits={},
             vetoes={}, layers={})
    r = dict(genes=g, ok=True, worked=5, parts=6, look_ret=0.04, check_ret=0.02)
    assert t.learn_mined(dict(results=[r])) == 1
    assert t.learn_mined(dict(results=[r])) == 0 and t.mined[0]["seen"] == 2  # found again: stronger
    assert t.mined_share() == 0.15
    hg = t.mined_genes()
    assert hg["name"] == g["name"] and hg["_mine_id"] == t.mined[0]["id"]
    v = t.vars[0]
    for _ in range(4):
        v.mine_src = t.mined[0]["id"] if t.mined else None
        t.grade_mined(v, False)
    assert not t.mined  # its eggs kept failing afterwards: dropped
    st = t.to_state()
    assert "mined" in st
