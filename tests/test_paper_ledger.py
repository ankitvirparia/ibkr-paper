"""Paper ledger unit tests (SQLite, tmp dir)."""
import pytest

from src.engine.paper_ledger import PaperLedger
from src.strategies.base import Signal


@pytest.fixture
def ledger(tmp_path):
    return PaperLedger(tmp_path / "paper.db", starting_cash=100_000)


def _sig(**kw):
    d = dict(strategy="us_momentum", symbol="AAA", side="BUY", kind="equity",
             qty=10, ref_price=100.0, reason="test")
    d.update(kw)
    return Signal(**d)


def test_buy_fill_creates_position(ledger):
    sid = ledger.record_signal(_sig())
    r = ledger.fill(sid)
    assert r["qty"] == 10 and r["avg_price"] == 100.0
    assert r["cash"] == 100_000 - 1_000
    pos = ledger.positions()
    assert len(pos) == 1 and pos[0]["symbol"] == "AAA"


def test_sell_closes_position(ledger):
    sid = ledger.record_signal(_sig())
    ledger.fill(sid)
    sid2 = ledger.record_signal(_sig(side="SELL", qty=0, ref_price=110.0))
    r = ledger.fill(sid2)
    assert r["qty"] == 0
    assert r["cash"] == 100_000 - 1_000 + 1_100
    assert ledger.positions() == []


def test_pnl_math(ledger):
    sid = ledger.record_signal(_sig())
    ledger.fill(sid)  # buy 10 @ 100
    pnl = ledger.pnl({"AAA": 110.0})
    assert pnl["unrealized"] == 100.0
    assert pnl["total_equity"] == 100_100.0
    assert pnl["pnl"] == 100.0


def test_sell_put_collects_premium(ledger):
    sid = ledger.record_signal(_sig(side="SELL_PUT", kind="option", symbol="SPY",
                                    qty=2, ref_price=1.5))
    r = ledger.fill(sid)
    assert r["cash"] == 100_000 + 2 * 1.5 * 100
