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

    def iserver_accounts(self) -> list[dict]:
        return self._json(self._get("/iserver/accounts"), "iserver accounts")

    def positions(self, account: str) -> list[dict]:
        return self._json(self._get(f"/portfolio/{account}/positions/0"), "positions")

    def account_summary(self, account: str) -> dict:
        return self._json(self._get(f"/portfolio/{account}/summary"), "account summary")

    def account_ledger(self, account: str) -> dict:
        return self._json(self._get(f"/portfolio/{account}/ledger"), "account ledger")

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

    def snapshot(self, conids: list[int], fields: list[str] | None = None,
                 retries: int = 4, retry_delay: float = 1.5) -> list[dict]:
        """Snapshot with warmth retries.

        The gateway lazily subscribes on first touch: the first call for a
        contract often returns only the conid echo, with fields arriving on
        later calls. Retry until every requested field is present in every
        row (a batch row that never warms just burns the bounded retries).
        """
        import time as _time
        params = {"conids": ",".join(str(c) for c in conids),
                  "fields": ",".join(fields or ["31", "84", "86"])}
        wanted = fields or ["31", "84", "86"]
        result: list[dict] = []
        for attempt in range(max(1, retries)):
            result = self._json(self._get("/iserver/marketdata/snapshot", params), "snapshot")
            if not isinstance(result, list):
                return result
            missing = any(
                row.get(f) is None or str(row.get(f)) in ("", "None")
                for row in result if isinstance(row, dict) for f in wanted)
            if not missing or attempt == max(1, retries) - 1:
                return result
            _time.sleep(retry_delay)
        return result

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

    def option_contracts(self, underlying_conid: int, month: str, strike: float,
                         right: str = "P") -> list[dict]:
        """All option contracts for (underlying, month, strike, right).

        Each row carries maturityDate (YYYYMMDD) — the true expiry. The old
        option_conid() took data[0] blindly, which could be any weekly in
        the month; callers must select by maturityDate.
        """
        r = self._get("/iserver/secdef/info",
                      {"conid": str(underlying_conid), "sectype": "OPT",
                       "month": month, "strike": str(strike), "right": right})
        data = self._json(r, "secdef_info")
        return data if isinstance(data, list) else []

    def _greeks_from_quote(self, opt_conid: int, quote: dict, strike: float,
                           underlying_price: float, dte: int,
                           risk_free: float = 0.045) -> dict | None:
        try:
            bid = float(str(quote.get("84", "0")).replace(",", ""))
            ask = float(str(quote.get("86", "0")).replace(",", ""))
            last = float(str(quote.get("31", "0")).replace(",", ""))
        except (ValueError, TypeError):
            return None
        price = (bid + ask) / 2.0 if bid > 0 and ask > 0 else (last if last > 0 else 0.0)
        if price <= 0 or dte <= 0:
            return None
        t = dte / 365.0
        iv = implied_vol_put(price, underlying_price, strike, t, risk_free)
        if iv is None:
            return None
        return {
            "conid": opt_conid, "bid": bid, "ask": ask, "mid": price,
            "iv": iv, "iv_pct": iv * 100.0,
            "delta": put_delta(underlying_price, strike, t, risk_free, iv),
            "theta": put_theta(underlying_price, strike, t, risk_free, iv),
            "dte": dte,
        }

    def option_greeks_for_contract(self, opt_conid: int, maturity_date: str,
                                   strike: float, underlying_price: float,
                                   risk_free: float = 0.045) -> dict | None:
        """Black-Scholes Greeks for one option contract, TRUE DTE."""
        from datetime import date as _date, datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        try:
            y, m, d = (int(maturity_date[0:4]), int(maturity_date[4:6]),
                       int(maturity_date[6:8]))
            dte = (_date(y, m, d) - _dt.now(_ZI("America/Toronto")).date()).days
        except Exception:
            return None
        if dte <= 0:
            return None
        q = self.option_quote(opt_conid)
        if not q:
            return None
        return self._greeks_from_quote(opt_conid, q, strike, underlying_price,
                                       dte, risk_free)

    def option_greeks(self, underlying_conid: int, month: str, strike: float,
                      right: str, underlying_price: float,
                      risk_free: float = 0.045) -> dict | None:
        """Black-Scholes Greeks for an option. Returns None if price unavailable.

        month may be YYYYMM (legacy: first contract of the month, DTE from
        month-end) or YYYYMMDD (exact maturity: the matching contract, true
        DTE). New callers should pass the exact maturity date.
        """
        if len(month) == 8:
            contracts = self.option_contracts(underlying_conid, month[:6], strike, right)
            match = [c for c in contracts if str(c.get("maturityDate")) == month]
            if not match:
                return None
            return self.option_greeks_for_contract(
                match[0].get("conid"), month, strike, underlying_price, risk_free)
        conid = self.option_conid(underlying_conid, month, strike, right)
        if not conid:
            return None
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
        q = self.option_quote(conid)
        if not q:
            return None
        return self._greeks_from_quote(conid, q, strike, underlying_price,
                                       dte, risk_free)
