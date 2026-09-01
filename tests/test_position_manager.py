from app.config.settings import Settings
from app.execution.position_manager import ExitReason, ManagedPosition, PositionManager


def position(**overrides) -> ManagedPosition:
    # max_profit/max_loss are per contract, matching what the journal stores
    # and hands back to the monitor: a 1.10 credit on a 5-wide spread is
    # 110 of profit and 390 of risk per contract, here held 2 contracts.
    values = {
        "symbol": "AAPL", "contracts": 2, "entry_credit": 1.10,
        "current_debit": 0.44, "max_profit": 110, "max_loss": 390,
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


def test_thresholds_scale_with_position_size() -> None:
    # A loss of 1.00 per contract is well inside a 390-per-contract stop at
    # 50%, no matter how many contracts are held. Comparing the position's
    # total P&L against a per-contract threshold used to stop this out at a
    # fraction of the intended loss, and the bigger the position the earlier
    # it fired.
    decision = PositionManager(Settings()).evaluate_exit(position(contracts=6, current_debit=2.10))

    assert decision.current_pnl == -600
    assert decision.should_exit is False
    assert decision.reason == ExitReason.HOLD


def test_healthy_position_is_held() -> None:
    decision = PositionManager(Settings()).evaluate_exit(position(current_debit=0.95))

    assert decision.should_exit is False
    assert decision.reason == ExitReason.HOLD
