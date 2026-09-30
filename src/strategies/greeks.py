"""Black-Scholes Greeks for the options_income strategy.

IBKR's Client Portal API only returns model Greeks with realtime market data
subscriptions (option + underlying). Paper accounts typically get delayed data,
so we compute Greeks ourselves from the option's market price.
"""
from __future__ import annotations

import math

SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def bs_put_price(s: float, k: float, t: float, r: float, sigma: float) -> float:
    """Black-Scholes put price. t in years."""
    if t <= 0 or sigma <= 0 or s <= 0 or k <= 0:
        return max(k - s, 0.0)
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    return k * math.exp(-r * t) * _norm_cdf(-d2) - s * _norm_cdf(-d1)


def implied_vol_put(price: float, s: float, k: float, t: float,
                    r: float = 0.045, tol: float = 1e-5) -> float | None:
    """Implied volatility from a put's market price via bisection. Returns None if unsolvable."""
    if price <= 0 or t <= 0 or s <= 0 or k <= 0:
        return None
    intrinsic = max(k - s, 0.0)
    if price < intrinsic * 0.99:  # price below intrinsic -> bad data
        return None
    lo, hi = 0.01, 5.0
    # ensure bracket
    if bs_put_price(s, k, t, r, hi) < price:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2.0
        p = bs_put_price(s, k, t, r, mid)
        if abs(p - price) < tol:
            return mid
        if p < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def put_delta(s: float, k: float, t: float, r: float, sigma: float) -> float:
    """Put delta (negative)."""
    if t <= 0 or sigma <= 0:
        return -1.0 if s < k else 0.0
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    return _norm_cdf(d1) - 1.0


def put_theta(s: float, k: float, t: float, r: float, sigma: float) -> float:
    """Put theta in $/day (negative = decays)."""
    if t <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    term1 = -(s * _norm_pdf(d1) * sigma) / (2.0 * math.sqrt(t))
    term2 = r * k * math.exp(-r * t) * _norm_cdf(-d2)
    return (term1 + term2) / 365.0


def put_gamma(s: float, k: float, t: float, r: float, sigma: float) -> float:
    if t <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    return _norm_pdf(d1) / (s * sigma * math.sqrt(t))


def put_vega(s: float, k: float, t: float, r: float, sigma: float) -> float:
    """Vega per 1% vol change."""
    if t <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    return s * _norm_pdf(d1) * math.sqrt(t) / 100.0
