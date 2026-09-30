"""SQLite paper-trade ledger: signals, fills, positions, cash, P&L.

Paper only. Fills are simulated at the signal's ref price (or a supplied price).
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ..strategies.base import Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL, strategy TEXT, symbol TEXT, side TEXT, kind TEXT,
  qty REAL, ref_price REAL, reason TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS fills(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL, signal_id INTEGER, symbol TEXT, side TEXT, qty REAL, price REAL);
CREATE TABLE IF NOT EXISTS positions(
  symbol TEXT PRIMARY KEY, qty REAL, avg_price REAL, kind TEXT, strategy TEXT);
CREATE TABLE IF NOT EXISTS cash(ts REAL, balance REAL);
"""


class NoPositionToClose(ValueError):
    """Raised when a close-all (qty 0) SELL arrives with no open position."""


class PaperLedger:
    def __init__(self, db_path: str | Path, starting_cash: float):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        if self.conn.execute("SELECT COUNT(*) c FROM cash").fetchone()["c"] == 0:
            self.conn.execute("INSERT INTO cash(ts, balance) VALUES (?, ?)",
                              (time.time(), starting_cash))
            self.conn.commit()
        self.starting_cash = starting_cash

    # -- signals ---------------------------------------------------------
    def record_signal(self, sig: Signal) -> int:
        cur = self.conn.execute(
            "INSERT INTO signals(ts,strategy,symbol,side,kind,qty,ref_price,reason,status)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (time.time(), sig.strategy, sig.symbol, sig.side, sig.kind,
             sig.qty, sig.ref_price, sig.reason, sig.status))
        self.conn.commit()
        return cur.lastrowid

    # -- fills -----------------------------------------------------------
    def fill(self, signal_id: int, price: float | None = None) -> dict:
        row = self.conn.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown signal {signal_id}")
        price = row["ref_price"] if price is None else price
        qty = row["qty"]
        side, symbol = row["side"], row["symbol"]
        now = time.time()

        pos = self.conn.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
        cur_qty = pos["qty"] if pos else 0.0
        cur_avg = pos["avg_price"] if pos else 0.0
        fill_qty = qty

        if side == "BUY":
            new_qty = cur_qty + qty
            new_avg = (cur_qty * cur_avg + qty * price) / new_qty if new_qty else 0.0
            self._set_cash(self.cash() - qty * price)
        elif side == "SELL":
            if qty == 0 and cur_qty <= 0:
                # Close-all signal with nothing open: pure noise (e.g. the old
                # us_momentum breakdown exits). Do not record a phantom fill.
                raise NoPositionToClose(f"no open position in {symbol} to close")
            close_qty = cur_qty if qty == 0 else min(qty, cur_qty)
            fill_qty = close_qty
            new_qty = cur_qty - close_qty
            new_avg = cur_avg if new_qty else 0.0
            self._set_cash(self.cash() + close_qty * price)
        elif side == "SELL_PUT":
            # paper short put: collect premium, cash-secured (collateral tracked in meta)
            new_qty = cur_qty - qty
            new_avg = cur_avg
            self._set_cash(self.cash() + qty * price * 100)
        else:
            raise ValueError(f"unsupported paper side {side}")

        if new_qty == 0:
            self.conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
        else:
            self.conn.execute(
                "INSERT INTO positions(symbol,qty,avg_price,kind,strategy) VALUES (?,?,?,?,?)"
                " ON CONFLICT(symbol) DO UPDATE SET qty=excluded.qty, avg_price=excluded.avg_price,"
                " kind=excluded.kind, strategy=excluded.strategy",
                (symbol, new_qty, new_avg, row["kind"], row["strategy"]))
        self.conn.execute(
            "INSERT INTO fills(ts,signal_id,symbol,side,qty,price) VALUES (?,?,?,?,?,?)",
            (now, signal_id, symbol, side, fill_qty, price))
        self.conn.execute("UPDATE signals SET status='PAPER_FILLED' WHERE id=?", (signal_id,))
        self.conn.commit()
        return {"symbol": symbol, "qty": new_qty, "avg_price": new_avg, "cash": self.cash()}

    # -- reads -----------------------------------------------------------
    def cash(self) -> float:
        return self.conn.execute("SELECT balance FROM cash ORDER BY ts DESC LIMIT 1").fetchone()["balance"]

    def _set_cash(self, balance: float):
        self.conn.execute("INSERT INTO cash(ts, balance) VALUES (?, ?)", (time.time(), balance))

    def positions(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM positions")]

    def signals(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,))]

    def pnl(self, last_prices: dict[str, float]) -> dict:
        unreal = 0.0
        market_value = 0.0
        for p in self.positions():
            last = last_prices.get(p["symbol"], p["avg_price"])
            unreal += p["qty"] * (last - p["avg_price"])
            if p["qty"] > 0:
                market_value += p["qty"] * last
        cash = self.cash()
        # total equity = cash + market value of long positions; cash already
        # reflects paper fills (buys/sells/premiums), unrealized adjusts marks.
        total_equity = cash + market_value
        return {
            "cash": round(cash, 2),
            "unrealized": round(unreal, 2),
            "total_equity": round(total_equity, 2),
            "pnl": round(total_equity - self.starting_cash, 2),
            "pnl_pct": round((total_equity - self.starting_cash) / self.starting_cash * 100, 3),
        }

    def reset(self, starting_cash: float):
        for t in ("signals", "fills", "positions", "cash"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.execute("INSERT INTO cash(ts, balance) VALUES (?, ?)", (time.time(), starting_cash))
        self.starting_cash = starting_cash
        self.conn.commit()
