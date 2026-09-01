from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.config.settings import Settings


class ExitReason(StrEnum):
    PROFIT_TARGET = "profit_target"
    STOP_LOSS = "stop_loss"
    TIME_EXIT = "time_exit"
    REGIME_EXIT = "regime_exit"
    HOLD = "hold"


BULLISH_REGIMES = {"BULLISH", "NEUTRAL-BULLISH"}
BEARISH_REGIMES = {"BEARISH", "NEUTRAL-BEARISH"}


@dataclass(frozen=True)
class ManagedPosition:
    symbol: str
    contracts: int
    entry_credit: float
    current_debit: float
    max_profit: float
    max_loss: float
    dte: int
    market_regime: str
    # A bull put spread wants the market up or flat; a bear call spread wants
    # the opposite, so the regime exit has to be read against the direction
    # the position was opened in rather than assuming bullish.
    strategy: str = "bull_put_spread"

    @property
    def regime_turned_against_position(self) -> bool:
        regime = self.market_regime.upper()
        if self.strategy == "bear_call_spread":
            return regime not in BEARISH_REGIMES
        return regime not in BULLISH_REGIMES

    @property
    def current_pnl(self) -> float:
        return round((self.entry_credit - self.current_debit) * 100 * self.contracts, 2)


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: ExitReason
    current_pnl: float


class PositionManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate_exit(self, position: ManagedPosition) -> ExitDecision:
        # current_pnl is the position total, while max_profit/max_loss are
        # per-contract (that is how the journal stores them, and how
        # run_agent.py reads them back), so the thresholds have to be scaled
        # to the position size too. Comparing the total against a
        # per-contract threshold silently divided both by `contracts` —
        # stopping out at ~12% of max loss on a 6-lot instead of 50%.
        contracts = max(position.contracts, 1)
        profit_target = position.max_profit * contracts * self._settings.profit_target_fraction
        stop_loss = position.max_loss * contracts * self._settings.stop_loss_fraction
        pnl = position.current_pnl
        if pnl >= profit_target:
            return ExitDecision(True, ExitReason.PROFIT_TARGET, pnl)
        if pnl <= -stop_loss:
            return ExitDecision(True, ExitReason.STOP_LOSS, pnl)
        if position.dte <= self._settings.exit_before_expiry_dte:
            return ExitDecision(True, ExitReason.TIME_EXIT, pnl)
        if position.regime_turned_against_position:
            return ExitDecision(True, ExitReason.REGIME_EXIT, pnl)
        return ExitDecision(False, ExitReason.HOLD, pnl)
