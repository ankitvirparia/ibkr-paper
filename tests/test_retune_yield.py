"""Spec 007 — retune options_income for the 1.5%/month program target.

Ankit (2026-11-03): target at least 1.5% profit per month on the paper
account. That needs ~3%/month on deployed collateral from the 50% options
sleeve, so the scanner moves closer to the money and only accepts premium
that pays at the target rate:
  otm_pct 5.0 -> 3.0, max_delta 0.30 -> 0.40,
  new min_ann_yield_pct = 30.0 (~2.5% per 30 days on collateral),
  sizing cap unchanged at 25% of sleeve.
"""
from pathlib import Path

import yaml

from src.strategies.base import StrategyContext
from src.strategies.options_income import OptionsIncome

RETUNED = {
    "otm_pct": 3.0,
    "min_dte": 30,
    "max_dte": 45,
    "min_delta": 0.01,
    "max_delta": 0.40,
    "min_iv_pct": 8.0,
    "min_theta": 0.005,
    "max_candidates": 5,
    "max_sleeve_per_put_pct": 25.0,
    "min_ann_yield_pct": 30.0,
}


def _ctx(chain, price=100.0, sleeve_cash=500_000):
    return StrategyContext(quotes={"AAA": {"price": price}},
                           chains={"AAA": chain},
                           sleeve_cash=sleeve_cash, sleeve="options")


def _put(strike, bid, delta=-0.35, iv=20.0, theta=-0.03, dte=36):
    return {"strike": strike, "expiry": "20261204", "right": "P", "dte": dte,
            "bid": bid, "ask": bid + 0.2, "delta": delta, "iv_pct": iv,
            "theta": theta}


def test_config_file_is_retuned():
    cfg = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "config.yaml").read_text())
    oi = cfg["strategies"]["options_income"]
    assert oi["otm_pct"] == 3.0
    assert oi["max_delta"] == 0.40
    assert oi["min_ann_yield_pct"] == 30.0
    # unchanged by the retune
    assert oi["max_sleeve_per_put_pct"] == 25.0
    assert oi["min_dte"] == 30 and oi["max_dte"] == 45


def test_delta_035_passes_retuned_band():
    # delta 0.35 was outside the old 0.30 cap; ann yield of this put:
    # (3.10/97) * (365/36) = 32.4% >= 30% floor.
    sigs = OptionsIncome(RETUNED).generate(_ctx([_put(97.0, 3.10)]))
    assert len(sigs) == 1
    assert sigs[0].meta["strike"] == 97.0


def test_low_yield_rejected_by_floor():
    # Passes every Greek filter but pays too little:
    # (1.00/95) * (365/36) = 10.7% annualized < 30% floor.
    chain = [_put(95.0, 1.00, delta=-0.22, iv=18.0, theta=-0.02)]
    assert OptionsIncome(RETUNED).generate(_ctx(chain)) == []
    # Same chain is a candidate when the floor is off (backward compatible).
    params = dict(RETUNED, min_ann_yield_pct=0.0)
    assert len(OptionsIncome(params).generate(_ctx(chain))) == 1


def test_pick_targets_3pct_otm():
    # Spot 100: the 97 strike (3% OTM) must win over the 95 strike (5% OTM).
    chain = [_put(95.0, 2.95, delta=-0.28), _put(97.0, 3.10, delta=-0.35)]
    sigs = OptionsIncome(RETUNED).generate(_ctx(chain))
    assert len(sigs) == 1
    assert sigs[0].meta["strike"] == 97.0


def test_sizing_still_capped_at_25pct_sleeve():
    # Sleeve 500k -> cap 125k; strike 97 -> 9,700 collateral -> x12 max.
    sigs = OptionsIncome(RETUNED).generate(_ctx([_put(97.0, 3.10)]))
    assert sigs[0].qty == 12
