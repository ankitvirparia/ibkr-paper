"""Tests for the intraday opening-range-breakout strategy (spec 003).

Pure unit tests on synthetic 5-min bars — no network.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.strategies.base import StrategyContext
from src.strategies.intraday_orb import IntradayORB

ET = ZoneInfo("America/Toronto")
DAY = datetime(2026, 9, 30, tzinfo=ET)  # a Wednesday


def _mbar(hour, minute, o, h, l, c, v=10_000):
    dt = DAY.replace(hour=hour, minute=minute)
    return {"t": int(dt.timestamp() * 1000), "o": o, "h": h, "l": l, "c": c, "v": v}


def _or_bars(or_high=100.0, or_low=99.0):
    """Six 5-min bars forming the 09:30-10:00 opening range."""
    bars = []
    mid = (or_high + or_low) / 2
    for i, minute in enumerate([30, 35, 40, 45, 50, 55]):
        if i == 5:
            o, h, l, c = mid, or_high, or_low, mid
        else:
            o = h = l = c = mid
        bars.append(_mbar(9, minute, o, h, l, c))
    return bars


def _ctx(bars, now, **kw):
    params = dict(sleeve_cash=50_000, sleeve="equity", now_et=now)
    params.update(kw)
    return StrategyContext(bars={"SPY": bars}, **params)


def _at(hour, minute):
    return DAY.replace(hour=hour, minute=minute)


def test_breakout_entry_sizes_by_half_percent_risk():
    strat = IntradayORB()
    bars = _or_bars() + [
        _mbar(10, 0, 99.6, 99.9, 99.4, 99.7),
        _mbar(10, 5, 99.7, 100.6, 99.7, 100.5),  # closes above OR high 100
    ]
    sigs = strat.generate(_ctx(bars, _at(10, 6)))
    assert len(sigs) == 1
    s = sigs[0]
    assert s.side == "BUY" and s.symbol == "SPY"
    # risk 0.5% of 50k = 250; stop distance 100.5-99 = 1.5 -> qty 166
    assert s.qty == 166
    assert s.ref_price == 100.5
    assert s.meta["stop"] == 99.0
    assert s.meta["target"] == pytest.approx(103.5)


def test_no_entry_before_entry_window():
    strat = IntradayORB()
    bars = _or_bars() + [_mbar(10, 0, 99.7, 100.6, 99.7, 100.5)]
    assert strat.generate(_ctx(bars, _at(9, 59))) == []


def test_no_entry_after_entry_window():
    strat = IntradayORB()
    bars = _or_bars() + [_mbar(11, 35, 99.7, 100.6, 99.7, 100.5)]
    assert strat.generate(_ctx(bars, _at(11, 36))) == []


def test_skip_when_or_range_too_tight():
    strat = IntradayORB()
    bars = _or_bars(or_high=100.0, or_low=99.9)  # 0.1% range < 0.15% floor
    bars += [_mbar(10, 5, 99.95, 100.1, 99.9, 100.05)]
    assert strat.generate(_ctx(bars, _at(10, 6))) == []


def test_no_trade_when_or_incomplete():
    strat = IntradayORB()
    bars = _or_bars()[:3]  # half day / missing data
    bars += [_mbar(10, 5, 99.7, 100.6, 99.7, 100.5)]
    assert strat.generate(_ctx(bars, _at(10, 6))) == []


def test_no_entry_when_qty_rounds_to_zero():
    strat = IntradayORB()
    bars = _or_bars() + [_mbar(10, 5, 99.7, 100.6, 99.7, 100.5)]
    # tiny sleeve: 0.5% of $100 = $0.50 risk can't cover 1.5 stop distance
    assert strat.generate(_ctx(bars, _at(10, 6), sleeve_cash=100)) == []


def test_one_entry_per_symbol_per_day():
    strat = IntradayORB()
    bars = _or_bars() + [_mbar(10, 5, 99.7, 100.6, 99.7, 100.5)]
    ctx = _ctx(bars, _at(10, 20), today_entries={"SPY"})
    assert strat.generate(ctx) == []


def _open_position_ctx(bars, now, entry=100.5):
    return _ctx(bars, now,
                positions={"SPY": {"qty": 166, "avg_price": entry}})


def test_stop_exit():
    strat = IntradayORB()
    bars = _or_bars() + [
        _mbar(10, 5, 99.7, 100.6, 99.7, 100.5),
        _mbar(10, 10, 100.4, 100.4, 98.9, 99.2),  # low 98.9 <= stop 99
    ]
    sigs = strat.generate(_open_position_ctx(bars, _at(10, 11)))
    assert len(sigs) == 1
    assert sigs[0].side == "SELL" and sigs[0].qty == 0  # 0 = close all
    assert "stop" in sigs[0].reason


def test_target_exit():
    strat = IntradayORB()
    bars = _or_bars() + [
        _mbar(10, 5, 99.7, 100.6, 99.7, 100.5),
        _mbar(10, 10, 100.4, 103.6, 100.4, 103.0),  # high >= target 103.5
    ]
    sigs = strat.generate(_open_position_ctx(bars, _at(10, 11)))
    assert len(sigs) == 1
    assert sigs[0].side == "SELL" and "target" in sigs[0].reason


def test_time_exit_flattens_before_close():
    strat = IntradayORB()
    bars = _or_bars() + [
        _mbar(10, 5, 99.7, 100.6, 99.7, 100.5),
        _mbar(15, 40, 101.0, 101.2, 100.8, 101.0),
    ]
    sigs = strat.generate(_open_position_ctx(bars, _at(15, 46)))
    assert len(sigs) == 1
    assert sigs[0].side == "SELL" and "time exit" in sigs[0].reason


def test_no_exit_signal_when_flat():
    strat = IntradayORB()
    bars = _or_bars() + [_mbar(15, 40, 101.0, 101.2, 100.8, 101.0)]
    assert strat.generate(_ctx(bars, _at(15, 46))) == []


def test_strategy_declares_intraday_bars():
    strat = IntradayORB()
    assert strat.bar_size == "5min"
    assert strat.history_period == "1d"
    assert strat.name == "intraday_orb"


def test_intraday_orb_does_not_auto_fill():
    # Strategies emit candidate signals only; the runner never simulates fills.
    assert IntradayORB.auto_fill is False


def test_runner_returns_intraday_signals_without_simulated_fills(monkeypatch):
    """A genuine breakout is returned as a candidate with live sizing."""
    from src.engine import runner
    from src.engine.runner import run_cycle

    monkeypatch.setattr(runner, "get_account_state", lambda client: {
        "account_id": "DUT160850", "positions": [], "net_liquidation": 100_000,
        "cash_by_currency": {"USD": 100_000}, "buying_power": 100_000,
        "available_funds": 100_000, "gross_position_value": 0,
        "source": "ibkr-paper-live", "fetched_at": "now",
    })

    day_bars = [
        _mbar(9, 30, 660.0, 661.0, 659.5, 660.5),
        _mbar(9, 35, 660.5, 661.2, 660.0, 661.0),
        _mbar(9, 40, 661.0, 661.5, 660.2, 660.8),
        _mbar(9, 45, 660.8, 661.0, 659.8, 660.0),
        _mbar(9, 50, 660.0, 660.9, 659.7, 660.6),
        _mbar(9, 55, 660.6, 661.1, 660.1, 660.9),
        _mbar(10, 5, 661.0, 662.5, 660.9, 662.0),  # close > OR high 661.5
    ]

    class FakeClient:
        def auth_status(self):
            return {"authenticated": True}

        def stock_conid(self, sym):
            return 111

        def history(self, conid, period, bar):
            assert period == "1d" and bar == "5min"
            return day_bars

    cfg = {
        "allocation": {"equity_sleeve_pct": 50, "options_sleeve_pct": 50},
        "universe": {"intraday": ["SPY"]},
        "strategies": {"intraday_orb": {}},
        "risk": {},
    }
    now = DAY.replace(hour=10, minute=30)  # inside the 10:00-11:30 entry window
    out = run_cycle(cfg, FakeClient(), only="intraday_orb", now_et=now)

    strat_out = out["strategies"]["intraday_orb"]
    assert strat_out["signals"] == 1
    assert strat_out["paper_filled"] == 0
    assert strat_out["candidates"] == 1
    assert strat_out["items"][0]["status"] == "CANDIDATE"
    assert strat_out["items"][0]["side"] == "BUY"
    assert strat_out["items"][0]["qty"] > 0
    assert out["account_state"]["source"] == "ibkr-paper-live"
