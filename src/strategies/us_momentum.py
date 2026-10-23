"""US equity momentum: 20-day breakout + 50-day MA trend filter.

Paper only. Position size risks a fixed % of the equity sleeve per trade,
with the stop at 2x ATR(14).
"""
from __future__ import annotations

import math
from statistics import mean

from .base import Signal, Strategy, StrategyContext


def _atr(bars: list[dict], period: int = 14) -> float:
    trs = []
    prev_close = bars[0]["c"]
    for b in bars:
        tr = max(b["h"] - b["l"], abs(b["h"] - prev_close), abs(b["l"] - prev_close))
        trs.append(tr)
        prev_close = b["c"]
    return mean(trs[-period:]) if len(trs) >= period else mean(trs)


class USEquityMomentum(Strategy):
    name = "us_momentum"
    sleeve = "equity"
    kind = "equity"
    auto_fill = False

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.lookback = int(self.params.get("lookback", 20))
        self.trend_ma = int(self.params.get("trend_ma", 50))
        self.atr_period = int(self.params.get("atr_period", 14))
        self.risk_pct = float(self.params.get("risk_per_trade_pct", 1.0))

    def generate(self, ctx: StrategyContext) -> list[Signal]:
        signals: list[Signal] = []
        for symbol, bars in ctx.bars.items():
            if len(bars) < self.trend_ma + 2:
                continue
            closes = [b["c"] for b in bars]
            highs = [b["h"] for b in bars]
            lows = [b["l"] for b in bars]
            last = closes[-1]
            prev_high = max(highs[-(self.lookback + 1):-1])
            prev_low = min(lows[-(self.lookback + 1):-1])
            ma = mean(closes[-self.trend_ma:])
            atr = _atr(bars, self.atr_period)

            if last > prev_high and last > ma and atr > 0:
                risk_amt = ctx.sleeve_cash * self.risk_pct / 100.0
                qty = math.floor(risk_amt / (2 * atr))
                if qty >= 1:
                    signals.append(Signal(
                        strategy=self.name, symbol=symbol, side="BUY",
                        kind="equity", qty=qty, ref_price=last,
                        reason=(f"20d breakout: {last:.2f} > prev high {prev_high:.2f}, "
                                f"above 50d MA {ma:.2f}; risk 1% sleeve, stop 2xATR"),
                        meta={"stop_dist": round(2 * atr, 2), "atr": round(atr, 2)},
                    ))
            elif last < prev_low:
                signals.append(Signal(
                    strategy=self.name, symbol=symbol, side="SELL",
                    kind="equity", qty=0, ref_price=last,
                    reason=f"20d breakdown: {last:.2f} < prev low {prev_low:.2f} — exit",
                ))
        return signals
