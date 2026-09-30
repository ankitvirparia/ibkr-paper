"""Allocator unit tests."""
from src.engine.allocator import Allocator

CFG = {"allocation": {"equity_sleeve_pct": 50, "options_sleeve_pct": 50},
       "risk": {"max_position_pct": 10, "max_total_positions": 12,
                "max_daily_loss_pct": 2}}


def test_sleeve_split():
    a = Allocator(CFG)
    assert a.sleeve_equity("equity", 100_000) == 50_000
    assert a.sleeve_equity("options", 100_000) == 50_000


def test_position_guard_blocks_oversize():
    a = Allocator(CFG)
    d = a.check_new_position("equity", 6_000, 50_000, 0)
    assert not d.allowed and "exceeds" in d.reason


def test_position_guard_allows_small():
    a = Allocator(CFG)
    d = a.check_new_position("equity", 4_000, 50_000, 0)
    assert d.allowed


def test_position_guard_blocks_too_many():
    a = Allocator(CFG)
    d = a.check_new_position("equity", 100, 50_000, 12)
    assert not d.allowed


def test_kill_switch():
    a = Allocator(CFG)
    assert a.kill_switch(-2.5).allowed  # True == halt
    assert not a.kill_switch(-1.0).allowed
