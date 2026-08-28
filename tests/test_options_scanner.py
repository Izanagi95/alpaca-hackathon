from datetime import date, timedelta
from types import SimpleNamespace

from app.agents.market_analyst import MarketAssessment
from app.agents.options_scanner import OptionsScanner
from app.config.settings import Settings


class _FakeContract:
    def __init__(self, symbol: str, strike_price: float, expiration_date: date, open_interest: str = "1000") -> None:
        self.symbol = symbol
        self.strike_price = strike_price
        self.expiration_date = expiration_date
        self.open_interest = open_interest


def _snapshot(bid: float, ask: float, delta: float, iv: float = 0.30, trade_size: int = 50):
    return SimpleNamespace(
        latest_quote=SimpleNamespace(bid_price=bid, ask_price=ask),
        greeks=SimpleNamespace(delta=delta),
        implied_volatility=iv,
        latest_trade=SimpleNamespace(size=trade_size),
    )


class _FakeOptionsData:
    def __init__(self, contracts: list, chain: dict, volumes: dict[str, int] | None = None) -> None:
        self._contracts = contracts
        self._chain = chain
        self._volumes = volumes or {}

    def contracts(self, symbols, expiration_date_gte, expiration_date_lte):
        return SimpleNamespace(option_contracts=self._contracts)

    def chain(self, underlying_symbol, expiration_date_gte, expiration_date_lte):
        return self._chain

    def daily_volume(self, contract_symbols: list[str]) -> dict[str, int]:
        return {symbol: self._volumes.get(symbol, 0) for symbol in contract_symbols}


def assessment() -> MarketAssessment:
    return MarketAssessment(
        symbol="AAPL", underlying_price=250, trend="BULLISH",
        market_regime="BULLISH", realized_volatility=0.25,
    )


def test_scanner_pairs_short_and_long_legs_within_target_delta() -> None:
    expiration = date.today() + timedelta(days=30)
    contracts = [
        _FakeContract("AAPL_240P", 240, expiration),
        _FakeContract("AAPL_235P", 235, expiration),
        _FakeContract("AAPL_260P", 260, expiration),  # too deep ITM-ish, wrong delta
    ]
    chain = {
        "AAPL_240P": _snapshot(bid=1.30, ask=1.40, delta=-0.18),
        "AAPL_235P": _snapshot(bid=0.20, ask=0.30, delta=-0.08),
        "AAPL_260P": _snapshot(bid=5.0, ask=5.2, delta=-0.60),
    }
    volumes = {"AAPL_240P": 120, "AAPL_235P": 80}
    scanner = OptionsScanner(_FakeOptionsData(contracts, chain, volumes), Settings())

    candidates = scanner.scan(assessment())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.short_strike == 240
    assert candidate.long_strike == 235
    assert candidate.short_delta == -0.18
    assert candidate.short_volume == 120
    assert candidate.long_volume == 80


def test_scanner_skips_contracts_without_delta() -> None:
    expiration = date.today() + timedelta(days=30)
    contracts = [_FakeContract("AAPL_240P", 240, expiration), _FakeContract("AAPL_235P", 235, expiration)]
    chain = {
        "AAPL_240P": SimpleNamespace(latest_quote=SimpleNamespace(bid_price=1.3, ask_price=1.4), greeks=None, implied_volatility=0.3, latest_trade=None),
        "AAPL_235P": _snapshot(bid=0.2, ask=0.3, delta=-0.08),
    }
    scanner = OptionsScanner(_FakeOptionsData(contracts, chain), Settings())

    assert scanner.scan(assessment()) == []


def test_scanner_returns_empty_when_no_contracts() -> None:
    scanner = OptionsScanner(_FakeOptionsData([], {}), Settings())

    assert scanner.scan(assessment()) == []
