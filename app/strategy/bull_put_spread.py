from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, computed_field, field_validator


class BullPutSpreadCandidate(BaseModel):
    symbol: str
    expiration: date
    underlying_price: float = Field(gt=0)
    short_strike: float = Field(gt=0)
    long_strike: float = Field(gt=0)
    short_delta: float
    short_bid: float = Field(ge=0)
    short_ask: float = Field(ge=0)
    long_bid: float = Field(ge=0)
    long_ask: float = Field(ge=0)
    short_open_interest: int = Field(ge=0)
    long_open_interest: int = Field(ge=0)
    short_volume: int = Field(ge=0)
    long_volume: int = Field(ge=0)
    market_regime: str
    trend: str
    realized_volatility: float = Field(ge=0)
    implied_volatility: float = Field(ge=0)

    @field_validator("symbol", "market_regime", "trend")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("long_strike")
    @classmethod
    def validate_strikes(cls, value: float, info: object) -> float:
        short_strike = info.data.get("short_strike")  # type: ignore[attr-defined]
        if short_strike is not None and value >= short_strike:
            raise ValueError("long strike must be below short strike")
        return value

    @computed_field
    @property
    def dte(self) -> int:
        return (self.expiration - date.today()).days

    @computed_field
    @property
    def spread_width(self) -> float:
        return self.short_strike - self.long_strike

    @computed_field
    @property
    def midpoint_credit(self) -> float:
        return ((self.short_bid + self.short_ask) / 2) - ((self.long_bid + self.long_ask) / 2)

    @computed_field
    @property
    def max_loss_per_contract(self) -> float:
        return (self.spread_width - self.midpoint_credit) * 100

    @computed_field
    @property
    def bid_ask_spread(self) -> float:
        return max(self.short_ask - self.short_bid, self.long_ask - self.long_bid)
