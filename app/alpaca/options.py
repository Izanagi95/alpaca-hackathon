from __future__ import annotations

from datetime import date, datetime, timezone

from alpaca.data.requests import OptionBarsRequest, OptionChainRequest, OptionLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.enums import AssetStatus, ContractType
from alpaca.trading.requests import GetOptionContractsRequest

from app.alpaca.client import AlpacaClients


class OptionsDataService:
    def __init__(self, clients: AlpacaClients) -> None:
        self._clients = clients

    def contracts(
        self,
        underlying_symbols: list[str],
        expiration_date_gte: date,
        expiration_date_lte: date,
    ) -> object:
        if not underlying_symbols:
            return []
        request = GetOptionContractsRequest(
            underlying_symbols=underlying_symbols,
            status=AssetStatus.ACTIVE,
            type=ContractType.PUT,
            expiration_date_gte=expiration_date_gte,
            expiration_date_lte=expiration_date_lte,
            limit=10000,
        )
        return self._clients.trading.get_option_contracts(request)

    def latest_quotes(self, contract_symbols: list[str]) -> object:
        if not contract_symbols:
            return {}
        return self._clients.option_data.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=contract_symbols)
        )

    def chain(
        self,
        underlying_symbol: str,
        expiration_date_gte: date,
        expiration_date_lte: date,
    ) -> object:
        """Latest quote, implied volatility and greeks for every put contract of a symbol."""
        request = OptionChainRequest(
            underlying_symbol=underlying_symbol,
            type=ContractType.PUT,
            expiration_date_gte=expiration_date_gte,
            expiration_date_lte=expiration_date_lte,
        )
        return self._clients.option_data.get_option_chain(request)

    def daily_volume(self, contract_symbols: list[str]) -> dict[str, int]:
        """Real cumulative volume for today's session, one batched request for
        every contract symbol. Falls back to 0 for a symbol with no bar yet
        today (illiquid contract, no trades) rather than guessing."""
        if not contract_symbols:
            return {}
        start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        bar_set = self._clients.option_data.get_option_bars(
            OptionBarsRequest(symbol_or_symbols=contract_symbols, timeframe=TimeFrame.Day, start=start_of_day)
        )
        data = getattr(bar_set, "data", bar_set)
        volumes: dict[str, int] = {}
        for symbol in contract_symbols:
            bars = data.get(symbol, []) if hasattr(data, "get") else []
            volumes[symbol] = int(bars[-1].volume) if bars else 0
        return volumes
