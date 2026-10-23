"""Tests for spec 004 — paper order routing.

Broker talks to the IBKR gateway through a fake transport (no network).
Ticket store uses SQLite. Nothing here places a real order.
"""
import time

import pytest

from src.engine.broker import (
    BrokerGuardError,
    BrokerRejected,
    PaperBroker,
)
from src.engine.order_store import OrderStore
from src.ibkr_client import IBKRClient, IBKRError

PAPER_ACCT = "DUT160850"


def test_stock_conid_raises_cleanly_on_gateway_error():
    """A dead gateway session returns {"error": ...} — must be a clean
    IBKRError (→ HTTP 503), never an AttributeError crash."""
    c = FakeIBKRClient()
    c.queue({"error": "Bad Request: no bridge", "statusCode": 400})
    with pytest.raises(IBKRError, match="no bridge"):
        c.stock_conid("SPY")


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class FakeIBKRClient(IBKRClient):
    """Scripted gateway: queue canned responses, record every call."""

    def __init__(self):
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[tuple[str, dict | None]] = []
        self.deletes: list[str] = []
        self._queue: list[FakeResp] = []

    def queue(self, payload, status=200):
        self._queue.append(FakeResp(payload, status))

    def _post(self, path, body=None):
        self.posts.append((path, body))
        assert self._queue, f"no canned response for POST {path}"
        return self._queue.pop(0)

    def _get(self, path, params=None):
        self.gets.append((path, params))
        assert self._queue, f"no canned response for GET {path}"
        return self._queue.pop(0)

    def _delete(self, path):
        self.deletes.append(path)
        assert self._queue, f"no canned response for DELETE {path}"
        return self._queue.pop(0)


def _broker(client=None):
    return PaperBroker(client or FakeIBKRClient(), PAPER_ACCT)


# -- order JSON -----------------------------------------------------------

def test_build_order_stock_market_buy():
    o = PaperBroker.build_order(conid=756733, side="BUY", qty=10)
    assert o["conid"] == 756733
    assert o["side"] == "BUY"
    assert o["orderType"] == "MKT"
    assert o["quantity"] == 10
    assert o["tif"] == "DAY"
    assert o["cOID"].startswith("amuse-") and len(o["cOID"]) <= 64


def test_build_order_option_limit_sell():
    o = PaperBroker.build_order(conid=925788906, side="SELL", qty=1,
                                order_type="LMT", limit_price=0.10, tif="GTC")
    assert o["orderType"] == "LMT" and o["price"] == 0.10
    assert o["tif"] == "GTC" and o["quantity"] == 1


def test_build_order_coids_unique():
    a = PaperBroker.build_order(1, "BUY", 1)["cOID"]
    b = PaperBroker.build_order(1, "BUY", 1)["cOID"]
    assert a != b


# -- place: the three IBKR response shapes --------------------------------

def test_place_success_shape():
    c = FakeIBKRClient()
    c.queue([{"order_id": "1234567", "order_status": "Submitted"}])
    b = _broker(c)
    order = PaperBroker.build_order(756733, "BUY", 10)
    res = b.place(PAPER_ACCT, order)
    assert res["order_id"] == "1234567"
    assert res["status"] == "Submitted"
    path, body = c.posts[0]
    assert path == f"/iserver/account/{PAPER_ACCT}/orders"
    assert body == {"orders": [order]}


def test_place_confirm_required_does_not_auto_confirm():
    c = FakeIBKRClient()
    c.queue([{"id": "reply-abc", "message": ["Price exceeds percentage constraint"],
              "messageIds": ["o163"]}])
    b = _broker(c)
    order = PaperBroker.build_order(756733, "BUY", 10)
    res = b.place(PAPER_ACCT, order)
    assert res["needs_confirm"] is True
    assert res["reply_id"] == "reply-abc"
    assert "Price exceeds" in res["messages"][0]
    # the broker must NOT confirm on its own — no reply call happened
    assert all("/iserver/reply" not in p for p, _ in c.posts)


def test_place_error_shape_raises_with_ibkr_message():
    c = FakeIBKRClient()
    c.queue({"error": "We cannot accept an order at the limit price you selected"})
    b = _broker(c)
    with pytest.raises(BrokerRejected, match="limit price"):
        b.place(PAPER_ACCT, PaperBroker.build_order(1, "BUY", 1,
                                                   order_type="LMT",
                                                   limit_price=99999))


def test_confirm_loops_cascading_replies():
    c = FakeIBKRClient()
    c.queue([{"id": "reply-2", "message": ["second warning"]}])
    c.queue([{"order_id": "1234567", "order_status": "Submitted"}])
    b = _broker(c)
    res = b.confirm("reply-1")
    assert res["order_id"] == "1234567"
    paths = [p for p, _ in c.posts]
    assert paths == ["/iserver/reply/reply-1", "/iserver/reply/reply-2"]
    assert c.posts[0][1] == {"confirmed": True}


def test_confirm_error_mid_loop_raises():
    c = FakeIBKRClient()
    c.queue({"error": "order no longer active"})
    b = _broker(c)
    with pytest.raises(BrokerRejected, match="no longer active"):
        b.confirm("reply-1")


# -- paper-account guard ---------------------------------------------------

