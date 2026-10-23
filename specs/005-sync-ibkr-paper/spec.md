# Spec 005 — Sync with IBKR Paper (retire the local simulation)

Date: 2026-10-22. Requested by Ankit: "Sync the simulation with paper trading.
No local simulation needed."

## Goal
The app's account state IS the real IBKR paper account **DUT160850**, read live
from the Client Portal Gateway. The local simulated ledger (SQLite paper.db,
$100,006 fake balance, simulated fills) is retired completely: no local source
of truth, no simulated positions, no simulated fills.

## Current live facts (verified 2026-10-22 20:00 EDT)
- Gateway session authenticated via Ankit's login in the VNC-desktop browser.
- Accounts visible: DUT160850 only, isPaper=true.
- Positions: [] (empty). Cash: CAD 1,000,357.20 + USD 6,290.50.
  NetLiq ~CAD 1,010,051. Buying power ~CAD 3,366,838.

## Requirements
1. **Live account state.** Every account/positions/cash figure the app serves
   comes from the gateway at request time:
   - GET /v1/api/portfolio/DUT160850/positions/0
   - GET /v1/api/portfolio/DUT160850/summary
   - GET /v1/api/portfolio/DUT160850/ledger
   If the gateway session is not authenticated, the app reports a clear
   "session not live" state. It must NEVER fall back to local/stale numbers.
2. **Local ledger retired.** `src/engine/paper_ledger.py` leaves the runtime
   path: no module in src/ reads or writes paper.db for account state,
   positions, balances, or fills. The app must boot and serve with the DB
   file absent. (Ops archives the file separately; code must not need it.)
3. **No simulated fills.** Any path that books a local/simulated fill is
   removed, including the effect of `us_momentum`'s legacy `auto_fill=True`.
   Strategies emit SIGNALS only. Execution exists solely through the
   spec-004 human-gated ticket flow (preview -> ticket -> place -> confirm)
   against IBKR paper. Per-order approval by Ankit is unchanged.
4. **Live sizing.** The allocator takes the live account summary as input:
   options sleeve = 50% of NetLiq, equity sleeve = 50%, max position 10% of
   its sleeve, max 12 open positions, 2% daily-loss kill switch. Percentages
   are Ankit's existing design, unchanged; at today's balance each sleeve is
   ~CAD 505K, which scans must display explicitly.
5. **Session init + account guard.** On first gateway use after app start,
   call GET /iserver/accounts once (IBKR requires it per brokerage session),
   cache that it was done, and assert the only account is DUT160850. Any
   other account present = hard refusal before any further calls.
6. **Gateway addressing.** Gateway base URL stays https://localhost:5000/v1/api
   (Ankit's rule: localhost, never 127.0.0.1).

## Non-goals
- No changes to the spec-004 order ticket flow or its tests' expectations.
- No real-money account support. No scheduling/autonomous runs.
- No keep-alive work (separate follow-up).

## Acceptance
- Full pytest suite green, including rewritten ledger tests.
- Live check: app account endpoint returns positions [] and cash/NetLiq
  matching the gateway's own summary within rounding.
- grep: no runtime import of paper_ledger under src/ (tests may reference the
  archived module only to assert its absence).
