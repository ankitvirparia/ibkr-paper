"""Spec 008 — IBKR prefixes a stale/closing 'last' price with 'C'
(e.g. 'C24.83'). The Greeks quote parser must tolerate that marker
instead of failing the whole quote (which made option contracts
unresolvable for order previews and silently dropped them from scans).
Found live 2026-11-06: AVGO 295P Dec 11 preview -> 503 'cannot resolve
option contract' while bid/ask were perfectly good.
"""
from src.ibkr_client import IBKRClient


def _bare():
    return IBKRClient.__new__(IBKRClient)


def test_greeks_tolerates_close_prefixed_last():
    q = {"84": "16.90", "86": "18.40", "31": "C24.83"}
    g = _bare()._greeks_from_quote(939846385, q, 295.0, 304.30, 35)
    assert g is not None
    assert g["conid"] == 939846385
    assert g["bid"] == 16.90 and g["ask"] == 18.40


def test_greeks_bad_last_degrades_not_fails():
    q = {"84": "10.0", "86": "11.0", "31": "HALT"}
    g = _bare()._greeks_from_quote(123, q, 100.0, 105.0, 35)
    assert g is not None
    assert g["mid"] == 10.5


def test_greeks_none_when_no_usable_price():
    q = {"84": "0", "86": "0", "31": "C0.00"}
    assert _bare()._greeks_from_quote(123, q, 100.0, 105.0, 35) is None
