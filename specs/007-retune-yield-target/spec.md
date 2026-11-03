# Spec 007 — Retune options_income for the 1.5%/month target

Date: 2026-11-03. Set by Ankit: "We want to make at least 1.5% a month
profit", then approved with the tap "Retune for 1.5%/mo".

## The math

- Paper account NetLiq ~$1.01M → target ≈ **$15,150/month**.
- Options sleeve is 50% (~$505K), so deployed collateral must earn
  **~3%/month** for the account to make 1.5%/month.
- Pre-retune settings (~5% OTM, delta ≤ 0.30, 30–45 DTE) yield ~1.3%/month
  on deployed collateral (the live GOOGL trade: $425 on $27K over ~5 weeks).
  Even a permanently fully-deployed sleeve would reach only ~0.65%/month
  account-wide. The gap is structural, not a sizing bug.

## Changes (options_income only)

| Parameter | Before | After |
|---|---|---|
| otm_pct | 5.0 | 3.0 |
| max_delta | 0.30 | 0.40 |
| min_ann_yield_pct | — (none) | 30.0 |
| min_dte / max_dte | 30 / 45 | unchanged |
| max_sleeve_per_put_pct | 25.0 | unchanged |
| min_delta / min_iv_pct / min_theta / max_candidates | — | unchanged |

The yield floor uses the strategy's existing annualized yield,
(bid / strike) × (365 / DTE); 30% annualized ≈ 2.5% per 30 days on
collateral. Candidates below the floor are skipped (diagnostics gain a
per-symbol `yield_ok` flag).

## Non-goals / standing rules unchanged

- Signals only: the runner never places orders; every order still needs
  Ankit's per-order approval via the ticket flow.
- Paper account DUT160850 only.
- The 1.5%/month is a target, not a promise: closer-to-the-money puts mean
  assignment and losing months are expected; the paper account is where
  that gets measured honestly.
