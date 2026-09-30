import requests
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


class _FakeSession:
    def __init__(self, outcomes: list[object]) -> None:
        # Each call to .request() consumes the next outcome: an exception
        # instance to raise, or any other value to return as the "response".
        self._outcomes = list(outcomes)
        self.call_count = 0

    def request(self, method: str, url: str, **kwargs: object) -> object:
        self.call_count += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeSdkClient:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session


def test_request_retries_a_transient_network_error_then_succeeds(monkeypatch) -> None:
    # Found live twice — a market-data call and a positions call each crashed
    # a whole scheduled run on a single Alpaca timeout/dropped connection,
    # wasting the run instead of recovering within it.
    monkeypatch.setattr("app.alpaca.client.time.sleep", lambda seconds: None)
    session = _FakeSession([requests.exceptions.ReadTimeout("timed out"), "ok"])
    client = _FakeSdkClient(session)

    AlpacaClients._set_request_timeout(client, timeout_seconds=15.0)
    result = client._session.request("GET", "https://paper-api.alpaca.markets/v2/account")

    assert result == "ok"
    assert session.call_count == 2


def test_request_gives_up_after_exhausting_retries(monkeypatch) -> None:
    monkeypatch.setattr("app.alpaca.client.time.sleep", lambda seconds: None)
    error = requests.exceptions.ConnectionError("connection aborted")
    session = _FakeSession([error, error, error])
    client = _FakeSdkClient(session)

    AlpacaClients._set_request_timeout(client, timeout_seconds=15.0)
    with pytest.raises(requests.exceptions.ConnectionError):
        client._session.request("GET", "https://paper-api.alpaca.markets/v2/account")

    assert session.call_count == 3  # exactly _MAX_ATTEMPTS, no more


def test_request_succeeds_immediately_without_retry_when_nothing_fails(monkeypatch) -> None:
    monkeypatch.setattr("app.alpaca.client.time.sleep", lambda seconds: (_ for _ in ()).throw(AssertionError("should not sleep")))
    session = _FakeSession(["ok"])
    client = _FakeSdkClient(session)

    AlpacaClients._set_request_timeout(client, timeout_seconds=15.0)
    result = client._session.request("GET", "https://paper-api.alpaca.markets/v2/account")

    assert result == "ok"
    assert session.call_count == 1
