from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.strategy.bull_put_spread import BullPutSpreadCandidate


class AIProposal(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    score: int = Field(ge=0, le=100)
    strategy: Literal["bull_put_spread"]
    confidence: float = Field(ge=0, le=1)
    rationale: list[str] = Field(min_length=1)
    risk_flags: list[str] = Field(default_factory=list)


class AIDecisionLayer:
    """Validates an external AI response; it cannot approve or submit an order itself."""

    def __init__(self, provider: Callable[[dict[str, Any]], Mapping[str, Any]]) -> None:
        self._provider = provider

    def analyze(self, candidate: BullPutSpreadCandidate) -> AIProposal:
        try:
            response = self._provider(candidate.model_dump(mode="json"))
            return AIProposal.model_validate(response)
        except (ValidationError, TypeError, ValueError, RuntimeError) as error:
            print(f"AI_ERROR symbol={candidate.symbol} error={error}")
            return AIProposal(
                decision="REJECT",
                score=0,
                strategy="bull_put_spread",
                confidence=0,
                rationale=["AI output was invalid or unavailable"],
                risk_flags=["invalid_ai_output"],
            )