def test_guard_refuses_foreign_account_without_any_http():
    c = FakeIBKRClient()
    b = _broker(c)
    with pytest.raises(BrokerGuardError, match="non-paper"):
        b.place("U9999999", PaperBroker.build_order(1, "BUY", 1))
    assert c.posts == [] and c.gets == [] and c.deletes == []


def test_guard_refuses_empty_account_id():
    with pytest.raises(BrokerGuardError):
        PaperBroker(FakeIBKRClient(), "")


# -- whatif preview --------------------------------------------------------

def test_whatif_returns_margin_block():
    c = FakeIBKRClient()
    c.queue({"impact": {"equity": 100.0}, "warn": []})
    b = _broker(c)
    order = PaperBroker.build_order(756733, "BUY", 10)
    out = b.whatif(PAPER_ACCT, order)
    assert out["impact"]["equity"] == 100.0
    path, body = c.posts[0]
    assert path == f"/iserver/account/{PAPER_ACCT}/orders/whatif"


# -- tickets (OrderStore) ---------------------------------------------------

def _ledger(tmp_path):
    return OrderStore(str(tmp_path / "t.db"))


def test_ticket_issue_and_redeem(tmp_path):
    ledger = _ledger(tmp_path)
    order = PaperBroker.build_order(756733, "BUY", 10)
    tid = ledger.issue_ticket(order, signal_id=16, ttl_sec=900)
    assert tid
    row = ledger.redeem_ticket(tid, order)
    assert row["status"] == "USED"
    # single-use: second redeem fails
    with pytest.raises(BrokerGuardError, match="already used"):
        ledger.redeem_ticket(tid, order)


def test_ticket_tamper_rejected(tmp_path):
    ledger = _ledger(tmp_path)
    order = PaperBroker.build_order(756733, "BUY", 10)
    tid = ledger.issue_ticket(order, ttl_sec=900)
    tampered = dict(order, quantity=9999)
    with pytest.raises(BrokerGuardError, match="does not match"):
        ledger.redeem_ticket(tid, tampered)


def test_ticket_expiry_rejected(tmp_path):
    ledger = _ledger(tmp_path)
    order = PaperBroker.build_order(756733, "BUY", 10)
    tid = ledger.issue_ticket(order, ttl_sec=-10)  # already expired
    with pytest.raises(BrokerGuardError, match="expired"):
        ledger.redeem_ticket(tid, order)


def test_ticket_unknown_rejected(tmp_path):
    ledger = _ledger(tmp_path)
    order = PaperBroker.build_order(756733, "BUY", 10)
    with pytest.raises(BrokerGuardError, match="unknown ticket"):
        ledger.redeem_ticket("nope", order)


# -- broker order records ----------------------------------------------------

def test_record_and_update_broker_order(tmp_path):
    ledger = _ledger(tmp_path)
    order = PaperBroker.build_order(756733, "BUY", 10)
    oid = ledger.record_broker_order("tick-1", order, symbol="SPY",
                                     signal_id=16)
    ledger.update_broker_order(oid, status="PLACED", ibkr_order_id="1234567")
    row = ledger.conn.execute(
        "SELECT status, ibkr_order_id, symbol FROM broker_orders WHERE id=?",
        (oid,)).fetchone()
    assert row["status"] == "PLACED" and row["ibkr_order_id"] == "1234567"


# -- cancel ------------------------------------------------------------------

def test_cancel_sends_delete_for_order_id():
    c = FakeIBKRClient()
    c.queue({"orderId": 1234567, "status": "Cancelled"})
    b = _broker(c)
    out = b.cancel(PAPER_ACCT, 1234567)
    assert out["status"] == "Cancelled"
    assert c.deletes == [f"/iserver/account/{PAPER_ACCT}/order/1234567"]


def test_cancel_refuses_minus_one():
    c = FakeIBKRClient()
    b = _broker(c)
    with pytest.raises(BrokerGuardError, match="cancel-all"):
        b.cancel(PAPER_ACCT, -1)
    assert c.deletes == []


# -- runner isolation: the engine never routes orders -------------------------

def test_runner_never_touches_order_endpoints(monkeypatch):
    """run_cycle must not POST to /orders — no auto-routing path may exist."""
    from src.engine import runner
    from src.engine.runner import run_cycle

    monkeypatch.setattr(runner, "get_account_state", lambda client: {
        "account_id": PAPER_ACCT, "positions": [], "net_liquidation": 100_000,
        "cash_by_currency": {"USD": 100_000}, "buying_power": 100_000,
        "available_funds": 100_000, "gross_position_value": 0,
        "source": "ibkr-paper-live", "fetched_at": "now",
    })

    class RecordingClient(FakeIBKRClient):
        def stock_conid(self, sym):
            return 111

        def history(self, conid, period, bar):
            return []

        def auth_status(self):
            return {"authenticated": True}

    c = RecordingClient()
    cfg = {
        "paper": {"starting_cash": 100_000, "account_id": PAPER_ACCT},
        "allocation": {"equity_sleeve_pct": 50, "options_sleeve_pct": 50},
        "universe": {"intraday": ["SPY"]},
        "strategies": {"intraday_orb": {}},
        "risk": {},
    }
    run_cycle(cfg, c, only="intraday_orb")
    order_posts = [p for p, _ in c.posts if "/orders" in p]
    assert order_posts == []
    assert "broker" not in dir(__import__("src.engine.runner", fromlist=["x"]))
