from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings
from app.strategy.bull_put_spread import BullPutSpreadCandidate
from app.strategy.position_sizing import calculate_contracts


@dataclass(frozen=True)
class RiskContext:
    equity: float
    daily_pnl_fraction: float
    open_positions: int
    open_symbols: frozenset[str] = frozenset()
    portfolio_risk_used: float = 0.0


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    contracts: int
    checks: dict[str, bool]
    reasons: tuple[str, ...]


class RiskEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, candidate: BullPutSpreadCandidate, context: RiskContext, ai_score: int) -> RiskDecision:
        contracts = calculate_contracts(
            context.equity,
            candidate.max_loss_per_contract,
            self._settings.max_position_risk,
        )
        checks = {
            "paper_mode": self._settings.paper_trading_only and self._settings.alpaca_paper,
            "dte": self._settings.min_dte <= candidate.dte <= self._settings.max_dte,
            "credit": candidate.midpoint_credit >= self._settings.min_credit,
            "liquidity_spread": candidate.bid_ask_spread <= self._settings.max_bid_ask_spread,
            "open_interest": min(candidate.short_open_interest, candidate.long_open_interest) >= self._settings.min_open_interest,
            "volume": min(candidate.short_volume, candidate.long_volume) >= self._settings.min_volume,
            "defined_risk": candidate.max_loss_per_contract > 0,
            "position_limit": context.open_positions < self._settings.max_open_positions,
            "daily_loss": context.daily_pnl_fraction > -self._settings.max_daily_loss,
            "portfolio_risk": context.portfolio_risk_used + self._settings.max_position_risk <= self._settings.max_portfolio_risk,
            "duplicate_exposure": candidate.symbol not in context.open_symbols,
            "ai_score": ai_score >= self._settings.min_ai_score,
            "sizing": contracts > 0,
        }
        reasons = tuple(name for name, passed in checks.items() if not passed)
        return RiskDecision(not reasons, contracts if not reasons else 0, checks, reasons)
