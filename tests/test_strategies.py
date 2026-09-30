"""Strategy unit tests on synthetic data (no network)."""
from src.strategies.base import StrategyContext
from src.strategies.options_income import OptionsIncome
from src.strategies.us_momentum import USEquityMomentum


def _bars(n, start=100.0, drift=0.5, spike_last=None):
    bars = []
    p = start
    for i in range(n):
        o = p
        c = p + drift
        bars.append({"t": i, "o": o, "h": c + 0.5, "l": o - 0.5, "c": c, "v": 1000})
        p = c
    if spike_last is not None:
        bars[-1]["c"] = spike_last
        bars[-1]["h"] = spike_last + 0.5
    return bars


def test_momentum_breakout_generates_buy():
    strat = USEquityMomentum()
    bars = _bars(60, drift=0.3)
    # force a breakout above the prior 20-day high
    bars[-1]["c"] = bars[-2]["c"] + 5
    bars[-1]["h"] = bars[-1]["c"] + 0.5
    ctx = StrategyContext(bars={"AAA": bars}, sleeve_cash=50_000, sleeve="equity")
    sigs = strat.generate(ctx)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.side == "BUY" and s.symbol == "AAA" and s.qty >= 1


def test_momentum_breakdown_generates_sell():
    strat = USEquityMomentum()
    bars = _bars(60, drift=-0.3)
    bars[-1]["c"] = bars[-2]["c"] - 5
    bars[-1]["l"] = bars[-1]["c"] - 0.5
    ctx = StrategyContext(bars={"AAA": bars}, sleeve_cash=50_000, sleeve="equity")
    sigs = strat.generate(ctx)
    assert len(sigs) == 1 and sigs[0].side == "SELL"


def test_momentum_flat_market_no_signal():
    strat = USEquityMomentum()
    bars = _bars(60, drift=0.0)
    ctx = StrategyContext(bars={"AAA": bars}, sleeve_cash=50_000, sleeve="equity")
    assert strat.generate(ctx) == []


def test_options_income_picks_otm_put():
    strat = OptionsIncome()
    # Greeks now required (strategy filters missing Greeks conservatively).
    # Plausible 31-DTE ~5% OTM put Greeks: |delta| 0.10-0.30, IV >= 12, |theta| >= 0.01.
    chain = [
        {"strike": 640.0, "expiry": "20251031", "right": "P", "dte": 31, "bid": 2.1, "ask": 2.3,
         "delta": -0.22, "iv_pct": 18.0, "theta": -0.025},
        {"strike": 630.0, "expiry": "20251031", "right": "P", "dte": 31, "bid": 1.4, "ask": 1.6,
         "delta": -0.17, "iv_pct": 16.0, "theta": -0.020},
        {"strike": 620.0, "expiry": "20251031", "right": "P", "dte": 31, "bid": 0.9, "ask": 1.1,
         "delta": -0.12, "iv_pct": 14.0, "theta": -0.015},
        {"strike": 640.0, "expiry": "20251031", "right": "C", "dte": 31, "bid": 5.0, "ask": 5.2,
         "delta": 0.55, "iv_pct": 18.0, "theta": -0.030},
        {"strike": 600.0, "expiry": "20251128", "right": "P", "dte": 59, "bid": 1.0, "ask": 1.2,
         "delta": -0.10, "iv_pct": 15.0, "theta": -0.012},
    ]
    # price 663 -> 5% OTM target = 629.85 -> closest put in 30-45 DTE is 630
    # (sleeve sized so one 630-strike CSP fits: 25% of 500k = 125k > 63k collateral)
    ctx = StrategyContext(quotes={"SPY": {"price": 663.0}}, chains={"SPY": chain},
                          sleeve_cash=500_000, sleeve="options")
    sigs = strat.generate(ctx)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.side == "SELL_PUT" and s.meta["strike"] == 630.0
    assert s.status == "CANDIDATE" and s.qty >= 1


def test_options_income_no_chain_no_signal():
    strat = OptionsIncome()
    ctx = StrategyContext(quotes={"SPY": {"price": 663.0}}, chains={},
                          sleeve_cash=50_000, sleeve="options")
    assert strat.generate(ctx) == []
