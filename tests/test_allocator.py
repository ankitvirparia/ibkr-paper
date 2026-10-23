"""Allocator unit tests."""
from src.engine.allocator import Allocator

CFG = {"allocation": {"equity_sleeve_pct": 50, "options_sleeve_pct": 50},
       "risk": {"max_position_pct": 10, "max_total_positions": 12,
                "max_daily_loss_pct": 2}}


LIVE_STATE = {
    "net_liquidation": 1_010_051.0,
    "positions": [],
}


def test_sleeves_and_position_limit_use_live_net_liquidation():
    a = Allocator(CFG, account_state=LIVE_STATE)
    assert a.sleeve_equity("equity") == 505_025.5
    assert a.sleeve_equity("options") == 505_025.5
    assert a.max_position_value("equity") == 50_502.55


def test_position_guard_blocks_oversize():
    a = Allocator(CFG, account_state=LIVE_STATE)
    d = a.check_new_position("equity", 60_000)
    assert not d.allowed and "exceeds" in d.reason


def test_position_guard_allows_small():
    a = Allocator(CFG, account_state=LIVE_STATE)
    d = a.check_new_position("equity", 40_000)
    assert d.allowed


def test_position_guard_blocks_too_many_live_positions():
    state = {**LIVE_STATE, "positions": [{"conid": i} for i in range(12)]}
    a = Allocator(CFG, account_state=state)
    d = a.check_new_position("equity", 100)
    assert not d.allowed


def test_kill_switch():
    a = Allocator(CFG)
    assert a.kill_switch(-2.5).allowed  # True == halt
    assert not a.kill_switch(-1.0).allowed
