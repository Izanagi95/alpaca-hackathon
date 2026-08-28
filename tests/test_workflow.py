from datetime import date, timedelta

from app.agents.ai_decision import AIDecisionLayer
from app.agents.workflow import TradeWorkflow
from app.config.settings import Settings
from app.database.repository import DecisionRepository
from app.execution.order_manager import OrderManager
from app.risk.risk_engine import RiskContext, RiskEngine
from app.strategy.bull_put_spread import BullPutSpreadCandidate


def make_candidate() -> BullPutSpreadCandidate:
    return BullPutSpreadCandidate(
        symbol="AAPL", expiration=date.today() + timedelta(days=30), underlying_price=250,
        short_strike=240, long_strike=235, short_delta=-0.18,
        short_bid=1.30, short_ask=1.40, long_bid=0.20, long_ask=0.30,
        short_open_interest=3200, long_open_interest=2800, short_volume=500, long_volume=400,
        market_regime="bullish", trend="bullish", realized_volatility=0.24, implied_volatility=0.31,
    )


def make_workflow(tmp_path, response: dict) -> tuple[TradeWorkflow, DecisionRepository]:
    settings = Settings()
    journal = DecisionRepository(tmp_path / "workflow.db")
    return TradeWorkflow(AIDecisionLayer(lambda _: response), RiskEngine(settings), OrderManager(settings), journal), journal


def test_approved_workflow_reaches_dry_run_execution(tmp_path) -> None:
    workflow, journal = make_workflow(tmp_path, {"decision": "APPROVE", "score": 82, "strategy": "bull_put_spread", "confidence": 0.82, "rationale": ["defined risk"], "risk_flags": []})

    result = workflow.evaluate(make_candidate(), RiskContext(100_000, 0, 0))

    assert result.risk_decision.approved is True
    assert result.execution.submitted is True
    assert result.execution.dry_run is True
    assert journal.count() == 1
    journal.close()


def test_ai_rejection_is_journaled_and_cannot_execute(tmp_path) -> None:
    workflow, journal = make_workflow(tmp_path, {"decision": "REJECT", "score": 90, "strategy": "bull_put_spread", "confidence": 0.90, "rationale": ["event risk"], "risk_flags": ["event_risk"]})

    result = workflow.evaluate(make_candidate(), RiskContext(100_000, 0, 0))

    assert result.risk_decision.approved is False
    assert result.execution.submitted is False
    assert "ai_decision_rejected" in result.risk_decision.reasons
    assert journal.count() == 1
    journal.close()


def test_deterministic_gate_failure_skips_the_ai_call_entirely(tmp_path) -> None:
    calls: list[dict] = []

    def spy_provider(payload: dict) -> dict:
        calls.append(payload)
        return {"decision": "APPROVE", "score": 99, "strategy": "bull_put_spread", "confidence": 0.99, "rationale": ["x"], "risk_flags": []}

    settings = Settings()
    journal = DecisionRepository(tmp_path / "workflow.db")
    workflow = TradeWorkflow(AIDecisionLayer(spy_provider), RiskEngine(settings), OrderManager(settings), journal)

    illiquid_candidate = BullPutSpreadCandidate(
        symbol="AAPL", expiration=date.today() + timedelta(days=30), underlying_price=250,
        short_strike=240, long_strike=235, short_delta=-0.18,
        short_bid=1.30, short_ask=1.40, long_bid=0.20, long_ask=0.30,
        short_open_interest=1, long_open_interest=1, short_volume=1, long_volume=1,
        market_regime="bullish", trend="bullish", realized_volatility=0.24, implied_volatility=0.31,
    )

    result = workflow.evaluate(illiquid_candidate, RiskContext(100_000, 0, 0))

    assert calls == []  # the AI provider was never invoked
    assert result.risk_decision.approved is False
    assert "ai_skipped_deterministic_reject" in result.proposal.risk_flags
    assert "open_interest" in result.risk_decision.reasons
    journal.close()