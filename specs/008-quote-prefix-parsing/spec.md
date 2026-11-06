# Spec 008 — Tolerate IBKR's 'C'-prefixed last price in quote parsing

Date: 2026-11-06. Found live while preparing Ankit's AVGO order.

## Symptom

`POST /orders/preview` for AVGO 295P Dec 11 2026 returned
`503 cannot resolve option contract for AVGO` — twice — while a manual
secdef lookup found the contract (conid 939846385) and its snapshot
carried a perfectly good bid/ask (16.90 / 18.40).

## Root cause

IBKR marks a stale last price as a *closing* price by prefixing it:
field 31 arrived as `"C24.83"`. The quote parsers did
`float(str(value))` inside a try that returned None (client Greeks) or
zeroed the whole row (runner chain building) on ValueError. So one
decorative prefix on the *last* field destroyed an otherwise valid
quote:

- `_greeks_from_quote` → None → `option_greeks` → None →
  `_resolve_conid` raises → no order ticket can be built.
- The runner's chain loop zeroed bid/ask too, so the same contracts
  were silently dropped from scans as "unquoted".

Contracts that had traded the same day (numeric last) were unaffected,
which is why GOOGL (Oct 29) and AMD (same morning) previews worked.

## Fix

One shared tolerant parser, `_num()` in `src/ibkr_client.py`: strips
commas and a leading `C`, degrades unparseable fields to 0.0
per-field (a bad `last` no longer kills good bid/ask). Used by both
`_greeks_from_quote` and the runner's chain loop.
