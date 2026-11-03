# Plan — Spec 007

1. Tests first (`tests/test_retune_yield.py`): config values, delta 0.35 in
   band, yield floor rejects a low-yield Greek-passing put (and passes with
   the floor off), strike pick targets 3% OTM, sizing still capped at 25%
   of sleeve.
2. Strategy: read `min_ann_yield_pct` (default 0 = off, backward
   compatible); skip candidates below it after computing `ann_yield`;
   `yield_ok` in per-symbol diagnostics; docstring updated to ~3% OTM.
3. Config: `otm_pct 3.0`, `max_delta 0.40`, add `min_ann_yield_pct: 30.0`
   with the target math as a comment. config.yaml is bind-mounted into the
   container read-only and read per request, so no rebuild/restart.
4. Full pytest suite green, commit + push.
5. The daily-scan cron's strategy description is updated to the new
   parameters (same change Ankit approved).
