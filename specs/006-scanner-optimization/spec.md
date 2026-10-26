# Spec 006 — Scanner optimization: why the options_income scan returns 0

Date: 2026-10-26. Requested by Ankit: "Optimize the scanner. Why no trades?"

## Verified live facts (2026-10-26, gateway session live, same device MAC)

Oct 26 ~09:45 scan: 0 candidates. SPY stock quote live ($763.10) but SPY Nov
725P option snapshots empty. Two root causes, both reproduced live:

### Root cause 1 — cold snapshot subscriptions (deterministic 0)
The gateway lazily subscribes on first snapshot touch: the FIRST
`/iserver/marketdata/snapshot` call for a contract returns only the conid echo
(no 31/84/86 fields); the SECOND call returns full bid/ask/last. The runner
calls each option snapshot exactly once, so on a cold session (the daily scan
ran minutes after auto_login created the session) EVERY option quote is empty,
`option_greeks` returns None, and the strategy drops every candidate. Prior
"successes" (Sep 30 rerun, Oct 7 manual calls) worked only because
subscriptions were already warm from earlier touches.

### Root cause 2 — expiry-blind contract selection (wrong Greeks, wrong DTE)
`/iserver/secdef/info` for (month, strike, right) returns ALL expiries in the
month, each with a real `maturityDate` — but the code takes `data[0]`
(e.g. NOV 02 26 725P, 7 DTE from Oct 26) while computing DTE from month-end
(35) and reporting it as 35 DTE. Greeks are computed at the wrong horizon,
delta/theta are wrong, and the strategy DTE filter operates on fake DTE.

### Contributing defects
- 2-month chain window (current + next) can exclude the 30-45 DTE window
  late in a month; December expiries are never fetched in late October.
- All exceptions in the Greeks loop are swallowed: the scan reports 0 with
  zero explanation of where candidates died.
- Per-contract snapshot calls (100+ per ETF) instead of one batched call.
- Sizing mismatch: strategy `max_sleeve_per_put_pct` 25% vs allocator guard
  10% — proposed sizes would be refused at order time.

## Requirements
1. Snapshot warmth: `snapshot()` retries until the requested fields appear
   (up to 4 attempts, 1.5s apart) and only then gives up; a persistently
   empty quote is a diagnosed failure, never a silent skip.
2. Batched quotes: one snapshot call for all candidate option conids per
   symbol (the endpoint accepts comma-separated conids).
3. True expiry: resolve each candidate to the contract whose `maturityDate`
   gives a true DTE inside the strategy window (defaults 30-45 from strategy
   params); Greeks computed with true DTE; signal meta carries true expiry
   (YYYYMMDD) and true DTE.
4. Window: 3 months (current + next 2) so the DTE window is always covered;
   skip months that cannot overlap the window for secdef/info calls.
5. Diagnostics: the scan output carries a per-symbol funnel (chain rows,
   OTM band, DTE window, quoted, Greeks OK, affordable, picked) so the daily
   brief can say WHY 0 instead of guessing.
6. Sizing alignment: config `max_sleeve_per_put_pct` 25 -> 10, matching the
   allocator guard. No change to the documented Greek filters (config
   already holds min_delta 0.01, min_iv 8%, min_theta 0.005).
7. No order-path change: signals only; /orders untouched; paper account
   DUT160850 only; never a headless login (auto_login.sh stays the only
   automated login route).

## Corrections during implementation (2026-10-26)
- Sizing: aligning the CSP cap to the 10% allocator guard would make every
  SPY/QQQ put unaffordable (725 strike = $72,500 collateral vs $50,500 cap),
  so the standing 25% cap is KEPT. Open policy question for Ankit: should
  the allocator guard treat CSP collateral differently, or should the CSP
  cap come down to 10%? No unilateral risk change.
- Speed: the strategy only ever picks the affordable strike closest to the
  5% target, so the runner now resolves expiries only for the 7 band
  strikes closest to target (ETFs) / 1 strike (stocks) instead of the whole
  band. This cuts secdef calls ~85% and keeps picks identical under the
  25% cap (all band strikes are affordable there).
