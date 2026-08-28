"""Turns raw daily bars into the trend/regime/volatility inputs the scanner
and scoring layer need. Every value here is computed from observed prices —
nothing is forecast or invented.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.alpaca.market_data import MarketDataService


@dataclass(frozen=True)
class MarketAssessment:
    symbol: str
    underlying_price: float
    trend: str
    market_regime: str
    realized_volatility: float


class MarketAnalyst:
    """Computes trend/regime/realized volatility from Alpaca daily bars."""

    def __init__(self, market_data: MarketDataService, lookback_days: int = 60) -> None:
        self._market_data = market_data
        self._lookback_days = lookback_days

    def assess(self, symbol: str) -> MarketAssessment | None:
        start = datetime.now(timezone.utc) - timedelta(days=self._lookback_days)
        bars = self._market_data.daily_bars([symbol], start=start)
        closes = self._closes_for(bars, symbol)
        if len(closes) < 20:
            return None  # not enough history to assess trend/volatility; fail closed

        underlying_price = closes[-1]
        short_ma = sum(closes[-10:]) / 10
        long_ma = sum(closes[-20:]) / 20
        realized_volatility = self._annualized_realized_volatility(closes)

        if short_ma > long_ma * 1.01:
            trend = "BULLISH"
            regime = "BULLISH"
        elif short_ma < long_ma * 0.99:
            trend = "BEARISH"
            regime = "BEARISH"
        else:
            trend = "NEUTRAL"
            regime = "NEUTRAL-BULLISH" if short_ma >= long_ma else "NEUTRAL-BEARISH"

        return MarketAssessment(
            symbol=symbol,
            underlying_price=underlying_price,
            trend=trend,
            market_regime=regime,
            realized_volatility=realized_volatility,
        )

    @staticmethod
    def _closes_for(bars: object, symbol: str) -> list[float]:
        data = getattr(bars, "data", bars)
        symbol_bars = data.get(symbol, []) if hasattr(data, "get") else []
        return [float(bar.close) for bar in symbol_bars]

    @staticmethod
    def _annualized_realized_volatility(closes: list[float]) -> float:
        returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        return round(math.sqrt(variance) * math.sqrt(252), 4)
