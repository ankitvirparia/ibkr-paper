# Plan 004 — Paper Order Routing

## Architecture
```
src/engine/broker.py      PaperBroker: account guard, order JSON builder,
                          place / confirm / open_orders / cancel / status.
                          Pure gateway wrapper; no strategy/ledger imports.
src/api.py                /orders/preview|place|confirm, GET /orders,
                          DELETE /orders/{id}. Ticket issuance + validation.
src/engine/paper_ledger.py  broker_orders + order_tickets tables
                          (CREATE TABLE IF NOT EXISTS in _init).
config.yaml               paper.account_id, paper.order_ticket_ttl_sec.
```

## IBKR Client Portal API (verified against community docs, 2026-09-30)
- `POST /iserver/account/{accountId}/orders` body `{"orders":[{...}]}`.
  Order fields: `conid` (int), `side` BUY|SELL, `orderType` MKT|LMT,
  `quantity`, `price` (LMT), `tif` DAY|GTC, `cOID` (unique ≤64 chars).
- Response shapes (all HTTP 200 — branch on shape):
  1. `[{"order_id","order_status"}]` → placed.
  2. `[{"id":"<replyId>","message":[...]}]` → `POST /iserver/reply/{replyId}`
     `{"confirmed":true}`; loop (cascading replies); reply immediately.
  3. `{"error":"..."}` → rejected with reason.
- `POST /iserver/account/{accountId}/orders/whatif` → margin preview.
- `GET /iserver/account/orders` (≤1 req/5s) → open orders.
- `GET /iserver/account/order/status/{orderId}` → single status.
- `DELETE /iserver/account/{accountId}/order/{orderId}` → cancel.
- Prereq: `GET /iserver/accounts` once per brokerage session before trading.

## Contract resolution
- Stocks: existing `client.stock_conid(symbol)`.
- Options: reuse `client.option_greeks(underlying_conid, expiry_month, strike,
  right, price)` — its response includes the option `conid`. v1 only.

## Ticket security
- `ticket_id` = secrets.token_urlsafe(24); stored with the exact order JSON.
- `/orders/place` re-serializes the request params and compares against the
  stored JSON; any divergence → 400, no gateway call.
- TTL 900s; single-use (status USED after place, regardless of outcome).

## Test plan (tests/test_paper_routing.py)
FakeIBKRClient(IBKRClient) overriding `_post`/`_get` with a scripted queue.
1. `build_order` produces the documented JSON shape (MKT buy stock).
2. place → success shape → returns order_id; ticket marked USED.
3. place → confirm-required shape → returns needs_confirm + reply_id;
   asserts no `/iserver/reply` call was made (no auto-confirm).
4. confirm → loops two cascading replies → final order_id.
5. place → `{"error": ...}` → raises BrokerRejected carrying IBKR's message.
6. PaperBroker(account_id="U123") → refuses to construct / call.
7. place with tampered qty vs ticket → 400 before any gateway call.
8. place with expired ticket → 400; reused ticket → 400.
9. Runner isolation: run_cycle with instrumented client records zero POSTs
   to `/orders` (proves no auto-routing path exists).
10. whatif preview returns margin impact block in the ticket.

## Rollout
1. Spec/plan/tasks → server.
2. Failing tests → implement → green (34 existing + ~10 new).
3. Live preview-only: `POST /orders/preview` {SPY, BUY, 1, MKT} against paper
   gateway; verify ticket + whatif; **no placement** (market closed anyway).
4. Commit incrementally; push needs the GitHub repo (Ankit to create).
