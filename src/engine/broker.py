"""Paper-account order routing through the IBKR Client Portal Gateway.

Spec: specs/004-paper-order-routing/spec.md

Safety model:
- PaperBroker is bound to ONE account id (the configured paper account).
  Every mutating method asserts the target account matches; anything else
  raises BrokerGuardError WITHOUT touching the network.
- place() never auto-confirms IBKR's precautionary reply messages.
  confirm() is a separate, explicit step.
- The runner (engine/runner.py) never imports this module: no auto-routing
  path can exist.
"""
from __future__ import annotations

import uuid

from ..ibkr_client import IBKRClient

MAX_CONFIRM_ROUNDS = 5


class BrokerGuardError(RuntimeError):
    """A safety guard refused the operation (wrong account, bad ticket)."""


class BrokerRejected(RuntimeError):
    """IBKR refused the order; carries IBKR's message."""


class PaperBroker:
    """Order placement bound to a single paper account."""

    def __init__(self, client: IBKRClient, paper_account_id: str):
        if not paper_account_id:
            raise BrokerGuardError(
                "refusing to construct broker without a paper account id")
        self.client = client
        self.paper_account_id = paper_account_id

    def _guard(self, account_id: str) -> str:
        if account_id != self.paper_account_id:
            raise BrokerGuardError(
                f"refusing order for non-paper account {account_id!r} "
                f"(paper account is {self.paper_account_id!r})")
        return account_id

    # -- order construction ------------------------------------------------
    @staticmethod
    def build_order(conid: int, side: str, qty: float,
                    order_type: str = "MKT",
                    limit_price: float | None = None,
                    tif: str = "DAY") -> dict:
        """Build the IBKR order JSON. cOID is unique per call (24h idempotency)."""
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {side!r}")
        order_type = order_type.upper()
        if order_type == "LMT" and limit_price is None:
            raise ValueError("LMT orders need limit_price")
        order = {
            "conid": int(conid),
            "side": side,
            "orderType": order_type,
            "quantity": qty,
            "tif": tif.upper(),
            "cOID": f"amuse-{uuid.uuid4().hex[:16]}",
        }
        if order_type == "LMT":
            order["price"] = float(limit_price)
        return order

    # -- gateway calls ------------------------------------------------------
    def whatif(self, account_id: str, order: dict) -> dict:
        """Margin/commission preview. Read-only; places nothing."""
        acct = self._guard(account_id)
        r = self.client._post(f"/iserver/account/{acct}/orders/whatif",
                              {"orders": [order]})
        return self.client._json(r, "order whatif")

    def place(self, account_id: str, order: dict) -> dict:
        """POST the order. Returns {"order_id", "status"} or
        {"needs_confirm": True, "reply_id", "messages"}. Never auto-confirms."""
        acct = self._guard(account_id)
        r = self.client._post(f"/iserver/account/{acct}/orders",
                              {"orders": [order]})
        return self._interpret_place_response(self.client._json(r, "place order"))

    @staticmethod
    def _interpret_place_response(data) -> dict:
        # IBKR answers HTTP 200 for all three shapes — branch on shape.
        if isinstance(data, dict):
            # {"error": "..."} — IBKR refused the order outright.
            raise BrokerRejected(data.get("error") or f"order rejected: {data!r}"[:200])
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise BrokerRejected(f"unexpected order response: {data!r}"[:200])
        first = data[0]
        if "order_id" in first:
            return {"order_id": str(first["order_id"]),
                    "status": first.get("order_status", "Submitted")}
        if "id" in first:
            # Precautionary reply message — needs an explicit confirm step.
            return {"needs_confirm": True,
                    "reply_id": first["id"],
                    "messages": list(first.get("message") or [])}
        raise BrokerRejected(f"unexpected order response: {data!r}"[:200])

    def confirm(self, reply_id: str) -> dict:
        """Confirm IBKR's precautionary reply. Loops on cascading replies.

        Must run promptly after place(): any other gateway request in between
        invalidates the reply (IBKR answers 503 then)."""
        last = reply_id
        for _ in range(MAX_CONFIRM_ROUNDS):
            r = self.client._post(f"/iserver/reply/{last}", {"confirmed": True})
            data = self.client._json(r, "order reply")
            if isinstance(data, dict):
                raise BrokerRejected(data.get("error") or f"reply rejected: {data!r}"[:200])
            if isinstance(data, list) and data and isinstance(data[0], dict):
                first = data[0]
                if "order_id" in first:
                    return {"order_id": str(first["order_id"]),
                            "status": first.get("order_status", "Submitted")}
                if "id" in first:
                    last = first["id"]  # cascade: one more confirmation
                    continue
            raise BrokerRejected(f"unexpected reply response: {data!r}"[:200])
        raise BrokerRejected("too many cascading order confirmations")

    def open_orders(self) -> list:
        r = self.client._get("/iserver/account/orders")
        data = self.client._json(r, "open orders")
        return data if isinstance(data, list) else []

    def order_status(self, order_id: str) -> dict:
        r = self.client._get(f"/iserver/account/order/status/{order_id}")
        return self.client._json(r, "order status")

    def cancel(self, account_id: str, order_id: str | int) -> dict:
        acct = self._guard(account_id)
        if str(order_id) == "-1":
            # IBKR treats -1 as cancel-ALL; never allow it to be defaulted to.
            raise BrokerGuardError("refusing cancel-all (order_id -1)")
        r = self.client._delete(f"/iserver/account/{acct}/order/{order_id}")
        return self.client._json(r, "cancel order")
