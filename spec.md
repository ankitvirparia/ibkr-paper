# ibkr-paper — spec

## Goal
Paper-trading signal + execution-simulation service for Ankit's IBKR account,
running on ankit-nucboxg9. Talks to the local IBKR Client Portal Gateway
(`ibkr-gateway` container) for market data. **Never places real orders.**

## Allocation (Ankit's call, 2026-09-30)
- 50% of portfolio → options strategies (income-style, e.g. cash-secured puts)
- 50% of portfolio → US equity strategies (e.g. momentum/breakout)

## Flexibility requirement
Deploying a new strategy = new file in `src/strategies/` + one line in the
registry (`src/strategies/__init__.py`) + optional config in `config.yaml`.
No changes to engine, ledger, API, or Docker needed.

## Components
1. `ibkr_client.py` — read-only CPGW client: auth status, accounts, positions,
   contract search, snapshots, historical bars, option strikes. No order endpoints.
2. `strategies/` — `Strategy` ABC + `Signal` dataclass; registry dict.
   - `us_momentum` (equity sleeve): 20-day breakout + 50-day MA trend filter,
     ATR-based position sizing, 1% risk per trade.
   - `options_income` (options sleeve): cash-secured-put candidates on index ETFs,
     ~5% OTM, 30–45 DTE, real chain strikes from IBKR. Candidates only in MVP
     (option fill pricing wired later); never auto-executes.
3. `engine/allocator.py` — sleeve splits, max position %, max positions,
   daily-loss kill switch.
4. `engine/paper_ledger.py` — SQLite: signals, paper fills, positions, cash, P&L.
5. `engine/runner.py` — one cycle: fetch data → strategies → allocate → paper fills.
6. `api.py` — FastAPI: health, IBKR read-only passthrough, strategy list,
   run trigger, paper signals/positions/P&L.

## Safety
- `ENABLE_ORDER_PLACEMENT` does not exist; order code is not in the repo.
- Paper ledger is the only "execution".
- Kill switch halts new signals per sleeve on daily loss breach.
