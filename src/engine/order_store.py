"""SQLite persistence for human-approved order tickets and broker records."""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from pathlib import Path

from .broker import BrokerGuardError


class OrderStore:
    """Store order tickets only; account state and fills are never simulated."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS order_tickets(
          ticket_id TEXT PRIMARY KEY, order_json TEXT, signal_id INTEGER,
          status TEXT, created_ts REAL, expires_ts REAL);
        CREATE TABLE IF NOT EXISTS broker_orders(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ticket_id TEXT, signal_id INTEGER, symbol TEXT, side TEXT, qty REAL,
          order_type TEXT, limit_price REAL, tif TEXT, conid INTEGER,
          status TEXT, ibkr_order_id TEXT, reply_id TEXT,
          created_ts REAL, updated_ts REAL);
        """)

    @staticmethod
    def _canon(order: dict) -> str:
        return json.dumps(order, sort_keys=True)

    def issue_ticket(self, order: dict, signal_id: int | None = None,
                     ttl_sec: int = 900) -> str:
        ticket_id = secrets.token_urlsafe(24)
        now = time.time()
        self.conn.execute(
            "INSERT INTO order_tickets(ticket_id, order_json, signal_id, status,"
            " created_ts, expires_ts) VALUES (?,?,?,?,?,?)",
            (ticket_id, self._canon(order), signal_id, "OPEN", now, now + ttl_sec))
        self.conn.commit()
        return ticket_id

    def get_ticket(self, ticket_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM order_tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
        return dict(row) if row else None

    def redeem_ticket(self, ticket_id: str, order: dict) -> dict:
        row = self.get_ticket(ticket_id)
        if row is None:
            raise BrokerGuardError("unknown ticket")
        if row["status"] != "OPEN":
            raise BrokerGuardError("ticket already used")
        if row["expires_ts"] < time.time():
            raise BrokerGuardError("ticket expired")
        if row["order_json"] != self._canon(order):
            raise BrokerGuardError("order does not match ticket")
        self.conn.execute("UPDATE order_tickets SET status='USED' WHERE ticket_id=?",
                          (ticket_id,))
        self.conn.commit()
        row["status"] = "USED"
        return row

    def record_broker_order(self, ticket_id: str, order: dict, symbol: str,
                            signal_id: int | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO broker_orders(ticket_id, signal_id, symbol, side, qty,"
            " order_type, limit_price, tif, conid, status, created_ts, updated_ts)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ticket_id, signal_id, symbol, order["side"], order["quantity"],
             order["orderType"], order.get("price"), order["tif"], order["conid"],
             "PREVIEWED", time.time(), time.time()))
        self.conn.commit()
        return cur.lastrowid

    def update_broker_order(self, order_id: int, **fields) -> None:
        allowed = {"status", "ibkr_order_id", "reply_id"}
        sets = ", ".join(f"{key}=?" for key in fields if key in allowed)
        if not sets:
            return
        values = [fields[key] for key in fields if key in allowed]
        self.conn.execute(
            f"UPDATE broker_orders SET {sets}, updated_ts=? WHERE id=?",
            (*values, time.time(), order_id))
        self.conn.commit()

    def broker_order_by_ticket(self, ticket_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM broker_orders WHERE ticket_id=? ORDER BY id DESC LIMIT 1",
            (ticket_id,)).fetchone()
        return dict(row) if row else None

    def broker_orders(self, limit: int = 50) -> list[dict]:
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM broker_orders ORDER BY id DESC LIMIT ?", (limit,))]
