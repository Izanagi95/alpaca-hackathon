from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
    api_key: str = Field(default="", repr=False)
    secret_key: str = Field(default="", repr=False)
    alpaca_paper: bool = True
    paper_trading_only: bool = True
    dry_run: bool = True
    max_portfolio_risk: float = 0.05
    max_position_risk: float = 0.01
    max_daily_loss: float = 0.02
    max_open_positions: int = 8
    min_dte: int = 21
    max_dte: int = 45
    min_open_interest: int = 500
    max_bid_ask_spread: float = 0.15
    min_credit: float = 0.25
    min_volume: int = 50
    min_ai_score: int = 75
    profit_target_fraction: float = 0.60
    stop_loss_fraction: float = 0.50
    exit_before_expiry_dte: int = 7
    request_timeout_seconds: float = 15.0
    data_feed: str = "iex"
    watchlist: list[str] = Field(default_factory=lambda: ["AAPL", "MSFT", "SPY"])

    spread_width: float = 5.0
    target_short_delta_min: float = 0.10
    target_short_delta_max: float = 0.30

    score_weight_regime: int = 20
    score_weight_trend: int = 20
    score_weight_volatility: int = 15
    score_weight_liquidity: int = 15
    score_weight_strike: int = 15
    score_weight_reward: int = 15

    ai_provider: str = "none"
    anthropic_api_key: str = Field(default="", repr=False)
    ai_model: str = "claude-sonnet-5"
    featherless_api_key: str = Field(default="", repr=False)
    featherless_base_url: str = "https://api.featherless.ai/v1"

    @field_validator("max_portfolio_risk", "max_position_risk", "max_daily_loss")
    @classmethod
    def validate_risk_fraction(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError("risk values must be greater than 0 and at most 1")
        return value

    @field_validator("max_bid_ask_spread")
    @classmethod
    def validate_spread(cls, value: float) -> float:
        if value < 0:
            raise ValueError("max bid/ask spread cannot be negative")
        return value

    @field_validator("request_timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("request timeout must be greater than zero")
        return value

    @field_validator("watchlist", mode="before")
    @classmethod
    def parse_watchlist(cls, value: object) -> list[str]:
        if isinstance(value, str):
            return [symbol.strip().upper() for symbol in value.split(",") if symbol.strip()]
        return value  # type: ignore[return-value]

    @field_validator("score_weight_reward")
    @classmethod
    def validate_score_weights(cls, value: int, info: object) -> int:
        # Runs last because pydantic validates fields in declaration order and
        # this one is declared last, so `info.data` already has every other
        # score_weight_* field. Naming each one explicitly (rather than looping
        # over a registered list) means adding a new score_weight_* field
        # requires updating this validator too, or the new weight is silently
        # excluded from the sum-to-100 check.
        data = info.data  # type: ignore[attr-defined]
        total = (
            data.get("score_weight_regime", 0)
            + data.get("score_weight_trend", 0)
            + data.get("score_weight_volatility", 0)
            + data.get("score_weight_liquidity", 0)
            + data.get("score_weight_strike", 0)
            + value
        )
        if total != 100:
            raise ValueError(f"score weights must sum to 100, got {total}")
        return value

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "Settings":
        if env_file:
            load_dotenv(env_file)
        return cls(
            api_key=os.getenv("ALPACA_API_KEY", ""),
            secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
            alpaca_paper=os.getenv("ALPACA_PAPER", "true").lower() == "true",
            paper_trading_only=os.getenv("PAPER_TRADING_ONLY", "true").lower() == "true",
            dry_run=os.getenv("DRY_RUN", "true").lower() == "true",
            max_portfolio_risk=float(os.getenv("MAX_PORTFOLIO_RISK", "0.05")),
            max_position_risk=float(os.getenv("MAX_POSITION_RISK", "0.01")),
            max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "0.02")),
            max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "8")),
            min_dte=int(os.getenv("MIN_DTE", "21")),
            max_dte=int(os.getenv("MAX_DTE", "45")),
            min_open_interest=int(os.getenv("MIN_OPEN_INTEREST", "500")),
            max_bid_ask_spread=float(os.getenv("MAX_BID_ASK_SPREAD", "0.15")),
            min_credit=float(os.getenv("MIN_CREDIT", "0.25")),
            min_volume=int(os.getenv("MIN_VOLUME", "50")),
            min_ai_score=int(os.getenv("MIN_AI_SCORE", "75")),
            profit_target_fraction=float(os.getenv("PROFIT_TARGET_FRACTION", "0.60")),
            stop_loss_fraction=float(os.getenv("STOP_LOSS_FRACTION", "0.50")),
            exit_before_expiry_dte=int(os.getenv("EXIT_BEFORE_EXPIRY_DTE", "7")),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "15")),
            data_feed=os.getenv("ALPACA_DATA_FEED", "iex"),
            watchlist=os.getenv("WATCHLIST", "AAPL,MSFT,SPY"),
            spread_width=float(os.getenv("SPREAD_WIDTH", "5.0")),
            target_short_delta_min=float(os.getenv("TARGET_SHORT_DELTA_MIN", "0.10")),
            target_short_delta_max=float(os.getenv("TARGET_SHORT_DELTA_MAX", "0.30")),
            score_weight_regime=int(os.getenv("SCORE_WEIGHT_REGIME", "20")),
            score_weight_trend=int(os.getenv("SCORE_WEIGHT_TREND", "20")),
            score_weight_volatility=int(os.getenv("SCORE_WEIGHT_VOLATILITY", "15")),
            score_weight_liquidity=int(os.getenv("SCORE_WEIGHT_LIQUIDITY", "15")),
            score_weight_strike=int(os.getenv("SCORE_WEIGHT_STRIKE", "15")),
            score_weight_reward=int(os.getenv("SCORE_WEIGHT_REWARD", "15")),
            ai_provider=os.getenv("AI_PROVIDER", "none"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            ai_model=os.getenv("AI_MODEL", "claude-sonnet-5"),
            featherless_api_key=os.getenv("FEATHERLESS_API_KEY", ""),
            featherless_base_url=os.getenv("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1"),
        )

    def require_paper_mode(self) -> None:
        if not self.paper_trading_only or not self.alpaca_paper:
            raise RuntimeError("Refusing to start: PAPER_TRADING_ONLY and ALPACA_PAPER must be true")

    def require_credentials(self) -> None:
        if not self.api_key or not self.secret_key:
            raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required for API access")
