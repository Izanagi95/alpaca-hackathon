import pytest

from app.alpaca.client import AlpacaClients
from app.config.settings import Settings


def test_clients_refuse_missing_credentials() -> None:
    with pytest.raises(RuntimeError, match="API_KEY"):
        AlpacaClients(Settings())


def test_clients_refuse_live_mode_before_credentials() -> None:
    settings = Settings(alpaca_paper=False, api_key="key", secret_key="secret")

    with pytest.raises(RuntimeError, match="PAPER_TRADING_ONLY"):
        AlpacaClients(settings)
