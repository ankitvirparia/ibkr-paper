"""Options income: cash-secured put candidates on index ETFs.

Paper only, candidates only in MVP. Uses real option chain strikes from IBKR
(via ctx.chains) to pick ~5% OTM puts, 30-45 DTE. Sizing keeps each put
cash-secured within a fraction of the options sleeve.

Chain rows expected: {"strike": float, "expiry": "YYYYMMDD", "right": "P"/"C",
"dte": int, "bid": float|None, "ask": float|None}
"""
from __future__ import annotations

import math

from .base import Signal, Strategy, StrategyContext


class OptionsIncome(Strategy):
    name = "options_income"
    sleeve = "options"
    kind = "option"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.otm_pct = float(self.params.get("otm_pct", 5.0))
        self.min_dte = int(self.params.get("min_dte", 30))
        self.max_dte = int(self.params.get("max_dte", 45))
        self.max_sleeve_per_put_pct = float(self.params.get("max_sleeve_per_put_pct", 25.0))

    def generate(self, ctx: StrategyContext) -> list[Signal]:
        signals: list[Signal] = []
        for symbol, quote in ctx.quotes.items():
            price = quote.get("price")
            chain = ctx.chains.get(symbol, [])
            if not price or not chain:
                continue
            target = price * (1 - self.otm_pct / 100.0)
            puts = [c for c in chain
                    if c.get("right") == "P"
                    and self.min_dte <= int(c.get("dte", 0)) <= self.max_dte]
            if not puts:
                continue
            pick = min(puts, key=lambda c: abs(float(c["strike"]) - target))
            strike = float(pick["strike"])
            collateral_per = strike * 100
            max_qty = math.floor(
                ctx.sleeve_cash * self.max_sleeve_per_put_pct / 100.0 / collateral_per)
            if max_qty < 1:
                continue
            bid = pick.get("bid")
            signals.append(Signal(
                strategy=self.name, symbol=symbol, side="SELL_PUT",
                kind="option", qty=max_qty,
                ref_price=float(bid) if bid else 0.0,
                reason=(f"CSP candidate: {strike:g}P {pick.get('expiry')} "
                        f"(~{self.otm_pct:g}% OTM, {pick.get('dte')} DTE), "
                        f"cash-secured x{max_qty}"),
                meta={"strike": strike, "expiry": pick.get("expiry"),
                      "dte": pick.get("dte"), "bid": bid, "ask": pick.get("ask")},
                status="CANDIDATE",
            ))
        return signals
