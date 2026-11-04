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
    assert abs(E.pricing_vol(p, t) - E.realized_vol(p, t, 120)) < 0.01  # (same few months, one day either way)


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


def test_bots_buy_inside_the_contract_price_range():
    """With a range set, a bot moves its strike until the contract's price fits, or skips the trade."""
    try:
        for lo, hi in ((0.50, 1.50), (3.00, 6.00)):
            E.set_prem_range(lo, hi)
            for otm in (0.5, 3.0, 8.0):
                sim = E.make_sim(10000.0, 0.006, 0.1, genes={"otm": otm, "odte": 14})
                sim.now = 1.77e9
                sim.vol_src["X"] = 0.35
                if sim._open("X", "call", 100.0, 0):
                    paid = sim.cost["X"] / sim.pos["X"]  # per contract, with fees and slippage
                    prem = sim.mark_one("X", 100.0) / E.CONTRACT
                    assert lo - 1e-9 <= prem <= hi + 1e-9, (lo, hi, otm, prem, paid)
        E.set_prem_range(50.0, 60.0)  # nothing on a $100 stock costs that much
        sim = E.make_sim(10000.0, 0.006, 0.1, genes={"otm": 2, "odte": 14})
        sim.now = 1.77e9
        sim.vol_src["X"] = 0.35
        assert not sim._open("X", "call", 100.0, 0)
    finally:
        E.set_prem_range(0, 0)


def test_overnight_gaps_do_not_inflate_pricing_volatility():
    """A jump over a night (or an earnings gap) isn't a one-minute move: counted as one, INTC read 226% vs 92%."""
    import math
    rng = random.Random(7)
    sd_min = 0.50 / math.sqrt(252 * 390)
    p, t, t0 = [57.0], [1.77e9], 1.77e9
    for day in range(6):
        if day:
            p.append(p[-1] * (1 + (0.10 if day == 3 else rng.gauss(0, 0.02))))
            t.append(t0 + day * 86400)
        for m in range(1, 390):
            p.append(p[-1] * (1 + rng.gauss(0, sd_min)))
            t.append(t0 + day * 86400 + m * 60)
    assert E.realized_vol(p, t, 1950) > 0.75  # the old way
    assert 0.42 < E.pricing_vol(p, t) < 0.58  # close to the true 50%
