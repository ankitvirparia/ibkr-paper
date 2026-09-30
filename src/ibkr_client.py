"""Read-only IBKR Client Portal Gateway client.

Talks to the local ibkr-gateway container (self-signed cert, verify=False is
only for this localhost/Tailscale-local default). Implements market-data and
account reads; order placement lives in engine/broker.py (paper account only,
human-gated) and never runs from the signal runner.
"""
from __future__ import annotations

import httpx

try:
    from .strategies.greeks import implied_vol_put, put_delta, put_theta
except ImportError:
    # fallback for direct module loading
    from strategies.greeks import implied_vol_put, put_delta, put_theta


class IBKRError(RuntimeError):
    pass


class IBKRClient:
    def __init__(self, base_url: str, verify_ssl: bool = False, timeout: float = 15,
                 cookies: dict | None = None):
        self.base = base_url.rstrip("/")
        jar = dict(cookies or {})
        try:
            from .sso_login import load_session_cookies
            jar.update(load_session_cookies())
        except Exception:
            pass
        self.client = httpx.Client(verify=verify_ssl, timeout=timeout, cookies=jar)

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

    def _delete(self, path: str) -> httpx.Response:
        try:
            r = self.client.delete(f"{self.base}{path}")
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
        res = self.search(symbol)
        if isinstance(res, dict):
            # gateway answers 200 with {"error": ...} when the session is down
            raise IBKRError(f"contract search failed for {symbol}: {res.get('error')}")
        for c in res:
            if not isinstance(c, dict):
                continue
            if c.get("secType") == "STK" or "secType" not in c:
                return int(c["conid"])
        raise IBKRError(f"no stock contract found for {symbol}")

    def snapshot(self, conids: list[int], fields: list[str] | None = None) -> list[dict]:
        params = {"conids": ",".join(str(c) for c in conids),
                  "fields": ",".join(fields or ["31", "84", "86"])}
        return self._json(self._get("/iserver/marketdata/snapshot", params), "snapshot")

    def history(self, conid: int, period: str = "1y", bar: str = "1d") -> list[dict]:
        r = self._get("/iserver/marketdata/history",
                      {"conid": str(conid), "period": period, "bar": bar, "outsideRth": "false"})
        data = self._json(r, "history")
        return data.get("data", data)

    def put_strikes(self, conid: int, month: str) -> list[dict]:
        """Option strikes for an underlying conid and expiry month (YYYYMM).
        Cached to disk for 24h (strikes don't change intraday)."""
        import os, time as _time
        cache_dir = "/data/strikes_cache"
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"{conid}_{month}.json")
        # Use cache if < 24h old
        if os.path.exists(cache_file):
            age = _time.time() - os.path.getmtime(cache_file)
            if age < 86400:
                try:
                    import json as _json
                    return _json.load(open(cache_file))
                except Exception:
                    pass
        r = self._get("/iserver/secdef/strikes",
                      {"conid": str(conid), "sectype": "OPT", "month": month})
        result = self._json(r, "strikes").get("put", [])
        try:
            import json as _json
            _json.dump(result, open(cache_file, "w"))
        except Exception:
            pass
        return result

    def option_conid(self, underlying_conid: int, month: str, strike: float,
                     right: str = "P") -> int | None:
        """Option contract conid for underlying/month/strike/right."""
        r = self._get("/iserver/secdef/info",
                      {"conid": str(underlying_conid), "sectype": "OPT",
                       "month": month, "strike": str(strike), "right": right})
        data = self._json(r, "secdef_info")
        if isinstance(data, list) and data:
            return data[0].get("conid")
        return None

    def option_quote(self, opt_conid: int) -> dict:
        """Bid/ask/last for an option contract."""
        snap = self.snapshot([opt_conid], fields=["31", "84", "86"])
        return snap[0] if snap else {}

    def option_greeks(self, underlying_conid: int, month: str, strike: float,
                      right: str, underlying_price: float,
                      risk_free: float = 0.045) -> dict | None:
        """Black-Scholes Greeks for an option. Returns None if price unavailable."""
        conid = self.option_conid(underlying_conid, month, strike, right)
        if not conid:
            return None
        q = self.option_quote(conid)
        try:
            bid = float(str(q.get("84", "0")).replace(",", ""))
            ask = float(str(q.get("86", "0")).replace(",", ""))
        except (ValueError, TypeError):
            return None
        if bid <= 0 or ask <= 0:
            return None
        mid = (bid + ask) / 2.0
        # DTE from month (use month-end as approximation)
        import calendar
        from datetime import date
        try:
            y, m = int(month[:4]), int(month[4:6])
            last = calendar.monthrange(y, m)[1]
            dte = (date(y, m, last) - date.today()).days
        except Exception:
            return None
        if dte <= 0:
            return None
        t = dte / 365.0
        iv = implied_vol_put(mid, underlying_price, strike, t, risk_free)
        if iv is None:
            return None
        return {
            "conid": conid, "bid": bid, "ask": ask, "mid": mid,
            "iv": iv, "iv_pct": iv * 100.0,
            "delta": put_delta(underlying_price, strike, t, risk_free, iv),
            "theta": put_theta(underlying_price, strike, t, risk_free, iv),
            "dte": dte,
        }

