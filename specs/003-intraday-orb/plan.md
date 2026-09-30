# Plan 003 — Intraday ORB

## Approach
TDD: failing tests first, then minimal implementation. All work on the server
at `/mnt/store/apps/ibkr-paper` (app) via SSH; tests run inside the
`ibkr-paper` container.

## Changes by file

1. **`src/strategies/base.py`**
   - `Strategy`: add `bar_size: str = "1d"`, `history_period: str = "1y"`.
   - `StrategyContext`: add `positions: dict = {}` (symbol → {"qty","avg_price"}),
     `today_entries: set = set()`, `now_et: datetime | None = None`.

2. **`src/strategies/intraday_orb.py`** (new)
   - `name = "intraday_orb"`, `sleeve = "equity"`, `kind = "equity"`,
     `bar_size = "5min"`, `history_period = "1d"`.
   - Params (config `strategies.intraday_orb`): `or_minutes: 30`,
     `entry_start: "10:00"`, `entry_end: "11:30"`, `time_exit: "15:45"`,
     `min_range_pct: 0.15`, `risk_per_trade_pct: 0.5`, `target_r: 2.0`.
   - `generate(ctx)`: pure function of 5-min bars + ctx. Emits BUY (entry),
     SELL (stop / target / time exit, qty 0 = close-all).

3. **`src/strategies/__init__.py`** — register `intraday_orb`.

4. **`src/engine/runner.py`**
   - Equity branch: `client.history(conid(sym), period=strat.history_period, bar=strat.bar_size)`.
   - Populate `ctx.positions` (qty>0 from ledger), `ctx.today_entries`
     (symbols with a BUY fill by this strategy today), `ctx.now_et`
     (now in America/Toronto).
   - Support `?strategy=` filter on the run (used by the future cron).

5. **`src/engine/paper_ledger.py`**
   - `fill()`: SELL with qty 0 resolves to full position qty; no position →
     raise/return a "noop" the runner skips instead of marking PAPER_FILLED.

6. **`config.yaml`**
   - `universe.intraday: [SPY, QQQ, AAPL, MSFT, NVDA, AMZN, META, TSLA]`
   - `strategies.intraday_orb` params (defaults from spec).

7. **`src/api.py`** — `/signals/run` accepts optional `?strategy=` query param.

8. **`tests/test_intraday_orb.py`** (new) — all acceptance cases from spec.

## Bar timestamp handling
IBKR history bars carry `t` (ms epoch). Strategy converts to ET, selects bars
with 09:30 ≤ t < 10:00 for the OR. `outsideRth=false` keeps it RTH-only.

## Edge cases
- Half-days / holidays: < 6 OR bars → no trade (can't form a range).
- 429s: existing throttling in client; a failed symbol is skipped, not fatal.
- Stale session: runner already checks auth first.

## Verification
1. `docker exec ibkr-paper pytest` — full suite green.
2. Manual paper scan via `/signals/run?strategy=intraday_orb` — no errors
   (outside market hours it should emit zero signals, cleanly).
3. Git commit; push to github.com/ankitvirparia (repo pending creation).
