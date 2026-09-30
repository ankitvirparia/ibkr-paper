"""Template for a new strategy. Copy this file, rename the class, and register
it in src/strategies/__init__.py STRATEGIES. No other code changes needed."""
from __future__ import annotations

from .base import Signal, Strategy, StrategyContext


class MyStrategy(Strategy):
    name = "my_strategy"   # unique; used in ledger + API
    sleeve = "equity"      # "equity" or "options" — which capital sleeve it may use
    kind = "equity"        # "equity" or "option"

    def generate(self, ctx: StrategyContext) -> list[Signal]:
        signals: list[Signal] = []
        # ctx.bars:   symbol -> [{"t","o","h","l","c","v"}, ...] (oldest -> newest)
        # ctx.quotes: symbol -> {"price": float, ...}
        # ctx.chains: symbol -> [{"strike","expiry","right","dte","bid","ask"}, ...]
        # ctx.sleeve_cash: cash allocated to this strategy's sleeve
        # return candidate Signal(...) objects; the engine sizes, guards, and
        # paper-fills them. Strategies never place orders.
        return signals
