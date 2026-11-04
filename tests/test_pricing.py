"""Practice option prices: steady volatility and a realistic minimum price, so a few % move can't turn a contract
into a 400x win that only exists in the model (the farm learned to chase those)."""
import random

import engine as E


def calm_then_burst(n_calm=2000, n_burst=15, seed=4):
    rng = random.Random(seed)
    p = [14.0]
    for _ in range(n_calm):
        p.append(p[-1] * (1 + rng.gauss(0, 0.0004)))
    calm = list(p)
    for _ in range(n_burst):
        p.append(p[-1] * (1 + 0.002 + rng.gauss(0, 0.003)))
    t = [1.77e9 + 60 * i for i in range(len(p))]
    return calm, p, t


def test_pricing_volatility_barely_moves_on_a_short_burst():
    calm, run, t = calm_then_burst()
    old_jump = E.realized_vol(run, t) / E.realized_vol(calm, t[:len(calm)])
    new_jump = E.pricing_vol(run, t) / E.pricing_vol(calm, t[:len(calm)])
    assert old_jump > 2.0  # the last-120-candles measure nearly triples...
    assert new_jump < 1.3  # ...the pricing one hardly moves


def test_daily_candles_use_a_few_months():
    rng = random.Random(1)
    p = [100.0]
    for _ in range(300):
        p.append(p[-1] * (1 + rng.gauss(0, 0.01)))
    t = [1.6e9 + 86400 * i for i in range(len(p))]
    assert abs(E.pricing_vol(p, t) - E.realized_vol(p, t, 120)) < 1e-12


def test_pricing_volatility_has_a_floor():
    p = [100.0] * 500
    t = [1.77e9 + 60 * i for i in range(500)]
    assert E.pricing_vol(p, t) >= E.PRICING_VOL_FLOOR


def test_contracts_below_the_minimum_price_are_not_bought():
    sim = E.make_sim(1000.0, 0.006, 0.1, genes={"otm": 12, "odte": 2})
    sim.now = 1.77e9
    sim.vol_src["X"] = 0.12  # calm, far out of the money, two days left: worth well under $5
    assert not sim._open("X", "call", 100.0, 0)
    assert not sim.pos.get("X")
    sim2 = E.make_sim(1000.0, 0.006, 0.1, genes={"otm": 1, "odte": 14})
    sim2.now = 1.77e9
    sim2.vol_src["X"] = 0.30
    assert sim2._open("X", "call", 100.0, 0)  # an ordinary contract still buys fine
