# Plan 005 — Sync with IBKR Paper

## Approach
Replace the ledger-backed state with a thin live-state layer over the existing
`src/ibkr_client.py`, rewire the API + runner to it, and delete the simulated
fill machinery. Keep spec-004 broker/ticket code untouched.

## Components
1. **NEW `src/engine/ibkr_state.py`**
   - `ensure_session()`: GET /iserver/auth/status; if not authenticated raise
     `SessionNotLive`. Once per process: GET /iserver/accounts, assert
     accounts == ["DUT160850"] else raise `AccountGuardError`. Cache the init.
   - `get_account_state()` -> dict: positions (gateway list), cash_by_currency
     (from ledger), net_liquidation, buying_power, available_funds,
     gross_position_value (from summary), plus `source: "ibkr-paper-live"`
     and a fetched-at timestamp.
   - All gateway calls go through `ibkr_client` (base https://localhost:5000/v1/api).
2. **`src/api.py`**: account/positions/balance endpoints call
   `ibkr_state.get_account_state()`. SessionNotLive -> HTTP 503 with
   `{"status": "session_not_live"}` body, never stale data. Remove PaperLedger
   construction and every ledger-backed endpoint. Order endpoints (spec 004)
   unchanged.
3. **`src/engine/runner.py`**: remove any PaperLedger/fill path. Runner flow:
   fetch live state -> allocator sizes from live NetLiq -> strategies emit
   signals -> nothing executes without the spec-004 ticket flow.
4. **`src/engine/allocator.py`**: accept an explicit `account_state` argument
   (NetLiq + existing IBKR position count) instead of reading a ledger.
   Defaults preserve the 50/50 sleeves, 10% max position, 12 positions,
   2% daily-loss kill switch.
5. **`src/strategies/us_momentum.py`**: remove `auto_fill` behavior; the
   strategy returns signals only (keep the flag name if referenced elsewhere,
   but it must have no effect; prefer deleting it and fixing references).
6. **`src/engine/paper_ledger.py`**: delete the module. `config.yaml`: drop
   `db_path`. `tests/test_paper_ledger.py`: replace with
   `tests/test_ibkr_state.py` (below).
7. **Deploy**: rebuild the ibkr-paper image from the repo Dockerfile and
   recreate the container (no in-place patching). Ops archives
   /mnt/store/data-app/ibkr-paper/paper.db to paper.db.archived-2026-10-22
   BEFORE the new container starts; the new app must not recreate it.

## Tests (write first, TDD)
- `tests/test_ibkr_state.py` with a mocked ibkr_client:
  - state maps gateway summary/ledger/positions into the response shape,
    including CAD + USD cash lines.
  - unauthenticated auth/status -> SessionNotLive; API returns 503 shape.
  - accounts != ["DUT160850"] -> AccountGuardError, and no positions call made.
  - /iserver/accounts called exactly once across repeated state fetches.
- Allocator tests updated: sizing derives from a supplied live NetLiq
  (e.g. NetLiq 1,010,051 -> sleeve 505,025.5, max position 50,502.55).
- Regression: `tests/test_paper_routing.py` (54 tests) and all other suites
  stay green; add a test asserting no module under src/ imports paper_ledger.
- Boot test: app imports and serves /health with no DB file present.

## Risks
- Gateway session drops mid-work: state calls surface SessionNotLive; scans
  stop loudly rather than sizing off stale numbers. Acceptable by design.
- Summary field names vary: map defensively (amount/currency sub-objects) and
  unit-test with a captured-shape fixture.
