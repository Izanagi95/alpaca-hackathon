from types import SimpleNamespace

from app.agents.market_analyst import MarketAnalyst


class _FakeBar:
    def __init__(self, close: float) -> None:
        self.close = close


class _FakeMarketData:
    def __init__(self, closes: list[float]) -> None:
        self._closes = closes

    def daily_bars(self, symbols, start=None, end=None):
        return SimpleNamespace(data={symbols[0]: [_FakeBar(c) for c in self._closes]})


def test_uptrend_is_classified_bullish() -> None:
    closes = [100 + i * 0.5 for i in range(30)]  # steadily rising
    analyst = MarketAnalyst(_FakeMarketData(closes))

    assessment = analyst.assess("AAPL")

    assert assessment is not None
    assert assessment.trend == "BULLISH"
    assert assessment.market_regime == "BULLISH"
    assert assessment.underlying_price == closes[-1]


def test_downtrend_is_classified_bearish() -> None:
    closes = [130 - i * 0.5 for i in range(30)]  # steadily falling
    analyst = MarketAnalyst(_FakeMarketData(closes))

    assessment = analyst.assess("AAPL")

    assert assessment is not None
    assert assessment.trend == "BEARISH"
    assert assessment.market_regime == "BEARISH"


def test_insufficient_history_returns_none() -> None:
    analyst = MarketAnalyst(_FakeMarketData([100.0, 101.0]))

    assert analyst.assess("AAPL") is None


def test_realized_volatility_is_nonnegative() -> None:
    closes = [100, 102, 99, 103, 101, 104, 100, 105, 98, 106] * 3
    analyst = MarketAnalyst(_FakeMarketData([float(c) for c in closes]))

    assessment = analyst.assess("AAPL")

    assert assessment is not None
    assert assessment.realized_volatility >= 0
