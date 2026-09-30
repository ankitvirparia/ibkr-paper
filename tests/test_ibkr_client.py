"""IBKR client unit tests with a mocked HTTP transport."""
import httpx
import pytest

from src.ibkr_client import IBKRError, IBKRClient


def _client(handler):
    transport = httpx.MockTransport(handler)
    c = IBKRClient.__new__(IBKRClient)
    c.base = "https://x/v1/api"
    c.client = httpx.Client(transport=transport)
    return c


def test_auth_status_ok():
    def h(req):
        return httpx.Response(200, json={"authenticated": True, "connected": True})
    assert _client(h).auth_status()["authenticated"] is True


def test_auth_401_raises():
    def h(req):
        return httpx.Response(401, text="unauthorized")
    with pytest.raises(IBKRError, match="not authenticated"):
        _client(h).auth_status()


def test_empty_body_raises_clear_error():
    def h(req):
        return httpx.Response(200, text="")
    with pytest.raises(IBKRError, match="non-JSON"):
        _client(h).auth_status()


def test_snapshot_params():
    seen = {}

    def h(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json=[{"conid": 1, "31": 150.0}])
    out = _client(h).snapshot([1])
    assert out[0]["31"] == 150.0
    assert "conids=1" in seen["url"]
