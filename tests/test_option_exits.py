"""Options-only exits a bot can learn: time decay and a volatility collapse."""
import time

import engine as E


class _Sim:
    def __init__(self, days, vol_then, vol_now):
        self.now = time.time()
        self.opt = {"SPY": dict(type="call", K=500.0, exp=self.now + days * 86400, vol=vol_then)}
        self._vol = lambda c: vol_now


def test_decay_exit_fires_near_expiry_only():
    assert E.option_exit(_Sim(2, 0.3, 0.3), "SPY", 500.0, {"decay": 10}) == "decay"
    assert E.option_exit(_Sim(60, 0.3, 0.3), "SPY", 500.0, {"decay": 10}) is None


def test_volatility_collapse_exit():
    assert E.option_exit(_Sim(30, 0.5, 0.25), "SPY", 500.0, {"ivdrop": 40}) == "ivdrop"
    assert E.option_exit(_Sim(30, 0.5, 0.45), "SPY", 500.0, {"ivdrop": 40}) is None
    assert E.option_exit(_Sim(30, 0.0, 0.25), "SPY", 500.0, {"ivdrop": 40}) is None  # entry vol unknown: never fires


def test_new_traits_are_described():
    for k in ("decay", "ivdrop"):
        assert k in E.TRAITS and k in E.TRAIT_NAMES
        assert E.TRAITS[k]["text"](E.TRAITS[k]["lo"])
