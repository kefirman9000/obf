"""1.47.2, from the 11/19 evening report: the Signal school counted every signal, though signals a candle apart (and
bots of the same kind on the same candle) see the same move, so its grades looked up to 4x surer than they were (on a
random walk, "edges" of 9 standard errors). Also: no "no new candle" warning while the market is closed."""
import json
import statistics

import pytest

import engine as E
from test_signal_school import _clean_books, _walks  # noqa: F401  (the fixture keeps each test's books apart)

KINDS = [("RSI", {"period": 14, "lo": 30, "hi": 70}, 1), ("RSI", {"period": 11, "lo": 30, "hi": 70}, 1),
         ("RSI", {"period": 16, "lo": 30, "hi": 70}, 1), ("Bollinger bands", {"n": 20, "k": 2.0}, 1),
         ("Bollinger bands", {"n": 16, "k": 2.0}, 1), ("Momentum", {"n": 10, "thr": 0.5}, 1),
         ("Mean reversion", {"n": 20, "thr": 1.0}, 1), ("Mean reversion", {"n": 16, "thr": 1.0}, 1),
         ("Breakout", {"n": 20}, 1), ("Stochastic", {"n": 14, "lo": 20, "hi": 80}, 1),
         ("Rate of change", {"n": 12, "smooth": 4}, 1)]


def test_on_a_random_walk_the_grades_are_no_surer_than_chance():
    ts = []
    for seed in (5, 6):
        E.SCHOOL.clear()
        E.merge_school(E.school_study(*_walks(4, 3000, seed), KINDS)["book"])
        ts += [r[4] / r[5] for r in E.school_rows(60) if r[5] > 0]
    assert len(ts) >= 12
    # honest standard errors give t-stats spread about 1; counting every overlapping signal gave about 4.5
    assert statistics.pstdev(ts) < 2.0


def test_one_kind_of_signal_counts_once_per_window():
    closes, extra = _walks(2, 2000)
    res = E.school_study(closes, extra, KINDS)
    span = 2000 - max(E.WARM, E.SCHOOL_SWING_BARS + 1, E.LOOKBACK // 2) - 240
    for key, hs in res["book"].items():
        for h in E.SCHOOL_HORIZONS:
            assert hs[f"h{h}"][0] <= len(closes) * (span // h + 1), (key, h)  # windows never overlap
    assert res["signals"] > sum(hs["h60"][0] for hs in res["book"].values())  # every signal still seen, fewer graded


def test_older_learning_books_are_regraded_but_the_judge_is_kept(tmp_path, monkeypatch):
    pytest.importorskip("tkinter")
    import types

    import main as M
    monkeypatch.setattr(E, "HOME_DIR", str(tmp_path))
    a = types.SimpleNamespace()
    a.learning_path = lambda: M.App.learning_path(a)
    old = dict(school={"RSI|1-2|b": {"h60": [900, 90.0, 50.0, 500]}}, seen={"NVDA": 123.0},
               judge=dict(w={"bias": -0.2}, n=98, wins=28.0, brier=[98, 20, 21]))
    (tmp_path / "learning-book.json").write_text(json.dumps(old))
    M.App.load_learning_book(a)
    assert not E.SCHOOL and not E.SCHOOL_SEEN  # counted overlapping signals: thrown out, the session's candles regraded
    assert E.JUDGE["n"] == 98 and E.JUDGE["w"] == {"bias": -0.2}
    (tmp_path / "learning-book.json").write_text(json.dumps(dict(old, school_rev=E.SCHOOL_REV)))
    M.App.load_learning_book(a)
    assert E.school_grade("RSI|1-2|b", 60)[0] == 900 and E.SCHOOL_SEEN == {"NVDA": 123.0}


def test_no_stale_candle_warning_while_the_market_is_closed():
    pytest.importorskip("tkinter")
    import main as M
    feed = dict(bars=2147, last_age_s=13538, gaps_today=[])
    closed = M.App._report_checks(dict(price_feed={"NVDA": dict(feed, market_open=False)}))
    opened = M.App._report_checks(dict(price_feed={"NVDA": dict(feed, market_open=True)}))
    assert "no new candle" not in closed and "Nothing looks wrong" in closed
    assert "NVDA: no new candle for 225 min" in opened
