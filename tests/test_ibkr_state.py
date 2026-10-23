"""Live account-state mapping tests; every gateway response is mocked."""
from fastapi.testclient import TestClient
import pytest

from src import api
from src.engine import ibkr_state


ACCOUNT = "DUT160850"


class FakeClient:
    def __init__(self, *, authenticated=True, accounts=None):
        self.authenticated = authenticated
        self.account_ids = [ACCOUNT] if accounts is None else accounts
        self.calls = []

    def auth_status(self):
        self.calls.append("auth_status")
        return {"authenticated": self.authenticated}

    def iserver_accounts(self):
        self.calls.append("iserver_accounts")
        return self.account_ids

    def positions(self, account):
        self.calls.append("positions")
        assert account == ACCOUNT
        return [{"conid": 123, "position": 2, "marketValue": 250.0}]

    def account_summary(self, account):
        self.calls.append("summary")
        assert account == ACCOUNT
        return {
            "netliquidation": {"amount": "1010051.00", "currency": "CAD"},
            "buyingpower": {"amount": "3366838.00", "currency": "CAD"},
            "availablefunds": {"amount": "900000.00", "currency": "CAD"},
            "grosspositionvalue": {"amount": "12000.00", "currency": "CAD"},
        }

    def account_ledger(self, account):
        self.calls.append("ledger")
        assert account == ACCOUNT
        return {
            "CAD": {"cashbalance": {"amount": "1000357.20", "currency": "CAD"}},
            "USD": {"cashbalance": {"amount": "6290.50", "currency": "USD"}},
        }


def test_state_maps_positions_summary_and_multi_currency_cash(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(ibkr_state, "_session_initialized", False)

    state = ibkr_state.get_account_state(client)

    assert state["account_id"] == ACCOUNT
    assert state["positions"] == [{"conid": 123, "position": 2, "marketValue": 250.0}]
    assert state["cash_by_currency"] == {"CAD": 1000357.2, "USD": 6290.5}
    assert state["net_liquidation"] == 1010051.0
    assert state["buying_power"] == 3366838.0
    assert state["available_funds"] == 900000.0
    assert state["gross_position_value"] == 12000.0
    assert state["source"] == "ibkr-paper-live"
    assert state["fetched_at"]
    assert client.calls == ["auth_status", "iserver_accounts", "positions", "summary", "ledger"]


def test_unauthenticated_session_is_not_live(monkeypatch):
    client = FakeClient(authenticated=False)
    monkeypatch.setattr(ibkr_state, "_session_initialized", False)

    with pytest.raises(ibkr_state.SessionNotLive):
        ibkr_state.get_account_state(client)

    assert client.calls == ["auth_status"]


def test_foreign_account_is_refused_before_state_reads(monkeypatch):
    client = FakeClient(accounts=[ACCOUNT, "U9999999"])
    monkeypatch.setattr(ibkr_state, "_session_initialized", False)

    with pytest.raises(ibkr_state.AccountGuardError):
        ibkr_state.get_account_state(client)

    assert client.calls == ["auth_status", "iserver_accounts"]


def test_iserver_accounts_initializes_once(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(ibkr_state, "_session_initialized", False)

    ibkr_state.get_account_state(client)
    ibkr_state.get_account_state(client)

    assert client.calls.count("iserver_accounts") == 1


def test_account_endpoint_returns_503_when_session_is_not_live(monkeypatch):
    def not_live(*args, **kwargs):
        raise ibkr_state.SessionNotLive()

    monkeypatch.setattr(api, "get_account_state", not_live)
    response = TestClient(api.app).get("/ibkr/account")

    assert response.status_code == 503
    assert response.json() == {"status": "session_not_live"}
