# Spec 003 — Intraday Opening-Range Breakout (ORB) strategy

## Goal
Add a paper-only intraday equity strategy to ibkr-paper: 5-minute opening-range
breakout, long-only, flat before the close. No real orders, no IBKR order code.

## Strategy: `intraday_orb`

- **Universe (v1):** SPY, QQQ, AAPL, MSFT, NVDA, AMZN, META, TSLA — liquid, tight spreads.
- **Data:** 5-minute bars for the current session only, `outsideRth=false`,
  via existing `IBKRClient.history(conid, period="1d", bar="5min")`.
- **Opening range (OR):** high/low of the first 30 minutes (09:30–10:00 ET).
- **Entry window:** 10:00–11:30 ET. Enter LONG when a 5-min bar **closes** above
  the OR high. One entry per symbol per day (no re-entry after exit).
- **Skip filter:** if OR range < 0.15% of OR midpoint → too choppy, no trade.
- **Stop:** OR low. Position size = (0.5% of sleeve equity) / (entry − stop).
  Qty floored; no trade if qty < 1.
- **Target:** entry + 2 × (entry − stop). Take profit at 2R.
- **Time exit:** 15:45 ET — flatten everything. **Never hold overnight.**
- **Sleeve:** shares the `equity` sleeve in v1 (dedicated sleeve is future work).
- **Paper fills:** candidate-only in v1 (`Strategy.auto_fill=False` default; the runner
  records ORB signals as CANDIDATE and never paper-fills them). Explicit per-fill
  approval is required before any simulated fill — the standing don't-trade
  boundary overrides auto-fill for new strategies. Slippage modeling
  is explicitly out of scope for v1.

## Engine changes

1. `IBKRClient.history` already accepts `bar`/`period` — no change needed.
2. `Strategy` base: add class attrs `bar_size = "1d"`, `history_period = "1y"`.
   Runner uses them when fetching bars (backward compatible).
3. `StrategyContext`: add `positions` (symbol → {qty, avg_price}) and
   `today_entries` (set of symbols this strategy entered today), plus `now_et`
   (injectable clock for tests). Runner populates from the ledger.
4. `PaperLedger.fill`: resolve SELL with qty 0 → close whole position.
   If no position exists, the signal is a no-op and must NOT be recorded as
   PAPER_FILLED (this also fixes the JPM zero-qty noise from `us_momentum`).
5. Register `intraday_orb` in `STRATEGIES`.

## Schedule (proposed, NOT installed without explicit approval)

- Cron every 15 min, Mon–Fri, 10:00–15:45 America/Toronto, hitting a new
  `/signals/run?strategy=intraday_orb` (or a dedicated runner entry).
- Entry signals only fire 10:00–11:30; exits fire any run.

## Non-goals (v1)

- Short side, real orders, slippage model, dedicated intraday sleeve,
  real-time stop orders, pre-market data, news/earnings filters.

## Acceptance

- pytest suite green, including: OR computation, breakout entry, skip filter,
  0.5% risk sizing, 2R target, stop exit, 15:45 time exit, no-overnight,
  one-entry-per-day, qty-0 SELL resolution, intraday bar fetch params.
- One manual live paper scan completes without errors.
- No schedule installed until Ankit approves it.
