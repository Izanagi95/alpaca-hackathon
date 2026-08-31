"""Concrete AI provider: sends a candidate to an LLM hosted on Featherless.ai
and returns its raw structured response. This is the only place that talks
to an LLM. The response is untrusted until `AIDecisionLayer.analyze`
validates it against the `AIProposal` schema — this function must never be
treated as a decision by itself.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any

from app.config.settings import Settings

_MAX_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 1.0

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised only when the package is missing
    OpenAI = None  # type: ignore[assignment,misc]

_SYSTEM_PROMPT = (
    "You are a consultative options analyst. You are given structured, verified market and "
    "option data for one Bull Put Spread candidate. You do not predict the market or invent "
    "probabilities. Evaluate only the given fields (trend, realized/implied volatility, market "
    "regime, strikes, delta, credit, liquidity) and decide whether this specific candidate looks "
    "attractive on defined-risk, income-oriented grounds. Your output is advisory only: a separate "
    "deterministic risk engine makes the final call and can reject your APPROVE. "
    "Respond with ONLY a single JSON object — no markdown code fences, no explanation before or "
    "after it — with exactly these keys: decision (\"APPROVE\" or \"REJECT\"), score (integer 0-100), "
    "strategy (must be \"bull_put_spread\"), confidence (number 0-1), rationale (a non-empty array of "
    "short strings), risk_flags (an array of short strings, possibly empty)."
)


def build_featherless_provider(settings: Settings) -> Callable[[dict[str, Any]], Mapping[str, Any]]:
    """Featherless.ai hosts many different open-weight models behind an OpenAI-compatible
    API; native tool-calling support varies by model, so this provider asks for plain JSON
    in the response text instead of relying on a tool call. AIDecisionLayer still validates
    the result against the same strict schema — malformed JSON becomes a forced REJECT."""
    if OpenAI is None:
        raise RuntimeError("the 'openai' package is not installed")
    if not settings.featherless_api_key:
        raise RuntimeError("FEATHERLESS_API_KEY is required to build the Featherless AI provider")

    client = OpenAI(api_key=settings.featherless_api_key, base_url=settings.featherless_base_url)

    def provider(candidate_payload: dict[str, Any]) -> Mapping[str, Any]:
        # A shared Featherless key under concurrent load (multiple bots scanning
        # at once) occasionally returns an empty/truncated completion rather than
        # a hard error — one immediate retry recovers most of those without
        # masking a genuinely broken response as a real AI rejection.
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = client.chat.completions.create(
                    model=settings.ai_model,
                    max_tokens=1024,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": _format_candidate(candidate_payload)},
                    ],
                )
                content = response.choices[0].message.content or ""
                return json.loads(_strip_code_fence(content))
            except Exception as error:  # noqa: BLE001 - any failure here is a retry candidate
                last_error = error
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_DELAY_SECONDS)
        raise RuntimeError(f"Featherless call failed after {_MAX_ATTEMPTS} attempts: {last_error}") from last_error

    return provider


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
        if stripped.endswith("```"):
            stripped = stripped[: -3]
    return stripped.strip()


def _format_candidate(candidate_payload: dict[str, Any]) -> str:
    return "Evaluate this Bull Put Spread candidate:\n" + json.dumps(candidate_payload, indent=2, default=str)
