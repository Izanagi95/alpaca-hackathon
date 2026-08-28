from __future__ import annotations

from datetime import datetime

from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame

from app.alpaca.client import AlpacaClients


class MarketDataService:
    def __init__(self, clients: AlpacaClients) -> None:
        self._clients = clients

    def latest_quotes(self, symbols: list[str]) -> object:
        if not symbols:
            return {}
        return self._clients.stock_data.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbols)
        )

    def daily_bars(self, symbols: list[str], start: datetime, end: datetime | None = None) -> object:
        if not symbols:
            return {}
        return self._clients.stock_data.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
            )
        )
