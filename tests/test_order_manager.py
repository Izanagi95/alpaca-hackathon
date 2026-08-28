from datetime import date, timedelta

from app.config.settings import Settings
from app.execution.order_manager import OrderManager
from app.execution.position_manager import ExitDecision, ExitReason, ManagedPosition
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


def test_dry_run_never_needs_clients() -> None:
    candidate = make_candidate()
    risk = RiskEngine(Settings()).evaluate(candidate, RiskContext(100_000, 0, 0), 80)

    result = OrderManager(Settings(dry_run=True)).submit_bull_put_spread(candidate, risk)

    assert result.submitted is True
    assert result.dry_run is True
    assert result.order is None
    assert result.reason == "dry run; no order submitted"


def test_unapproved_risk_cannot_submit_even_in_dry_run() -> None:
    candidate = make_candidate()
    risk = RiskEngine(Settings()).evaluate(candidate, RiskContext(100_000, -0.03, 0), 80)

    result = OrderManager(Settings(dry_run=True)).submit_bull_put_spread(candidate, risk)

    assert result.submitted is False
    assert result.reason == "risk decision is not approved"


def test_live_mode_requires_clients() -> None:
    candidate = make_candidate()
    risk = RiskEngine(Settings()).evaluate(candidate, RiskContext(100_000, 0, 0), 80)

    result = OrderManager(Settings(dry_run=False)).submit_bull_put_spread(candidate, risk)

    assert result.submitted is False
    assert result.reason == "Alpaca clients are required outside dry run"


class FakeTradingClient:
    def __init__(self) -> None:
        self.request = None

    def submit_order(self, *, order_data):
        self.request = order_data
        return "paper-order-id"


class FakeClients:
    def __init__(self) -> None:
        self.trading = FakeTradingClient()


def test_non_dry_run_builds_defined_two_leg_order() -> None:
    candidate = make_candidate()
    risk = RiskEngine(Settings()).evaluate(candidate, RiskContext(100_000, 0, 0), 80)
    clients = FakeClients()

    result = OrderManager(Settings(dry_run=False), clients).submit_bull_put_spread(candidate, risk)

    assert result.submitted is True
    assert result.order == "paper-order-id"
    assert clients.trading.request.order_class.value == "mleg"
    assert clients.trading.request.limit_price < 0
    assert [leg.position_intent.value for leg in clients.trading.request.legs] == ["sell_to_open", "buy_to_open"]
    assert clients.trading.request.legs[0].symbol == "AAPL" + candidate.expiration.strftime("%y%m%d") + "P00240000"


def test_close_builds_reverse_two_leg_order() -> None:
    candidate = make_candidate()
    position = ManagedPosition("AAPL", 2, 1.10, 0.95, 220, 780, 30, "BULLISH")
    exit_decision = ExitDecision(True, ExitReason.PROFIT_TARGET, 30)
    clients = FakeClients()

    result = OrderManager(Settings(dry_run=False), clients).close_bull_put_spread(candidate, position, exit_decision)

    assert result.submitted is True
    assert clients.trading.request.limit_price == 0.95
    assert [leg.position_intent.value for leg in clients.trading.request.legs] == ["buy_to_close", "sell_to_close"]
