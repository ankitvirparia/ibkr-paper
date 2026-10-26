"""Spec 006 — scanner optimization: snapshot warmth, true expiry, funnel."""
from datetime import date, timedelta

import httpx
import yaml

from src.ibkr_client import IBKRClient
from src.strategies.base import StrategyContext
from src.strategies.greeks import put_delta, put_theta
from src.strategies.options_income import OptionsIncome


def _client(handler):
    transport = httpx.MockTransport(handler)
    c = IBKRClient.__new__(IBKRClient)
    c.base = "https://x/v1/api"
    c.client = httpx.Client(transport=transport)
    return c


def test_snapshot_retries_until_fields_present():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=[{"conid": 1}])
        return httpx.Response(200, json=[{"conid": 1, "31": "100.0", "84": "1.00", "86": "1.20"}])
    out = _client(h).snapshot([1], fields=["31", "84", "86"], retry_delay=0)
    assert out[0]["84"] == "1.00"
    assert calls["n"] == 2


def test_snapshot_batch_is_one_call():
    seen = {"n": 0, "url": ""}

    def h(req):
        seen["n"] += 1
        seen["url"] = str(req.url)
        return httpx.Response(200, json=[{"conid": i, "84": "1.0", "86": "1.2"} for i in (1, 2, 3)])
    out = _client(h).snapshot([1, 2, 3], fields=["84", "86"], retry_delay=0)
    assert seen["n"] == 1
    assert "conids=1%2C2%2C3" in seen["url"] or "conids=1,2,3" in seen["url"]
    assert len(out) == 3


def test_option_contracts_returns_maturities():
    def h(req):
        return httpx.Response(200, json=[
            {"conid": 11, "maturityDate": "20261102", "strike": 725.0, "right": "P"},
            {"conid": 22, "maturityDate": "20261127", "strike": 725.0, "right": "P"},
        ])
    contracts = _client(h).option_contracts(756733, "202611", 725.0, "P")
    assert [c["conid"] for c in contracts] == [11, 22]
    assert contracts[1]["maturityDate"] == "20261127"


def test_greeks_use_true_dte_not_month_end():
    import calendar
    today = date.today()
    maturity = (today + timedelta(days=7)).strftime("%Y%m%d")
    month_end_dte = (date(today.year, today.month,
                          calendar.monthrange(today.year, today.month)[1]) - today).days

    def h(req):
        return httpx.Response(200, json=[{"conid": 9, "84": "0.33", "86": "0.35"}])
    g = _client(h).option_greeks_for_contract(9, maturity, 725.0, 765.0)
    assert g is not None
    assert g["dte"] == 7
    assert g["dte"] != month_end_dte or month_end_dte == 7
    assert g["delta"] == put_delta(765.0, 725.0, 7 / 365.0, 0.045, g["iv"])
    assert g["theta"] == put_theta(765.0, 725.0, 7 / 365.0, 0.045, g["iv"])


def _ctx_for(rows, price=765.0, sleeve_cash=1_000_000.0):
    return StrategyContext(
        quotes={"SPY": {"price": price}},
        chains={"SPY": rows},
        sleeve_cash=sleeve_cash,
        sleeve="options",
    )


def test_strategy_prefers_higher_bid_on_same_strike():
    rows = [
        {"strike": 725.0, "expiry": "20261127", "right": "P", "dte": 32,
         "bid": 1.00, "ask": 1.10, "iv_pct": 15.0, "delta": -0.20, "theta": -0.03},
        {"strike": 725.0, "expiry": "20261204", "right": "P", "dte": 39,
         "bid": 2.50, "ask": 2.60, "iv_pct": 15.0, "delta": -0.20, "theta": -0.03},
    ]
    strat = OptionsIncome({"max_sleeve_per_put_pct": 10.0})
    signals = strat.generate(_ctx_for(rows))
    assert len(signals) == 1
    assert signals[0].meta["expiry"] == "20261204"
    assert signals[0].meta["bid"] == 2.50


def test_strategy_records_diagnostics():
    rows = [
        {"strike": 725.0, "expiry": "20261127", "right": "P", "dte": 32,
         "bid": 2.50, "ask": 2.60, "iv_pct": 15.0, "delta": -0.20, "theta": -0.03},
        {"strike": 700.0, "expiry": "20261127", "right": "P", "dte": 32,
         "bid": 1.00, "ask": 1.10, "iv_pct": 15.0, "delta": None, "theta": None},
    ]
    strat = OptionsIncome({"max_sleeve_per_put_pct": 10.0})
    strat.generate(_ctx_for(rows))
    d = strat.diagnostics["symbols"]["SPY"]
    assert d["puts_seen"] == 2
    assert d["greeks_ok"] == 1
    assert d["affordable"] == 1


def test_config_csp_cap_is_standing_25_percent():
    # OPEN POLICY QUESTION (2026-10-26): the CSP cap is 25% of sleeve while
    # the allocator guard is 10%. Aligning to 10% would make every SPY/QQQ
    # put unaffordable (e.g. 725 strike = $72,500 collateral > $50,500 cap),
    # so the standing 25% is kept until Ankit rules on the guard. This test
    # pins the value so any change is deliberate, not drift.
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    assert cfg["strategies"]["options_income"]["max_sleeve_per_put_pct"] == 25.0
    assert cfg["risk"]["max_position_pct"] == 10


def test_runner_funnel_and_true_expiry(monkeypatch):
    from src.engine import runner

    today = date.today()
    in_win = (today + timedelta(days=35)).strftime("%Y%m%d")
    out_win = (today + timedelta(days=7)).strftime("%Y%m%d")

    class FakeClient:
        def stock_conid(self, symbol):
            return 756733

        def snapshot(self, conids, fields=None):
            rows = []
            for c in conids:
                if c == 756733:
                    rows.append({"conid": c, "31": "765.0"})
                else:
                    rows.append({"conid": c, "31": "2.55", "84": "2.50", "86": "2.60"})
            return rows

        def __init__(self):
            self.strikes_queried: set[float] = set()

        def put_strikes(self, conid, month):
            return [690.0 + 5.0 * i for i in range(12)]

        def option_contracts(self, conid, month, strike, right):
            self.strikes_queried.add(strike)
            return [{"conid": 11, "maturityDate": out_win, "strike": strike},
                    {"conid": 22, "maturityDate": in_win, "strike": strike}]

    monkeypatch.setattr(runner, "get_account_state", lambda client: {
        "net_liquidation": 2_000_000.0, "positions": [],
        "account_id": "DUT160850"})
    cfg = {"universe": {"options_etf": ["SPY"], "options_stocks": []},
           "strategies": {"options_income": {"max_sleeve_per_put_pct": 10.0}},
           "allocation": {"equity_sleeve_pct": 50, "options_sleeve_pct": 50},
           "risk": {"max_position_pct": 10, "max_total_positions": 12,
                    "max_daily_loss_pct": 2}}
    fake = FakeClient()
    out = runner.run_cycle(cfg, fake, only="options_income")
    strat_out = out["strategies"]["options_income"]
    assert strat_out["signals"] == 1
    # 12 strikes in band, but only the 7 closest to target get secdef calls
    assert len(fake.strikes_queried) <= 7
    assert 725.0 in fake.strikes_queried
    assert strat_out["items"][0]["meta"]["expiry"] == in_win
    assert strat_out["items"][0]["meta"]["dte"] == 35
    funnel = strat_out["diagnostics"]["symbols"]["SPY"]
    for key in ("chain", "band", "dte_window", "quoted", "greeks_ok", "affordable"):
        assert key in funnel
