# Spec 004 — Paper Order Routing

## Goal
Route orders to the IBKR **paper** account through the Client Portal Gateway,
so approved signals can become real paper-account positions. Read-only engine
today; this adds an explicit, human-gated execution path.

## Non-goals (v1)
- Live (non-paper) trading. The broker refuses any account except the configured
  paper account (`DUT160850`).
- Automatic routing. The runner never places orders. Every order needs Ankit's
  explicit confirmation, per order, through the preview → place → confirm flow.
- Bracket/OCO/complex orders. Single stock/option orders only.
- Fill reconciliation into the local $100K ledger (tracked as follow-up).

## Order flow
1. `POST /orders/preview` — {symbol | option{strike,expiry,right}, side, qty,
   order_type, limit_price, tif, signal_id?}. Resolves conid, calls IBKR
   `.../orders/whatif` for margin impact, returns a **ticket**
   {ticket_id, exact order JSON, whatif, expires_at = now+15min}.
2. Ankit reviews the ticket (chat shows symbol/side/qty/type/limit/est. cost).
3. `POST /orders/place` — {ticket_id, confirm: true}. Ticket must exist,
   be unexpired, unused, and params must match the ticket byte-for-byte.
   Broker POSTs `{"orders":[order]}` to `/iserver/account/{acct}/orders`.
4. IBKR replies with one of three 200-OK shapes:
   - `[{order_id, order_status}]` → placed. Record FILLED/SUBMITTED.
   - `[{id: replyId, message}]` → confirmation required. Return
     {needs_confirm: true, reply_id, warnings}; **do not auto-confirm**.
   - `{error}` → rejected. Record REJECTED with IBKR's message.
5. `POST /orders/confirm` — {ticket_id}. Completes the handshake:
   `POST /iserver/reply/{replyId}` {"confirmed": true}, looping on cascading
   replies. Reply must be immediate (any other request cancels it), so the
   confirm call does place → reply in one server-side sequence.

## Safety rules
- **Paper-account guard**: `PaperBroker` is constructed with the configured
  `paper.account_id`; every method asserts the target account equals it.
  Mismatch → hard refusal, no request sent.
- **No runner integration**: `run_cycle` never imports or calls the broker.
  (Covered by a test.)
- **Tickets**: single-use, 15-min TTL, tamper-evident (order JSON pinned).
- **cOID**: unique per order (`orb-<uuid>`), ≤64 chars, idempotency for 24h.
- **Cancel**: `DELETE /orders/{ibkr_order_id}` → IBKR cancel; never default -1.
- Market closed behavior: paper orders rest until open; preview-only testing
  after hours (no placement without Ankit's per-order approval).

## Data
- `broker_orders`: ticket_id, signal_id?, symbol, side, qty, order_type,
  limit_price, tif, conid, status (PREVIEWED→PLACED→CONFIRMED/FILLED |
  REJECTED | CANCELLED), ibkr_order_id, reply_id, timestamps.
- `order_tickets`: ticket_id, order_json, signal_id?, status, created/expires.

## Config
```yaml
paper:
  account_id: "DUT160850"   # hard guard: broker refuses anything else
  order_ticket_ttl_sec: 900
```

## Verification
- New `tests/test_paper_routing.py`: fake gateway transport; covers the three
  IBKR response shapes, ticket tamper/expiry/reuse, account guard, and
  runner isolation.
- Full suite green in container.
- Live: `POST /orders/preview` against the paper gateway (read-only whatif) —
  no placement after hours without explicit approval.
