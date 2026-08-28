from types import SimpleNamespace

import pytest

from app.agents import ai_provider
from app.agents.ai_decision import AIDecisionLayer
from app.config.settings import Settings
from app.strategy.bull_put_spread import BullPutSpreadCandidate
from datetime import date, timedelta


def make_candidate() -> BullPutSpreadCandidate:
    return BullPutSpreadCandidate(
        symbol="AAPL", expiration=date.today() + timedelta(days=30), underlying_price=250,
        short_strike=240, long_strike=235, short_delta=-0.18,
        short_bid=1.30, short_ask=1.40, long_bid=0.20, long_ask=0.30,
        short_open_interest=3200, long_open_interest=2800, short_volume=500, long_volume=400,
        market_regime="bullish", trend="bullish", realized_volatility=0.24, implied_volatility=0.31,
    )


class _FakeToolUseBlock:
    type = "tool_use"
    name = "submit_options_proposal"

    def __init__(self, payload: dict) -> None:
        self.input = payload


class _FakeMessages:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(content=[_FakeToolUseBlock(self._payload)])


class _FakeAnthropic:
    def __init__(self, payload: dict, api_key: str) -> None:
        self.messages = _FakeMessages(payload)


def test_provider_requires_api_key() -> None:
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ai_provider.build_anthropic_provider(Settings(anthropic_api_key=""))


def test_provider_parses_valid_tool_call(monkeypatch) -> None:
    payload = {
        "decision": "APPROVE", "score": 82, "strategy": "bull_put_spread",
        "confidence": 0.8, "rationale": ["defined risk"], "risk_flags": [],
    }
    monkeypatch.setattr(ai_provider, "Anthropic", lambda api_key: _FakeAnthropic(payload, api_key))

    provider = ai_provider.build_anthropic_provider(Settings(anthropic_api_key="test-key"))
    result = provider(make_candidate().model_dump(mode="json"))

    assert result == payload


def test_provider_output_feeds_ai_decision_layer_validation(monkeypatch) -> None:
    payload = {
        "decision": "APPROVE", "score": 82, "strategy": "bull_put_spread",
        "confidence": 0.8, "rationale": ["defined risk"], "risk_flags": [],
    }
    monkeypatch.setattr(ai_provider, "Anthropic", lambda api_key: _FakeAnthropic(payload, api_key))
    provider = ai_provider.build_anthropic_provider(Settings(anthropic_api_key="test-key"))

    proposal = AIDecisionLayer(provider).analyze(make_candidate())

    assert proposal.decision == "APPROVE"
    assert proposal.score == 82


def test_missing_tool_call_becomes_forced_rejection(monkeypatch) -> None:
    class _NoToolMessages:
        def create(self, **kwargs):
            return SimpleNamespace(content=[])

    class _NoToolAnthropic:
        def __init__(self, api_key: str) -> None:
            self.messages = _NoToolMessages()

    monkeypatch.setattr(ai_provider, "Anthropic", _NoToolAnthropic)
    provider = ai_provider.build_anthropic_provider(Settings(anthropic_api_key="test-key"))

    proposal = AIDecisionLayer(provider).analyze(make_candidate())

    assert proposal.decision == "REJECT"
    assert "invalid_ai_output" in proposal.risk_flags
