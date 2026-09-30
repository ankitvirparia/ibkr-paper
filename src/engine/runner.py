"""Paper run cycle: fetch data -> strategies -> allocate -> paper fills."""
from __future__ import annotations

from datetime import date, timedelta

from ..ibkr_client import IBKRClient, IBKRError
from ..strategies import STRATEGIES
from ..strategies.base import StrategyContext
from .allocator import Allocator
from .paper_ledger import PaperLedger


def _bars_from_history(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        out.append({"t": r.get("t"), "o": r.get("o"), "h": r.get("h"),
                    "l": r.get("l"), "c": r.get("c"), "v": r.get("v", 0)})
    return out


def _expiry_months(n: int = 3) -> list[str]:
    today = date.today()
    months = []
    for i in range(n):
        m = (today.month - 1 + i) % 12 + 1
        y = today.year + (today.month - 1 + i) // 12
        months.append(f"{y}{m:02d}")
    return months


def run_cycle(cfg: dict, client: IBKRClient, ledger: PaperLedger) -> dict:
    alloc = Allocator(cfg)
    universe = cfg.get("universe", {})
    out: dict = {"strategies": {}, "errors": []}

    try:
        out["auth"] = client.auth_status()
    except IBKRError as e:
        out["errors"].append(str(e))
        return out

    total_equity = ledger.pnl({})["total_equity"] or float(cfg["paper"]["starting_cash"])
    conid_cache: dict[str, int] = {}
    last_prices: dict[str, float] = {}

    def conid(sym: str) -> int:
        if sym not in conid_cache:
            conid_cache[sym] = client.stock_conid(sym)
        return conid_cache[sym]

    for strat_name, strat_cls in STRATEGIES.items():
        params = cfg.get("strategies", {}).get(strat_name, {})
        strat = strat_cls(params)
        sleeve = strat.sleeve
        sleeve_equity = alloc.sleeve_equity(sleeve, total_equity)
        ctx = StrategyContext(sleeve_cash=sleeve_equity, sleeve=sleeve,
                              risk=cfg.get("risk", {}))
        try:
            if strat.kind == "equity":
                for sym in universe.get("equity", []):
                    rows = client.history(conid(sym))
                    ctx.bars[sym] = _bars_from_history(rows)
                    if ctx.bars[sym]:
                        last_prices[sym] = ctx.bars[sym][-1]["c"]
            else:  # option
                for sym in universe.get("options_etf", []):
                    cid = conid(sym)
                    snap = client.snapshot([cid], fields=["31"])
                    price = (snap[0].get("31") if snap else None) or 0
                    ctx.quotes[sym] = {"price": float(price)}
                    last_prices[sym] = float(price)
                    chain: list[dict] = []
                    for month in _expiry_months():
                        for s in client.put_strikes(cid, month):
                            chain.append({"strike": s.get("strike"),
                                          "expiry": s.get("expiry") or month,
                                          "right": "P",
                                          "dte": s.get("dte", 0),
                                          "bid": None, "ask": None})
                    ctx.chains[sym] = chain
        except IBKRError as e:
            out["errors"].append(f"{strat_name}: {e}")
            continue

        signals = strat.generate(ctx)
        filled, skipped = 0, 0
        for sig in signals:
            sig_id = ledger.record_signal(sig)
            if sig.kind == "equity":
                value = sig.qty * sig.ref_price
                open_n = len([p for p in ledger.positions() if p["qty"] > 0])
                decision = alloc.check_new_position(sleeve, value, sleeve_equity, open_n)
                if sig.side == "BUY" and not decision.allowed:
                    skipped += 1
                    continue
                ledger.fill(sig_id)  # paper fill at ref price
                filled += 1
            else:
                # option candidates stay CANDIDATE in MVP (no auto paper fills)
                skipped += 1
        out["strategies"][strat_name] = {
            "sleeve": sleeve, "sleeve_equity": round(sleeve_equity, 2),
            "signals": len(signals), "paper_filled": filled, "candidates": skipped,
        }
    out["pnl"] = ledger.pnl(last_prices)
    return out
