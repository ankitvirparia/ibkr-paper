# Tasks 003 — Intraday ORB

- [x] 1. Ship spec/plan/tasks to `/mnt/store/apps/ibkr-paper/specs/003-intraday-orb/`
- [x] 2. Tests: OR high/low from 5-min bars (incl. half-day → no trade)
- [x] 3. Tests: breakout entry (bar close above OR high, inside 10:00–11:30)
- [x] 4. Tests: no entry before 10:00 / after 11:30; skip when OR range < 0.15%
- [x] 5. Tests: position sizing = 0.5% sleeve / (entry − stop); qty<1 → no trade
- [x] 6. Tests: exits — stop hit, 2R target hit, 15:45 time exit (qty 0 SELL)
- [x] 7. Tests: one entry per symbol per day; never hold overnight
- [x] 8. Tests: ledger.fill resolves qty-0 SELL to full position; no-op when flat
- [x] 9. Tests: runner passes bar_size/history_period/positions/today_entries/now_et
- [x] 10. Implement `src/strategies/intraday_orb.py` + register
- [x] 11. Implement base/ctx/runner/ledger/api changes + config
- [x] 12. Full pytest green in container
- [x] 13. Manual live `/signals/run?strategy=intraday_orb` — clean, no errors
- [ ] 14. Commit incrementally; push to GitHub (create repo if needed)
- [ ] 15. Propose cron schedule text — DO NOT install without Ankit's approval
