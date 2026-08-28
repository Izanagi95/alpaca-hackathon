from datetime import date, timedelta

from app.config.settings import Settings
from app.risk.risk_engine import RiskContext, RiskEngine
from app.strategy.bull_put_spread import BullPutSpreadCandidate
from app.strategy.position_sizing import calculate_contracts
from app.strategy.scoring import score_candidate


def candidate() -> BullPutSpreadCandidate:
    return BullPutSpreadCandidate(
        symbol="AAPL",
        expiration=date.today() + timedelta(days=30),
        underlying_price=250,
        short_strike=240,
        long_strike=235,
        short_delta=-0.18,
        short_bid=1.30,
        short_ask=1.40,
        long_bid=0.20,
        long_ask=0.30,
        short_open_interest=3200,
        long_open_interest=2800,
        short_volume=500,
        long_volume=400,
        market_regime="bullish",
        trend="bullish",
        realized_volatility=0.24,
        implied_volatility=0.31,
    )


def test_position_sizing_uses_theoretical_max_loss() -> None:
    assert calculate_contracts(100_000, 380, 0.01) == 2


def test_candidate_score_is_bounded() -> None:
    assert 0 <= score_candidate(candidate()) <= 100


def test_risk_engine_approves_valid_defined_risk_trade() -> None:
    decision = RiskEngine(Settings()).evaluate(candidate(), RiskContext(100_000, 0, 0), 80)

    assert decision.approved is True
    assert decision.contracts == 2
    assert not decision.reasons


def test_risk_engine_rejects_insufficient_liquidity() -> None:
    trade = candidate().model_copy(update={"short_open_interest": 10})
    decision = RiskEngine(Settings()).evaluate(trade, RiskContext(100_000, 0, 0), 90)

    assert decision.approved is False
    assert "open_interest" in decision.reasons


def test_risk_engine_rejects_daily_loss_and_duplicate_exposure() -> None:
    decision = RiskEngine(Settings()).evaluate(
        candidate(),
        RiskContext(100_000, -0.03, 0, frozenset({"AAPL"})),
        90,
    )

    assert decision.approved is False
    assert "daily_loss" in decision.reasons
    assert "duplicate_exposure" in decision.reasons
