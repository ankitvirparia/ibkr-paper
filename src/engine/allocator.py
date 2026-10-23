"""Capital allocation across sleeves + risk guards.

Sleeves: "equity" and "options", each a % of total equity. Guards:
- max position value as % of sleeve equity
- max number of positions per sleeve
- daily-loss kill switch per sleeve (halts NEW signals; exits still allowed)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GuardDecision:
    allowed: bool
    reason: str = ""


class Allocator:
    def __init__(self, cfg: dict, account_state: dict):
        self.account_state = account_state
        self.net_liquidation = float(account_state["net_liquidation"])
        self.open_positions = len(account_state.get("positions", []))
        alloc = cfg.get("allocation", {})
        self.sleeve_pct = {
            "equity": float(alloc.get("equity_sleeve_pct", 50)),
            "options": float(alloc.get("options_sleeve_pct", 50)),
        }
        risk = cfg.get("risk", {})
        self.max_position_pct = float(risk.get("max_position_pct", 10))
        self.max_positions = int(risk.get("max_total_positions", 12))
        self.max_daily_loss_pct = float(risk.get("max_daily_loss_pct", 2))

    def sleeve_equity(self, sleeve: str) -> float:
        return self.net_liquidation * self.sleeve_pct.get(sleeve, 0) / 100.0

    def max_position_value(self, sleeve: str) -> float:
        return self.sleeve_equity(sleeve) * self.max_position_pct / 100.0

    def check_new_position(self, sleeve: str, position_value: float) -> GuardDecision:
        sleeve_equity = self.sleeve_equity(sleeve)
        open_positions = self.open_positions
        if sleeve_equity <= 0:
            return GuardDecision(False, "sleeve equity is zero")
        if position_value > sleeve_equity * self.max_position_pct / 100.0:
            return GuardDecision(
                False,
                f"position {position_value:.0f} exceeds {self.max_position_pct:g}% "
                f"of sleeve ({sleeve_equity:.0f})",
            )
        if open_positions >= self.max_positions:
            return GuardDecision(False, f"already at max {self.max_positions} positions")
        return GuardDecision(True)

    def kill_switch(self, daily_pnl_pct: float) -> GuardDecision:
        """True (halt) when the sleeve lost more than the daily limit."""
        if daily_pnl_pct <= -abs(self.max_daily_loss_pct):
            return GuardDecision(True, f"daily loss {daily_pnl_pct:.2f}% breached limit")
        return GuardDecision(False)
