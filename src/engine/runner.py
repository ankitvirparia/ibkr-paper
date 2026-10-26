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


def _expiry_months(n: int = 3) -> list[str]:
    today = date.today()
    months = []
    for i in range(n):
        m = (today.month - 1 + i) % 12 + 1
        y = today.year + (today.month - 1 + i) // 12
        months.append(f"{y}{m:02d}")
    return months


def _today_et():
    return datetime.now(ET).date()


def _dte_from_maturity(maturity: str) -> int | None:
    """True days-to-expiry from a YYYYMMDD maturity date (ET calendar)."""
    try:
        y, m, d = int(maturity[0:4]), int(maturity[4:6]), int(maturity[6:8])
        return (date(y, m, d) - _today_et()).days
    except Exception:
        return None


def _month_overlaps_window(month: str, min_dte: int, max_dte: int) -> bool:
    """True if any day of this YYYYMM month falls in [min_dte, max_dte]."""
    try:
        import calendar
        y, m = int(month[:4]), int(month[4:6])
        first = date(y, m, 1)
        last = date(y, m, calendar.monthrange(y, m)[1])
        today = _today_et()
        return (first - today).days <= max_dte and (last - today).days >= min_dte
    except Exception:
        return True


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
        diag: dict[str, dict] = {}
        try:
            if strat.kind == "equity":
                for symbol in universe.get(strat.universe_key, []):
                    rows = client.history(conid(symbol), period=strat.history_period,
                                          bar=strat.bar_size)
                    ctx.bars[symbol] = _bars_from_history(rows)
            else:
                opt_symbols = list(universe.get("options_etf", []))
                stock_syms = list(universe.get("options_stocks", []))
                min_dte = int(params.get("min_dte", 30))
                max_dte = int(params.get("max_dte", 45))
                for symbol in opt_symbols + stock_syms:
                    contract_id = conid(symbol)
                    snap = client.snapshot([contract_id], fields=["31"])
                    price = float((snap[0].get("31") if snap else None) or 0)
                    ctx.quotes[symbol] = {"price": price}
                    funnel: dict[str, int] = {"chain": 0, "band": 0, "dte_window": 0,
                                              "quoted": 0, "greeks_computed": 0}
                    chain: list[dict] = []
                    if price:
                        import time
                        months = [m for m in _expiry_months(3)
                                  if _month_overlaps_window(m, min_dte, max_dte)]
                        strikes: set[float] = set()
                        for month in months:
                            for strike_row in client.put_strikes(contract_id, month):
                                strike = (strike_row.get("strike")
                                          if isinstance(strike_row, dict) else strike_row)
                                if isinstance(strike, (int, float)):
                                    strikes.add(float(strike))
                        funnel["chain"] = len(strikes)
                        band = [st for st in sorted(strikes)
                                if 2.0 <= (price - st) / price * 100.0 <= 10.0]
                        funnel["band"] = len(band)
                        is_stock = symbol in stock_syms
                        if is_stock and band:
                            target = float(price) * 0.95
                            band = [min(band, key=lambda st: abs(st - target))]
                        elif len(band) > 7:
                            # The strategy only ever picks the affordable strike
                            # closest to the 5% target, so resolving expiries for
                            # the whole band wastes ~85% of secdef calls. Keep
                            # the 7 strikes closest to target.
                            target = float(price) * 0.95
                            band = sorted(band, key=lambda st: abs(st - target))[:7]
                        kept: list[dict] = []
                        seen_conids: set[int] = set()
                        for strike in band:
                            for month in months:
                                time.sleep(0.15)
                                try:
                                    contracts = client.option_contracts(
                                        contract_id, month, strike, "P")
                                except Exception:
                                    continue
                                for c in contracts:
                                    mat = str(c.get("maturityDate") or "")
                                    dte = _dte_from_maturity(mat)
                                    if dte is None or not (min_dte <= dte <= max_dte):
                                        continue
                                    cc = c.get("conid")
                                    if not cc or cc in seen_conids:
                                        continue
                                    seen_conids.add(cc)
                                    kept.append({"strike": strike, "expiry": mat,
                                                 "dte": dte, "conid": cc})
                        funnel["dte_window"] = len(kept)
                        if kept:
                            snaps: dict[int, dict] = {}
                            try:
                                for row in client.snapshot(
                                        [k["conid"] for k in kept],
                                        fields=["31", "84", "86"]):
                                    if isinstance(row, dict) and row.get("conid") is not None:
                                        snaps[row["conid"]] = row
                            except Exception:
                                snaps = {}
                            from ..strategies.greeks import (
                                implied_vol_put, put_delta, put_theta)
                            for entry in kept:
                                row = snaps.get(entry["conid"], {})
                                try:
                                    bid = float(str(row.get("84", "0")).replace(",", ""))
                                    ask = float(str(row.get("86", "0")).replace(",", ""))
                                    last = float(str(row.get("31", "0")).replace(",", ""))
                                except (ValueError, TypeError):
                                    bid = ask = last = 0.0
                                entry["right"] = "P"
                                entry["bid"] = bid if bid > 0 else None
                                entry["ask"] = ask if ask > 0 else None
                                entry["iv_pct"] = None
                                entry["delta"] = None
                                entry["theta"] = None
                                if bid > 0 and ask > 0:
                                    funnel["quoted"] += 1
                                opt_price = ((bid + ask) / 2.0 if bid > 0 and ask > 0
                                             else (last if last > 0 else 0.0))
                                if opt_price > 0:
                                    t = entry["dte"] / 365.0
                                    iv = implied_vol_put(opt_price, price,
                                                         entry["strike"], t)
                                    if iv is not None:
                                        entry["iv_pct"] = iv * 100.0
                                        entry["delta"] = put_delta(
                                            price, entry["strike"], t, 0.045, iv)
                                        entry["theta"] = put_theta(
                                            price, entry["strike"], t, 0.045, iv)
                                        funnel["greeks_computed"] += 1
                                chain.append(entry)
                    ctx.chains[symbol] = chain
                    diag[symbol] = funnel
        except IBKRError as exc:

            out["errors"].append(f"{strat_name}: {exc}")
            continue

        signals = strat.generate(ctx)
        strat_diag = getattr(strat, "diagnostics", {}) or {}
        per_sym = strat_diag.get("symbols", {}) if isinstance(strat_diag, dict) else {}
        for sym, fun in diag.items():
            sd = per_sym.get(sym, {})
            fun["greeks_ok"] = sd.get("greeks_ok", 0)
            fun["affordable"] = sd.get("affordable", 0)
        out["strategies"][strat_name] = {
            "sleeve": sleeve,
            "sleeve_equity": round(sleeve_equity, 2),
            "signals": len(signals),
            "candidates": len(signals),
            "paper_filled": 0,
            "diagnostics": {"symbols": diag},
            "items": [
                {"strategy": signal.strategy, "symbol": signal.symbol,
                 "side": signal.side, "kind": signal.kind, "qty": signal.qty,
                 "ref_price": signal.ref_price, "reason": signal.reason,
                 "meta": signal.meta, "status": "CANDIDATE"}
                for signal in signals
            ],
        }
    return out
