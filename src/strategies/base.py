"""Pluggable trading strategies: base types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Signal:
    strategy: str
    symbol: str
    side: str          # BUY, SELL, SELL_PUT, ...
    kind: str          # "equity" | "option"
    qty: float = 0     # SELL with qty 0 means "close whole position"
    ref_price: float = 0.0
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    status: str = "CANDIDATE"  # CANDIDATE -> PAPER_FILLED


@dataclass
class StrategyContext:
    """Everything a strategy may read. Strategies never place orders."""
    bars: dict[str, list[dict]] = field(default_factory=dict)   # symbol -> OHLCV dicts
    quotes: dict[str, dict] = field(default_factory=dict)       # symbol -> {"price": float, ...}
    chains: dict[str, list[dict]] = field(default_factory=dict) # symbol -> option chain rows
    sleeve_cash: float = 0.0
    sleeve: str = ""          # "equity" | "options"
    risk: dict = field(default_factory=dict)
    positions: dict[str, dict] = field(default_factory=dict)  # symbol -> {"qty","avg_price"}
    today_entries: set = field(default_factory=set)  # symbols this strategy entered today
    now_et: datetime | None = None  # injectable clock (America/Toronto); tests set this


class Strategy(ABC):
    """Implement generate(); register in src/strategies/__init__.py."""
    name: str = "base"
    sleeve: str = "equity"   # which capital sleeve this strategy may use
    kind: str = "equity"     # "equity" | "option"
    universe_key: str = "equity"  # which config universe list to scan
    bar_size: str = "1d"          # IBKR history bar size
    history_period: str = "1y"    # IBKR history period
    # Whether the runner may auto paper-fill this strategy's signals.
    # Default False (candidate-only) so new strategies never auto-fill without
    # explicit approval. us_momentum opts in to preserve its existing behavior.
    auto_fill: bool = False

    def __init__(self, params: dict | None = None):
        self.params = params or {}

    @abstractmethod
    def generate(self, ctx: StrategyContext) -> list[Signal]:
        """Return candidate signals. Pure function of ctx: no I/O, no orders."""
        raise NotImplementedError
