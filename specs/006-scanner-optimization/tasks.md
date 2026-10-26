# Tasks — Spec 006
- [x] Failing tests: tests/test_scanner_opt.py (retry, batch, true expiry,
      true DTE Greeks, funnel diagnostics, bid tie-break, sizing 10%)
- [x] ibkr_client: snapshot retry + option_contracts + option_greeks_for_contract
- [x] runner: 3 months, window pruning, per-strike expiry resolution,
      batched snapshot, funnel diagnostics
- [x] options_income: bid tie-break + self.diagnostics
- [x] config.yaml: max_sleeve_per_put_pct 25 -> 10
- [x] Full suite green; rebuild container; live /signals/run verification
- [x] Commit + push to github.com/ankitvirparia/ibkr-paper
