from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderClass, TimeInForce, PositionIntent
from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest

from app.alpaca.client import AlpacaClients
from app.config.settings import Settings
from app.execution.position_manager import ExitDecision, ManagedPosition
from app.risk.risk_engine import RiskDecision
from app.strategy.bull_put_spread import BullPutSpreadCandidate


@dataclass(frozen=True)
class ExecutionResult:
    submitted: bool
    dry_run: bool
    client_order_id: str
    order: object | None = None
    reason: str | None = None


class OrderManager:
    def __init__(self, settings: Settings, clients: AlpacaClients | None = None) -> None:
        self._settings = settings
        self._clients = clients

    def submit_bull_put_spread(
        self,
        candidate: BullPutSpreadCandidate,
        risk_decision: RiskDecision,
    ) -> ExecutionResult:
        client_order_id = f"oaa-{uuid4().hex[:20]}"
        if not self._settings.paper_trading_only or not self._settings.alpaca_paper:
            return ExecutionResult(False, self._settings.dry_run, client_order_id, reason="paper mode is required")
        if not risk_decision.approved or risk_decision.contracts <= 0:
            return ExecutionResult(False, self._settings.dry_run, client_order_id, reason="risk decision is not approved")
        if self._settings.dry_run:
            return ExecutionResult(True, True, client_order_id, reason="dry run; no order submitted")
        if self._clients is None:
            return ExecutionResult(False, False, client_order_id, reason="Alpaca clients are required outside dry run")

        order_request = LimitOrderRequest(
            qty=risk_decision.contracts,
            limit_price=-round(candidate.midpoint_credit, 2),
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.MLEG,
            client_order_id=client_order_id,
            legs=[
                OptionLegRequest(
                    symbol=f"{candidate.symbol}{candidate.expiration:%y%m%d}P{int(candidate.short_strike * 1000):08d}",
                    ratio_qty=1,
                    position_intent=PositionIntent.SELL_TO_OPEN,
                ),
                OptionLegRequest(
                    symbol=f"{candidate.symbol}{candidate.expiration:%y%m%d}P{int(candidate.long_strike * 1000):08d}",
                    ratio_qty=1,
                    position_intent=PositionIntent.BUY_TO_OPEN,
                ),
            ],
        )
        try:
            order = self._clients.trading.submit_order(order_data=order_request)
        except APIError as error:
            # A broker-level rejection (e.g. one leg's strike collides with an
            # already-open position from a prior trade, so Alpaca infers the
            # opposite intent from the one requested) must not kill the whole
            # scan — every other candidate this cycle still deserves a chance.
            return ExecutionResult(False, False, client_order_id, reason=f"broker rejected order: {error}")
        return ExecutionResult(True, False, client_order_id, order=order)

    def close_bull_put_spread(
        self,
        candidate: BullPutSpreadCandidate,
        position: ManagedPosition,
        exit_decision: ExitDecision,
    ) -> ExecutionResult:
        client_order_id = f"oaa-close-{uuid4().hex[:16]}"
        if not self._settings.paper_trading_only or not self._settings.alpaca_paper:
            return ExecutionResult(False, self._settings.dry_run, client_order_id, reason="paper mode is required")
        if not exit_decision.should_exit:
            return ExecutionResult(False, self._settings.dry_run, client_order_id, reason="exit rules do not require closing")
        if self._settings.dry_run:
            return ExecutionResult(True, True, client_order_id, reason="dry run; no close order submitted")
        if self._clients is None:
            return ExecutionResult(False, False, client_order_id, reason="Alpaca clients are required outside dry run")

        order_request = LimitOrderRequest(
            qty=position.contracts,
            limit_price=round(position.current_debit, 2),
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.MLEG,
            client_order_id=client_order_id,
            legs=[
                OptionLegRequest(
                    symbol=f"{candidate.symbol}{candidate.expiration:%y%m%d}P{int(candidate.short_strike * 1000):08d}",
                    ratio_qty=1,
                    position_intent=PositionIntent.BUY_TO_CLOSE,
                ),
                OptionLegRequest(
                    symbol=f"{candidate.symbol}{candidate.expiration:%y%m%d}P{int(candidate.long_strike * 1000):08d}",
                    ratio_qty=1,
                    position_intent=PositionIntent.SELL_TO_CLOSE,
                ),
            ],
        )
        try:
            order = self._clients.trading.submit_order(order_data=order_request)
        except APIError as error:
            return ExecutionResult(False, False, client_order_id, reason=f"broker rejected order: {error}")
        return ExecutionResult(True, False, client_order_id, order=order)
