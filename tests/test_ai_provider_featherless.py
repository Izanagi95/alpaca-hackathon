from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.agents import ai_provider
from app.agents.ai_decision import AIDecisionLayer
from app.config.settings import Settings
from app.strategy.bull_put_spread import BullPutSpreadCandidate


def make_candidate() -> BullPutSpreadCandidate:
    return BullPutSpreadCandidate(
        symbol="AAPL", expiration=date.today() + timedelta(days=30), underlying_price=250,
        short_strike=240, long_strike=235, short_delta=-0.18,
        short_bid=1.30, short_ask=1.40, long_bid=0.20, long_ask=0.30,
        short_open_interest=3200, long_open_interest=2800, short_volume=500, long_volume=400,
        market_regime="bullish", trend="bullish", realized_volatility=0.24, implied_volatility=0.31,
    )


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content

    def create(self, **kwargs):
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeOpenAI:
    def __init__(self, content: str, api_key: str, base_url: str) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(content))


def test_provider_requires_api_key() -> None:
    with pytest.raises(RuntimeError, match="FEATHERLESS_API_KEY"):
        ai_provider.build_featherless_provider(Settings(featherless_api_key=""))


def test_provider_parses_plain_json_response(monkeypatch) -> None:
    payload = '{"decision": "APPROVE", "score": 80, "strategy": "bull_put_spread", "confidence": 0.75, "rationale": ["defined risk"], "risk_flags": []}'
    monkeypatch.setattr(ai_provider, "OpenAI", lambda api_key, base_url: _FakeOpenAI(payload, api_key, base_url))

    provider = ai_provider.build_featherless_provider(Settings(featherless_api_key="test-key"))
    result = provider(make_candidate().model_dump(mode="json"))

    assert result["decision"] == "APPROVE"
    assert result["score"] == 80


def test_provider_strips_markdown_code_fence(monkeypatch) -> None:
    payload = (
        "```json\n"
        '{"decision": "REJECT", "score": 40, "strategy": "bull_put_spread", '
        '"confidence": 0.3, "rationale": ["thin liquidity"], "risk_flags": ["liquidity"]}\n'
        "```"
    )
    monkeypatch.setattr(ai_provider, "OpenAI", lambda api_key, base_url: _FakeOpenAI(payload, api_key, base_url))

    provider = ai_provider.build_featherless_provider(Settings(featherless_api_key="test-key"))
    result = provider(make_candidate().model_dump(mode="json"))

    assert result["decision"] == "REJECT"
    assert result["risk_flags"] == ["liquidity"]


def test_malformed_json_becomes_forced_rejection(monkeypatch) -> None:
    monkeypatch.setattr(ai_provider, "OpenAI", lambda api_key, base_url: _FakeOpenAI("not json at all", api_key, base_url))
    provider = ai_provider.build_featherless_provider(Settings(featherless_api_key="test-key"))

    proposal = AIDecisionLayer(provider).analyze(make_candidate())

    assert proposal.decision == "REJECT"
    assert "invalid_ai_output" in proposal.risk_flags
