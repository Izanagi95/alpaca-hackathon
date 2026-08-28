from __future__ import annotations

from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.trading.client import TradingClient

from app.config.settings import Settings


class AlpacaClients:
    """Constructs all SDK clients only after enforcing paper-only configuration."""

    def __init__(self, settings: Settings) -> None:
        settings.require_paper_mode()
        settings.require_credentials()
        self.trading = TradingClient(settings.api_key, settings.secret_key, paper=True)
        self.stock_data = StockHistoricalDataClient(settings.api_key, settings.secret_key)
        self.option_data = OptionHistoricalDataClient(settings.api_key, settings.secret_key)
        self._set_request_timeout(self.trading, settings.request_timeout_seconds)
        self._set_request_timeout(self.stock_data, settings.request_timeout_seconds)
        self._set_request_timeout(self.option_data, settings.request_timeout_seconds)

    @staticmethod
    def _set_request_timeout(client: object, timeout_seconds: float) -> None:
        if timeout_seconds <= 0:
            raise ValueError("request timeout must be greater than zero")
        session = getattr(client, "_session", None)
        if session is None:
            return
        original_request = session.request

        def request_with_timeout(method: str, url: str, **kwargs: object) -> object:
            kwargs.setdefault("timeout", timeout_seconds)
            return original_request(method, url, **kwargs)

        session.request = request_with_timeout

    def verify_account(self) -> object:
        account = self.trading.get_account()
        if getattr(account, "status", None) is None:
            raise RuntimeError("Alpaca returned an account without status")
        return account
