from app.config.settings import Settings
from app.execution.position_manager import ExitReason, ManagedPosition, PositionManager


def position(**overrides) -> ManagedPosition:
    values = {
        "symbol": "AAPL", "contracts": 2, "entry_credit": 1.10,
        "current_debit": 0.44, "max_profit": 220, "max_loss": 780,
        "dte": 30, "market_regime": "BULLISH",
    }
    values.update(overrides)
    return ManagedPosition(**values)


def test_profit_target_exits_at_configured_fraction() -> None:
    decision = PositionManager(Settings()).evaluate_exit(position(current_debit=0.44))

    assert decision.should_exit is True
    assert decision.reason == ExitReason.PROFIT_TARGET
    assert decision.current_pnl == 132


def test_stop_loss_exits_before_theoretical_max_loss() -> None:
    decision = PositionManager(Settings()).evaluate_exit(position(current_debit=3.05))

    assert decision.should_exit is True
    assert decision.reason == ExitReason.STOP_LOSS


def test_time_and_regime_exits() -> None:
    manager = PositionManager(Settings())

    assert manager.evaluate_exit(position(dte=7, current_debit=0.95)).reason == ExitReason.TIME_EXIT
    assert manager.evaluate_exit(position(market_regime="BEARISH", current_debit=0.95)).reason == ExitReason.REGIME_EXIT


def test_healthy_position_is_held() -> None:
    decision = PositionManager(Settings()).evaluate_exit(position(current_debit=0.95))

    assert decision.should_exit is False
    assert decision.reason == ExitReason.HOLD
