from __future__ import annotations

from dataclasses import dataclass

from app.agents.ai_decision import AIDecisionLayer, AIProposal
from app.database.repository import DecisionRepository
from app.execution.order_manager import ExecutionResult, OrderManager
from app.risk.risk_engine import RiskContext, RiskDecision, RiskEngine
from app.strategy.bull_put_spread import BullPutSpreadCandidate


@dataclass(frozen=True)
class WorkflowResult:
    proposal: AIProposal
    risk_decision: RiskDecision
    execution: ExecutionResult


class TradeWorkflow:
    def __init__(self, ai_layer: AIDecisionLayer, risk_engine: RiskEngine, order_manager: OrderManager, journal: DecisionRepository) -> None:
        self._ai_layer = ai_layer
        self._risk_engine = risk_engine
        self._order_manager = order_manager
        self._journal = journal

    def evaluate(self, candidate: BullPutSpreadCandidate, context: RiskContext) -> WorkflowResult:
        proposal = self._ai_layer.analyze(candidate)
        risk_decision = self._risk_engine.evaluate(candidate, context, proposal.score)
        if proposal.decision != "APPROVE":
            risk_decision = RiskDecision(False, 0, {**risk_decision.checks, "ai_decision": False}, (*risk_decision.reasons, "ai_decision_rejected"))
        self._journal.record(candidate, proposal, risk_decision)
        execution = self._order_manager.submit_bull_put_spread(candidate, risk_decision)
        self._journal.record_trade_open(candidate, proposal, risk_decision, execution)
        return WorkflowResult(proposal, risk_decision, execution)
