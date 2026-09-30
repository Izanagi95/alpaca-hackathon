from __future__ import annotations

import time

import requests
from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
from alpaca.trading.client import TradingClient

from app.config.settings import Settings

# Alpaca's paper API occasionally times out or drops a connection under
# load — found live twice (a market-data call and a positions call, on two
# separate scheduled runs) — and each time it crashed the whole scan/monitor
# job instead of just that one request, wasting the run and leaving the next
# chance up to fifteen minutes away. A couple of quick retries recover most
# of those within the same run instead.
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2.0


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
            last_error: requests.exceptions.RequestException | None = None
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    return original_request(method, url, **kwargs)
                except requests.exceptions.RequestException as error:
                    # A GET is always safe to retry. A POST (order submission)
                    # is not in general, but every write this project makes
                    # carries its own client_order_id, so a retried submit
                    # either reaches the broker for the first time or is
                    # rejected as a duplicate of one that already went
                    # through — never silently doubled.
                    last_error = error
                    if attempt < _MAX_ATTEMPTS - 1:
                        time.sleep(_RETRY_DELAY_SECONDS)
            raise last_error  # type: ignore[misc]  # loop always sets it before exhausting

        session.request = request_with_timeout

    def verify_account(self) -> object:
        account = self.trading.get_account()
        if getattr(account, "status", None) is None:
            raise RuntimeError("Alpaca returned an account without status")
        return account
