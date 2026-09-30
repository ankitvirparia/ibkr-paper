"""Intraday opening-range breakout (ORB), long-only. Spec 003.

Rules:
- 5-min bars, RTH only, current session.
- Opening range = high/low of the first `or_minutes` (default 30) from 09:30 ET.
- Entry 10:00-11:30 ET: a 5-min bar closes above the OR high -> BUY.
  One entry per symbol per day. Skip if OR range < min_range_pct.
- Sizing: risk_per_trade_pct of sleeve equity / (entry - OR low).
- Exits: stop at OR low, target at entry + target_r * risk, time exit 15:45 ET.
- Never holds overnight: the time exit flattens everything before the close.

Paper only. Strategies never place orders.
"""
from __future__ import annotations

import math
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from .base import Signal, Strategy, StrategyContext

ET = ZoneInfo("America/Toronto")
SESSION_OPEN = dtime(9, 30)


def _et(ms: float) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=ET)


class IntradayORB(Strategy):
    name = "intraday_orb"
    sleeve = "equity"
    kind = "equity"
    universe_key = "intraday"
    bar_size = "5min"
    history_period = "1d"

    def _p(self, key: str, default):
        return self.params.get(key, default)

    def generate(self, ctx: StrategyContext) -> list[Signal]:
        now = ctx.now_et or datetime.now(ET)
        if now.tzinfo is None:
            now = now.replace(tzinfo=ET)
        today = now.date()

        or_minutes = int(self._p("or_minutes", 30))
        entry_start = dtime.fromisoformat(self._p("entry_start", "10:00"))
        entry_end = dtime.fromisoformat(self._p("entry_end", "11:30"))
        time_exit = dtime.fromisoformat(self._p("time_exit", "15:45"))
        min_range_pct = float(self._p("min_range_pct", 0.15))
        risk_pct = float(self._p("risk_per_trade_pct", 0.5))
        target_r = float(self._p("target_r", 2.0))

        or_end = dtime(SESSION_OPEN.hour + (SESSION_OPEN.minute + or_minutes) // 60,
                       (SESSION_OPEN.minute + or_minutes) % 60)
        need_bars = or_minutes // 5

        signals: list[Signal] = []
        for symbol, bars in ctx.bars.items():
            day_bars = [b for b in bars
                        if b.get("t") and _et(b["t"]).date() == today]
            if not day_bars:
                continue
            or_bars = [b for b in day_bars
                       if SESSION_OPEN <= _et(b["t"]).time() < or_end]
            if len(or_bars) < need_bars:
                continue  # incomplete opening range (half day / missing data)
            or_high = max(b["h"] for b in or_bars)
            or_low = min(b["l"] for b in or_bars)
            mid = (or_high + or_low) / 2
            if mid <= 0 or (or_high - or_low) / mid * 100 < min_range_pct:
                continue  # too tight to trade — chop filter
            last = day_bars[-1]
            pos_qty = (ctx.positions.get(symbol) or {}).get("qty", 0) or 0

            if pos_qty > 0:
                entry = (ctx.positions[symbol] or {}).get("avg_price") or last["c"]
                stop = or_low
                target = entry + target_r * (entry - stop)
                reason = None
                if last["l"] <= stop:
                    reason = (f"ORB stop hit: {last['l']:.2f} <= OR low {stop:.2f}")
                elif last["h"] >= target:
                    reason = (f"ORB target hit: {last['h']:.2f} >= "
                              f"{target_r:g}R {target:.2f}")
                elif now.time() >= time_exit:
                    reason = (f"ORB time exit {time_exit.strftime('%H:%M')}: "
                              f"flatten before close")
                if reason:
                    signals.append(Signal(
                        strategy=self.name, symbol=symbol, side="SELL",
                        kind="equity", qty=0, ref_price=last["c"],
                        reason=reason,
                        meta={"stop": round(stop, 2), "target": round(target, 2),
                              "or_high": or_high, "or_low": or_low},
                    ))
            else:
                if symbol in ctx.today_entries:
                    continue  # one entry per symbol per day
                tnow = now.time()
                if not (entry_start <= tnow <= entry_end):
                    continue
                if last["c"] > or_high:
                    risk_amt = ctx.sleeve_cash * risk_pct / 100.0
                    stop_dist = last["c"] - or_low
                    if stop_dist <= 0:
                        continue
                    qty = math.floor(risk_amt / stop_dist)
                    if qty < 1:
                        continue
                    target = last["c"] + target_r * stop_dist
                    signals.append(Signal(
                        strategy=self.name, symbol=symbol, side="BUY",
                        kind="equity", qty=qty, ref_price=last["c"],
                        reason=(f"ORB breakout: {last['c']:.2f} > OR high "
                                f"{or_high:.2f} (OR {or_low:.2f}-{or_high:.2f}); "
                                f"risk {risk_pct:g}% sleeve, stop {or_low:.2f}"),
                        meta={"stop": round(or_low, 2),
                              "target": round(target, 2),
                              "or_high": or_high, "or_low": or_low},
                    ))
        return signals
