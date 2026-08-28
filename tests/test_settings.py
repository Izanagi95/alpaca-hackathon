import pytest

from app.config.settings import Settings


def test_defaults_are_paper_and_dry_run() -> None:
    settings = Settings()

    assert settings.alpaca_paper is True
    assert settings.paper_trading_only is True
    assert settings.dry_run is True


def test_non_paper_configuration_is_rejected() -> None:
    settings = Settings(alpaca_paper=False)

    with pytest.raises(RuntimeError, match="PAPER_TRADING_ONLY"):
        settings.require_paper_mode()


def test_watchlist_is_normalized() -> None:
    settings = Settings(watchlist="aapl, msft")

    assert settings.watchlist == ["AAPL", "MSFT"]


def test_invalid_risk_fraction_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(max_position_risk=1.1)


def test_request_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError):
        Settings(request_timeout_seconds=0)
