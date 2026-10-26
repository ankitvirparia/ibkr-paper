# Plan — Spec 006

## Changes
- `src/ibkr_client.py`
  - `snapshot()`: retry loop (4 attempts, 1.5s apart) until every requested
    field is present in at least one row; 401 still raises immediately.
  - `option_contracts(underlying_conid, month, strike, right)`: full
    secdef/info list (conid + maturityDate), replacing blind `data[0]`.
  - `option_greeks_for_contract(conid, maturity_date, strike, price)`:
    retry snapshot + Black-Scholes Greeks with TRUE DTE from maturityDate.
  - `option_greeks(...)` kept as a compatibility wrapper: exact maturityDate
    (YYYYMMDD) selects the matching contract; legacy YYYYMM keeps old
    behavior for old callers (api._resolve_conid now passes true expiry).
- `src/engine/runner.py`
  - 3 expiry months; skip months that cannot overlap the DTE window.
  - Per symbol: unique OTM-band strikes -> secdef/info per (strike, month)
    -> keep contracts whose true DTE is in [min_dte, max_dte] (from the
    strategy params, defaults 30/45) -> ONE batched snapshot for all kept
    conids -> Greeks per contract with true DTE.
  - Chain entries carry bid/ask/iv_pct/delta/theta/dte/expiry=maturityDate.
  - Funnel diagnostics per symbol + strategy diagnostics from generate().
  - Stocks keep the single-closest-strike rule, now with true-expiry
    resolution (all in-window expiries for that strike enriched).
- `src/strategies/options_income.py`
  - Tie-break the pick by higher bid when two contracts share a strike.
  - Record `self.diagnostics` (puts seen, Greeks OK, affordable) for the
    runner funnel.
- `config.yaml`: `max_sleeve_per_put_pct: 25.0 -> 10.0`.

## Tests (failing first)
- `tests/test_scanner_opt.py`: snapshot retry (empty then fields); batched
  snapshot single call; true-expiry selection (multi-maturity list, DTE
  window); Greeks use true DTE not month-end; funnel diagnostics present;
  strategy tie-break by bid; config sizing alignment (10%).

## Verification
- Full pytest suite green; container rebuilt from Dockerfile/compose
  (no in-place patching); live `POST /signals/run?strategy=options_income`
  returns diagnostics (after-close quotes are delayed but present, proving
  the retry/batch path). Full live-candidate verification happens on the
  next market-open scan (2026-10-27 09:45 brief carries the funnel).
