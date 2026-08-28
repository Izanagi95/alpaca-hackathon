from datetime import date, timedelta

from app.agents.ai_decision import AIDecisionLayer
from app.database.repository import DecisionRepository
from app.risk.risk_engine import RiskContext, RiskEngine
from app.config.settings import Settings
from app.strategy.bull_put_spread import BullPutSpreadCandidate


def make_candidate() -> BullPutSpreadCandidate:
    return BullPutSpreadCandidate(
        symbol="AAPL", expiration=date.today() + timedelta(days=30), underlying_price=250,
        short_strike=240, long_strike=235, short_delta=-0.18,
        short_bid=1.30, short_ask=1.40, long_bid=0.20, long_ask=0.30,
        short_open_interest=3200, long_open_interest=2800, short_volume=500, long_volume=400,
        market_regime="bullish", trend="bullish", realized_volatility=0.24, implied_volatility=0.31,
    )


def test_invalid_ai_output_is_rejected() -> None:
    proposal = AIDecisionLayer(lambda _: {"decision": "APPROVE"}).analyze(make_candidate())

    assert proposal.decision == "REJECT"
    assert "invalid_ai_output" in proposal.risk_flags


def test_valid_ai_output_is_schema_validated() -> None:
    proposal = AIDecisionLayer(lambda _: {
        "decision": "APPROVE", "score": 82, "strategy": "bull_put_spread",
        "confidence": 0.82, "rationale": ["defined risk"], "risk_flags": [],
    }).analyze(make_candidate())

    assert proposal.decision == "APPROVE"
    assert proposal.score == 82


def test_decision_repository_reconstructs_final_decision(tmp_path) -> None:
    candidate = make_candidate()
    proposal = AIDecisionLayer(lambda _: {
        "decision": "APPROVE", "score": 82, "strategy": "bull_put_spread",
        "confidence": 0.82, "rationale": ["defined risk"], "risk_flags": [],
    }).analyze(candidate)
    risk = RiskEngine(Settings()).evaluate(candidate, RiskContext(100_000, 0, 0), proposal.score)
    repository = DecisionRepository(tmp_path / "journal.db")

    repository.record(candidate, proposal, risk)

    assert repository.count() == 1
    repository.close()
