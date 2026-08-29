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
        pre_screen = self._risk_engine.pre_screen(candidate, context)
        if not pre_screen.approved:
            # Fails on liquidity/DTE/credit/sizing/etc. regardless of what the AI
            # would say — skip the AI call entirely rather than spending time and
            # money asking about a candidate that can never be approved.
            # `decision="REJECT"` here means "the AI was never consulted", not
            # "the AI rejected it" (that case sets risk_flags=["invalid_ai_output"]
            # in AIDecisionLayer.analyze instead) — the rationale and
            # risk_flags=["ai_skipped_deterministic_reject"] below are what
            # distinguish the two REJECT causes for anyone reading the journal.
            proposal = AIProposal(
                decision="REJECT", score=0, strategy="bull_put_spread", confidence=0.0,
                rationale=["Rejected by deterministic risk gates before AI evaluation"],
                risk_flags=["ai_skipped_deterministic_reject"],
            )
            risk_decision = RiskDecision(False, 0, {**pre_screen.checks, "ai_score": False}, (*pre_screen.reasons, "ai_score"))
        else:
            proposal = self._ai_layer.analyze(candidate)
            risk_decision = self._risk_engine.evaluate(candidate, context, proposal.score)
            if proposal.decision != "APPROVE":
                risk_decision = RiskDecision(False, 0, {**risk_decision.checks, "ai_decision": False}, (*risk_decision.reasons, "ai_decision_rejected"))

        self._journal.record(candidate, proposal, risk_decision)
        execution = self._order_manager.submit_bull_put_spread(candidate, risk_decision)
        self._journal.record_trade_open(candidate, proposal, risk_decision, execution)
        return WorkflowResult(proposal, risk_decision, execution)
