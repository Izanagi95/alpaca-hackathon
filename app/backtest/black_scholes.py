"""Black-Scholes put and call pricing/delta, used only by the simulated
backtest to reconstruct a THEORETICAL option price from real historical
stock prices. This is a modeling approximation, not an observed historical
market price — see app/backtest/simulated_backtest.py for why, and never
treat its output as a validated historical option quote.
"""

from __future__ import annotations

import math


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def put_price(spot: float, strike: float, time_to_expiry_years: float, volatility: float, risk_free_rate: float = 0.04) -> float:
    if time_to_expiry_years <= 0:
        return max(strike - spot, 0.0)
    if volatility <= 0 or spot <= 0 or strike <= 0:
        return max(strike - spot, 0.0)
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry_years) / (
        volatility * math.sqrt(time_to_expiry_years)
    )
    d2 = d1 - volatility * math.sqrt(time_to_expiry_years)
    return strike * math.exp(-risk_free_rate * time_to_expiry_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def put_delta(spot: float, strike: float, time_to_expiry_years: float, volatility: float, risk_free_rate: float = 0.04) -> float:
    if time_to_expiry_years <= 0 or volatility <= 0 or spot <= 0 or strike <= 0:
        return -1.0 if spot < strike else 0.0
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry_years) / (
        volatility * math.sqrt(time_to_expiry_years)
    )
    return _norm_cdf(d1) - 1.0


def call_price(spot: float, strike: float, time_to_expiry_years: float, volatility: float, risk_free_rate: float = 0.04) -> float:
    """Derived from the put via put-call parity (C = P + S - K*e^-rT), so the
    two prices can never drift apart and a bear call spread priced here is
    consistent with the bull put spread priced beside it."""
    if time_to_expiry_years <= 0 or volatility <= 0 or spot <= 0 or strike <= 0:
        return max(spot - strike, 0.0)
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry_years)
    return put_price(spot, strike, time_to_expiry_years, volatility, risk_free_rate) + spot - discounted_strike


def call_delta(spot: float, strike: float, time_to_expiry_years: float, volatility: float, risk_free_rate: float = 0.04) -> float:
    if time_to_expiry_years <= 0 or volatility <= 0 or spot <= 0 or strike <= 0:
        return 1.0 if spot > strike else 0.0
    return put_delta(spot, strike, time_to_expiry_years, volatility, risk_free_rate) + 1.0
