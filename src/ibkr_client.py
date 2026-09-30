"""Read-only IBKR Client Portal Gateway client.

Talks to the local ibkr-gateway container (self-signed cert, verify=False is
only for this localhost/Tailscale-local default). Implements market-data and
account reads only — there are deliberately no order endpoints in this client.
"""
from __future__ import annotations

import httpx


class IBKRError(RuntimeError):
    pass


class IBKRClient:
    def __init__(self, base_url: str, verify_ssl: bool = False, timeout: float = 15):
        self.base = base_url.rstrip("/")
        self.client = httpx.Client(verify=verify_ssl, timeout=timeout)

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        try:
            r = self.client.get(f"{self.base}{path}", params=params)
        except httpx.HTTPError as e:
            raise IBKRError(f"gateway unreachable: {e}") from e
        if r.status_code == 401:
            raise IBKRError("not authenticated — log in at the gateway URL first")
        return r

    def _post(self, path: str, body: dict) -> httpx.Response:
        try:
            r = self.client.post(f"{self.base}{path}", json=body)
        except httpx.HTTPError as e:
            raise IBKRError(f"gateway unreachable: {e}") from e
        if r.status_code == 401:
            raise IBKRError("not authenticated — log in at the gateway URL first")
        return r

    def _json(self, r: httpx.Response, what: str):
        if r.status_code == 401:
            raise IBKRError("not authenticated — log in at the gateway URL first")
        try:
            return r.json()
        except ValueError:
            body = (r.text or "").strip()[:120]
            raise IBKRError(
                f"gateway returned HTTP {r.status_code} (non-JSON) for {what}: "
                f"{body or '<empty>'} — log in at the gateway URL first")

    # -- session / account ------------------------------------------------
    def auth_status(self) -> dict:
        return self._json(self._get("/iserver/auth/status"), "auth/status")

    def accounts(self) -> list[dict]:
        return self._json(self._get("/portfolio/accounts"), "accounts")

    def positions(self, account: str) -> list[dict]:
        return self._json(self._get(f"/portfolio/{account}/positions/0"), "positions")

    # -- contracts / market data ------------------------------------------
    def search(self, symbol: str) -> list[dict]:
        return self._json(self._get("/iserver/secdef/search", {"symbol": symbol}), "search")

    def stock_conid(self, symbol: str) -> int:
        for c in self.search(symbol):
            if c.get("secType") == "STK" or "secType" not in c:
                return int(c["conid"])
        raise IBKRError(f"no stock contract found for {symbol}")

    def snapshot(self, conids: list[int], fields: list[str] | None = None) -> list[dict]:
        params = {"conids": ",".join(str(c) for c in conids),
                  "fields": ",".join(fields or ["31", "84", "86"])}
        return self._json(self._get("/iserver/marketdata/snapshot", params), "snapshot")

    def history(self, conid: int, period: str = "1y", bar: str = "1d") -> list[dict]:
        r = self._post("/iserver/marketdata/history",
                       {"conid": str(conid), "period": period, "bar": bar, "outsideRth": False})
        data = self._json(r, "history")
        return data.get("data", data)

    def put_strikes(self, conid: int, month: str) -> list[dict]:
        """Option strikes for an underlying conid and expiry month (YYYYMM)."""
        r = self._get("/iserver/secdef/strikes",
                      {"conid": str(conid), "sectype": "OPT", "month": month})
        return self._json(r, "strikes").get("put", [])
