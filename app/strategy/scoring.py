from __future__ import annotations

from app.config.settings import Settings
from app.strategy.bull_put_spread import BullPutSpreadCandidate


def score_candidate(candidate: BullPutSpreadCandidate, settings: Settings | None = None) -> int:
    """Score only observable inputs; no forecast or invented probability metric."""
    settings = settings or Settings()
    regime = 100 if candidate.market_regime in {"BULLISH", "NEUTRAL-BULLISH"} else 0
    trend = 100 if candidate.trend == "BULLISH" else 0
    volatility = min(100, max(0, round(candidate.implied_volatility * 100)))
    liquidity = max(0, 100 - round(candidate.bid_ask_spread * 100))
    strike = min(100, max(0, round(abs(candidate.short_delta) * 500)))
    reward = min(100, max(0, round(candidate.midpoint_credit / candidate.spread_width * 1000)))
    weighted = (
        regime * settings.score_weight_regime
        + trend * settings.score_weight_trend
        + volatility * settings.score_weight_volatility
        + liquidity * settings.score_weight_liquidity
        + strike * settings.score_weight_strike
        + reward * settings.score_weight_reward
    ) / 100
    return max(0, min(100, round(weighted)))
