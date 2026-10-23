"""Fetch live account state, scan strategies, and return signals only."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..ibkr_client import IBKRClient, IBKRError
from ..strategies import STRATEGIES
from ..strategies.base import StrategyContext
from .allocator import Allocator
from .ibkr_state import get_account_state

ET = ZoneInfo("America/Toronto")


def _bars_from_history(rows: list[dict]) -> list[dict]:
    return [{"t": r.get("t"), "o": r.get("o"), "h": r.get("h"),
             "l": r.get("l"), "c": r.get("c"), "v": r.get("v", 0)}
            for r in rows]


def _expiry_months(n: int = 2) -> list[str]:
    today = date.today()
    months = []
    for i in range(n):
        m = (today.month - 1 + i) % 12 + 1
        y = today.year + (today.month - 1 + i) // 12
        months.append(f"{y}{m:02d}")
    return months


def _dte(month):
    """Rough days-to-expiry from YYYYMM (uses month-end)."""
    try:
        import calendar
        from datetime import date as _date
        y, m = int(month[:4]), int(month[4:6])
        last = calendar.monthrange(y, m)[1]
        return (_date(y, m, last) - _date.today()).days
    except Exception:
        return 0


def _position_context(positions: list[dict]) -> dict:
    result = {}
    for position in positions:
        if not isinstance(position, dict):
            continue
        symbol = position.get("symbol") or position.get("ticker")
        quantity = position.get("position", position.get("qty", 0))
        if symbol and quantity:
            result[str(symbol)] = {
                "qty": float(quantity),
                "avg_price": float(position.get("avgPrice", position.get("avgCost", 0)) or 0),
            }
    return result


def run_cycle(cfg: dict, client: IBKRClient, only: str | None = None,
              now_et: datetime | None = None) -> dict:
    """Scan using a fresh guarded account snapshot; never books or routes fills."""
    state = get_account_state(client)
    alloc = Allocator(cfg, account_state=state)
    universe = cfg.get("universe", {})
    out: dict = {"account_state": state, "strategies": {}, "errors": []}
    conid_cache: dict[str, int] = {}

    def conid(symbol: str) -> int:
        if symbol not in conid_cache:
            conid_cache[symbol] = client.stock_conid(symbol)
        return conid_cache[symbol]

    for strat_name, strat_cls in STRATEGIES.items():
        if only and strat_name != only:
            continue
        params = cfg.get("strategies", {}).get(strat_name, {})
        strat = strat_cls(params)
        sleeve = strat.sleeve
        sleeve_equity = alloc.sleeve_equity(sleeve)
        now = now_et or datetime.now(ET)
        ctx = StrategyContext(
            sleeve_cash=sleeve_equity,
            sleeve=sleeve,
            risk=cfg.get("risk", {}),
            positions=_position_context(state["positions"]),
            now_et=now,
        )
        try:
            if strat.kind == "equity":
                for symbol in universe.get(strat.universe_key, []):
                    rows = client.history(conid(symbol), period=strat.history_period,
                                          bar=strat.bar_size)
                    ctx.bars[symbol] = _bars_from_history(rows)
            else:
                opt_symbols = list(universe.get("options_etf", []))
                stock_syms = list(universe.get("options_stocks", []))
                for symbol in opt_symbols + stock_syms:
                    contract_id = conid(symbol)
                    snap = client.snapshot([contract_id], fields=["31"])
                    price = float((snap[0].get("31") if snap else None) or 0)
                    ctx.quotes[symbol] = {"price": price}
                    chain: list[dict] = []
                    import time
                    for month in _expiry_months():
                        time.sleep(0.3)
                        for strike_row in client.put_strikes(contract_id, month):
                            if isinstance(strike_row, dict):
                                strike = strike_row.get("strike")
                                expiry = strike_row.get("expiry") or month
                                dte = strike_row.get("dte", 0)
                            else:
                                strike, expiry, dte = strike_row, month, _dte(month)
                            chain.append({"strike": strike, "expiry": expiry, "right": "P",
                                          "dte": dte, "bid": None, "ask": None})
                    ctx.chains[symbol] = chain
                    try:
                        is_stock = symbol in stock_syms
                        target = float(price) * 0.95 if price else 0
                        candidates = [entry for entry in chain
                                      if entry.get("strike") and price and
                                      2.0 <= (price - entry["strike"]) / price * 100.0 <= 10.0]
                        if is_stock and candidates:
                            candidates = [min(candidates,
                                              key=lambda entry: abs(float(entry["strike"]) - target))]
                        for entry in candidates:
                            try:
                                time.sleep(0.2)
                                greeks = client.option_greeks(
                                    contract_id, entry.get("expiry") or "", entry["strike"],
                                    "P", float(price))
                                if greeks:
                                    entry.update({key: greeks[key] for key in
                                                  ("bid", "ask", "iv_pct", "delta", "theta")})
                            except Exception:
                                continue
                    except Exception:
                        pass
        except IBKRError as exc:
            out["errors"].append(f"{strat_name}: {exc}")
            continue

        signals = strat.generate(ctx)
        out["strategies"][strat_name] = {
            "sleeve": sleeve,
            "sleeve_equity": round(sleeve_equity, 2),
            "signals": len(signals),
            "candidates": len(signals),
            "paper_filled": 0,
            "items": [
                {"strategy": signal.strategy, "symbol": signal.symbol,
                 "side": signal.side, "kind": signal.kind, "qty": signal.qty,
                 "ref_price": signal.ref_price, "reason": signal.reason,
                 "meta": signal.meta, "status": "CANDIDATE"}
                for signal in signals
            ],
        }
    return out
