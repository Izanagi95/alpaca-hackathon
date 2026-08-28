from datetime import date, timedelta

from app.agents.ai_decision import AIProposal
from app.database.repository import DecisionRepository
from app.execution.order_manager import ExecutionResult
from app.execution.position_manager import ExitDecision, ExitReason
from app.risk.risk_engine import RiskDecision
from app.strategy.bull_put_spread import BullPutSpreadCandidate


def make_candidate() -> BullPutSpreadCandidate:
    return BullPutSpreadCandidate(
        symbol="AAPL", expiration=date.today() + timedelta(days=30), underlying_price=250,
        short_strike=240, long_strike=235, short_delta=-0.18,
        short_bid=1.30, short_ask=1.40, long_bid=0.20, long_ask=0.30,
        short_open_interest=3200, long_open_interest=2800, short_volume=500, long_volume=400,
        market_regime="bullish", trend="bullish", realized_volatility=0.24, implied_volatility=0.31,
    )


def make_proposal() -> AIProposal:
    return AIProposal(decision="APPROVE", score=82, strategy="bull_put_spread", confidence=0.82, rationale=["defined risk"], risk_flags=[])


def test_only_submitted_executions_are_journaled_as_trades(tmp_path) -> None:
    journal = DecisionRepository(tmp_path / "journal.db")
    candidate = make_candidate()
    risk_decision = RiskDecision(True, 2, {"paper_mode": True}, ())

    rejected_execution = ExecutionResult(False, True, "oaa-1", reason="risk decision is not approved")
    assert journal.record_trade_open(candidate, make_proposal(), risk_decision, rejected_execution) is None
    assert journal.list_open_trades() == []

    submitted_execution = ExecutionResult(True, True, "oaa-2", reason="dry run; no order submitted")
    trade_id = journal.record_trade_open(candidate, make_proposal(), risk_decision, submitted_execution)
    assert trade_id is not None

    open_trades = journal.list_open_trades()
    assert len(open_trades) == 1
    assert open_trades[0]["symbol"] == "AAPL"
    assert open_trades[0]["contracts"] == 2
    journal.close()


def test_closing_a_trade_records_exit_reason_and_pnl(tmp_path) -> None:
    journal = DecisionRepository(tmp_path / "journal.db")
    candidate = make_candidate()
    risk_decision = RiskDecision(True, 1, {"paper_mode": True}, ())
    submitted_execution = ExecutionResult(True, True, "oaa-3", reason="dry run; no order submitted")
    trade_id = journal.record_trade_open(candidate, make_proposal(), risk_decision, submitted_execution)
    assert trade_id is not None

    exit_decision = ExitDecision(True, ExitReason.PROFIT_TARGET, 132.0)
    close_execution = ExecutionResult(True, True, "oaa-close-3", reason="dry run; no close order submitted")
    journal.record_trade_close(trade_id, exit_decision, close_execution)

    recent = journal.list_recent_trades()
    assert recent[0]["exit_reason"] == "profit_target"
    assert recent[0]["realized_pnl"] == 132.0
    assert recent[0]["execution_status"] == "closed_dry_run"
    assert journal.list_open_trades() == []
    journal.close()
