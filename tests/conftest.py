import os
import sys
import tempfile

# keep tests away from the real ~/.obf data folder
os.environ["HOME"] = tempfile.mkdtemp(prefix="obf-test-home-")
os.environ["USERPROFILE"] = os.environ["HOME"]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import random  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _repeatable(monkeypatch):
    """Every test sees the same 'random' farm: a generator made without a seed gets a fixed one, so a test can't pass
    or fail on the luck of the draw."""
    import engine
    real = random.Random
    counter = iter(range(10 ** 6))
    monkeypatch.setattr(engine.random, "Random", lambda *a: real(*a) if a else real(1000 + next(counter)))
    random.seed(12345)
    # the Signal school's and the trade judge's books are shared by every farm in a process: each test starts empty,
    # so what one test's farm taught can't change how another's trades (and the order tests run in can't matter)
    saved = (dict(engine.SCHOOL), dict(engine.SCHOOL_SEEN), dict(engine.JUDGE), dict(engine.GATES))
    engine.SCHOOL.clear()
    engine.SCHOOL_SEEN.clear()
    engine.JUDGE.clear()
    engine.JUDGE.update(w={}, n=0, wins=0.0, brier=[0.0, 0.0, 0.0])
    yield
    for d, x in zip((engine.SCHOOL, engine.SCHOOL_SEEN, engine.JUDGE, engine.GATES), saved):
        d.clear()
        d.update(x)
