"""Live-order safety: OBF never sells what it doesn't hold, and never sends the same order twice."""
import urllib.error

import pytest

import engine as E


class FakeAlpaca:
    """Pretends to be Alpaca's order endpoints. `lose_answer` makes the first POST arrive but its reply get lost."""

    def __init__(self, lose_answer=False, fail_first=None):
        self.orders = {}
        self.posts = 0
        self.lose_answer = lose_answer
        self.fail_first = fail_first

    def __call__(self, method, url, body=None, timeout=12, retries=1, creds=None):
        if method == "POST":
            self.posts += 1
            if self.fail_first is not None and self.posts == 1:
                raise self.fail_first
            cid = body["client_order_id"]
            if cid in self.orders:
                raise E.AlpacaError(422, "Alpaca said 422: client_order_id must be unique")
            self.orders[cid] = dict(body, id=f"ord-{len(self.orders)}")
            if self.lose_answer and self.posts == 1:
                raise urllib.error.URLError("timed out")
            return self.orders[cid]
        if method == "GET" and "by_client_order_id" in url:
            cid = url.split("client_order_id=")[1]
            if cid not in self.orders:
                raise E.AlpacaError(404, "Alpaca said 404: order not found")
            return self.orders[cid]
        raise AssertionError(f"unexpected call {method} {url}")


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(E.time, "sleep", lambda s: None)

    def make(**kw):
        f = FakeAlpaca(**kw)
        monkeypatch.setattr(E, "alp", f)
        return f
    return make


def test_lost_reply_does_not_place_a_second_order(fake):
    f = fake(lose_answer=True)
    r = E.alp_order("SPY250101C00500000", 2, "buy", limit=1.23)
    assert len(f.orders) == 1
    assert r["id"] == "ord-0"


def test_order_that_never_arrived_is_sent_again(fake):
    f = fake(fail_first=urllib.error.URLError("connection reset"))
    r = E.alp_order("SPY250101C00500000", 1, "buy")
    assert len(f.orders) == 1 and f.posts == 2
    assert r["qty"] == "1"


def test_server_error_checks_before_resending(fake):
    f = fake(fail_first=E.AlpacaError(503, "Alpaca said 503"))
    E.alp_order("SPY250101C00500000", 1, "buy")
    assert len(f.orders) == 1


def test_rejected_order_is_not_retried(fake):
    f = fake(fail_first=E.AlpacaError(403, "Alpaca said 403: insufficient buying power"))
    with pytest.raises(E.AlpacaError):
        E.alp_order("SPY250101C00500000", 1, "buy")
    assert f.posts == 1


def test_every_order_has_its_own_client_id(fake):
    f = fake()
    E.alp_order("A", 1, "buy")
    E.alp_order("A", 1, "buy")
    assert len(f.orders) == 2


@pytest.mark.parametrize("qty,held", [(1, None), (2, 1), (0, 5), (-1, 5)])
def test_never_sells_more_than_it_holds(qty, held):
    with pytest.raises(E.UnsafeOrder):
        E.check_order("sell", qty, held)


def test_unknown_side_is_blocked():
    with pytest.raises(E.UnsafeOrder):
        E.check_order("sell_short", 1, 1)


def test_closing_what_it_holds_is_allowed():
    E.check_order("sell", 2, 2)
    E.check_order("buy", 3)
