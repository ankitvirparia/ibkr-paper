"""Options income: cash-secured put candidates on index ETFs.

Paper only, candidates only in MVP. Uses real option chain strikes from IBKR
(via ctx.chains) to pick ~5% OTM puts, 30-45 DTE, filtered by Black-Scholes
Greeks (delta, IV, theta). Sizing keeps each put cash-secured within a
fraction of the options sleeve.

Chain rows expected: {"strike": float, "expiry": "YYYYMM", "right": "P"/"C",
"dte": int, "bid": float|None, "ask": float|None,
"iv_pct": float|None, "delta": float|None, "theta": float|None}
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
        # Greek filters (deltas are negative for puts; we compare abs values)
        self.min_delta = float(self.params.get("min_delta", 0.10))
        self.max_delta = float(self.params.get("max_delta", 0.30))
        self.min_iv_pct = float(self.params.get("min_iv_pct", 12.0))
        self.min_theta = float(self.params.get("min_theta", 0.01))
        self.max_candidates = int(self.params.get("max_candidates", 5))

    def generate(self, ctx: StrategyContext) -> list[Signal]:
        # Collect best candidate per symbol, then rank by annualized yield
        candidates: list[tuple[float, dict]] = []  # (score, info)
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
            # Greek filters: delta range, minimum IV, minimum theta decay
            def _greeks_ok(c):
                d = c.get("delta")
                iv = c.get("iv_pct")
                th = c.get("theta")
                if d is None or iv is None or th is None:
                    return False  # no Greeks -> skip (conservative)
                if not (self.min_delta <= abs(d) <= self.max_delta):
                    return False
                if iv < self.min_iv_pct:
                    return False
                if abs(th) < self.min_theta:
                    return False
                return True
            puts = [c for c in puts if _greeks_ok(c)]
            if not puts:
                continue
            # Filter to affordable strikes first (collateral <= max allocation)
            max_collateral = ctx.sleeve_cash * self.max_sleeve_per_put_pct / 100.0
            affordable = [c for c in puts
                          if float(c["strike"]) * 100 <= max_collateral]
            if not affordable:
                continue
            pick = min(affordable, key=lambda c: abs(float(c["strike"]) - target))
            strike = float(pick["strike"])
            collateral_per = strike * 100
            max_qty = math.floor(max_collateral / collateral_per)
            if max_qty < 1:
                continue
            bid = pick.get("bid") or 0.0
            dte = int(pick.get("dte") or 1)
            # Annualized premium yield: (premium / strike) * (365 / dte)
            ann_yield = (bid / strike) * (365.0 / dte) if strike > 0 else 0.0
            candidates.append((ann_yield, {
                "symbol": symbol, "strike": strike, "pick": pick,
                "qty": max_qty, "bid": bid, "ann_yield": ann_yield,
            }))
        # Rank by annualized yield, take top N
        candidates.sort(key=lambda x: x[0], reverse=True)
        signals: list[Signal] = []
        for ann_yield, info in candidates[:self.max_candidates]:
            symbol, strike, pick = info["symbol"], info["strike"], info["pick"]
            max_qty, bid = info["qty"], info["bid"]
            signals.append(Signal(
                strategy=self.name, symbol=symbol, side="SELL_PUT",
                kind="option", qty=max_qty,
                ref_price=float(bid),
                reason=(f"CSP candidate: {symbol} {strike:g}P {pick.get('expiry')} "
                        f"(~{self.otm_pct:g}% OTM, {pick.get('dte')} DTE, "
                        f"delta {pick.get('delta', 0):.2f}, "
                        f"IV {pick.get('iv_pct', 0):.1f}%, "
                        f"theta {pick.get('theta', 0):.3f}, "
                        f"yield {ann_yield:.1%}), "
                        f"cash-secured x{max_qty}"),
                meta={"strike": strike, "expiry": pick.get("expiry"),
                      "dte": pick.get("dte"), "bid": bid, "ask": pick.get("ask"),
                      "delta": pick.get("delta"), "iv_pct": pick.get("iv_pct"),
                      "theta": pick.get("theta"), "ann_yield": ann_yield},
                status="CANDIDATE",
            ))
        return signals
