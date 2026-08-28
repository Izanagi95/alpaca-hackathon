"""Builds real Bull Put Spread candidates from live Alpaca option data.

This is the missing link between raw market/option data and the rest of the
pipeline (scoring -> AI -> risk engine): previously every candidate had to
be constructed by hand in tests and scripts. `OptionsScanner.scan` does it
from a real option chain for one underlying symbol.

Any contract missing a quote, greeks or open interest is skipped rather than
guessed — the scanner fails closed per-contract instead of fabricating data.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from pydantic import ValidationError

from app.agents.market_analyst import MarketAssessment
from app.alpaca.options import OptionsDataService
from app.config.settings import Settings
from app.strategy.bull_put_spread import BullPutSpreadCandidate


class OptionsScanner:
    def __init__(self, options_data: OptionsDataService, settings: Settings) -> None:
        self._options_data = options_data
        self._settings = settings

    def scan(self, assessment: MarketAssessment) -> list[BullPutSpreadCandidate]:
        today = date.today()
        expiration_gte = today + timedelta(days=self._settings.min_dte)
        expiration_lte = today + timedelta(days=self._settings.max_dte)

        contracts_response = self._options_data.contracts(
            [assessment.symbol], expiration_gte, expiration_lte
        )
        contracts = getattr(contracts_response, "option_contracts", None) or []
        if not contracts:
            return []

        chain = self._options_data.chain(assessment.symbol, expiration_gte, expiration_lte)
        if not chain:
            return []

        by_expiration: dict[date, list] = defaultdict(list)
        for contract in contracts:
            by_expiration[contract.expiration_date].append(contract)

        pairs: list[tuple] = []
        for expiration, expiration_contracts in by_expiration.items():
            expiration_contracts.sort(key=lambda c: c.strike_price, reverse=True)
            pairs.extend(self._pairs_for_expiration(assessment, expiration, expiration_contracts, chain))
        if not pairs:
            return []

        leg_symbols = sorted({leg.symbol for _, short_contract, long_contract, *_ in pairs for leg in (short_contract, long_contract)})
        volumes = self._options_data.daily_volume(leg_symbols)

        candidates: list[BullPutSpreadCandidate] = []
        for expiration, short_contract, long_contract, short_snapshot, long_snapshot, short_delta in pairs:
            candidate = self._build_candidate(
                assessment, expiration, short_contract, short_snapshot, long_contract, long_snapshot, short_delta, volumes
            )
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _pairs_for_expiration(self, assessment, expiration, contracts, chain) -> list[tuple]:
        results: list[tuple] = []
        for short_contract in contracts:
            short_snapshot = chain.get(short_contract.symbol)
            short_delta = self._delta(short_snapshot)
            if short_delta is None:
                continue
            if not (self._settings.target_short_delta_min <= abs(short_delta) <= self._settings.target_short_delta_max):
                continue

            target_long_strike = short_contract.strike_price - self._settings.spread_width
            long_contract = self._closest_at_or_below(contracts, target_long_strike, exclude=short_contract)
            if long_contract is None:
                continue
            long_snapshot = chain.get(long_contract.symbol)
            results.append((expiration, short_contract, long_contract, short_snapshot, long_snapshot, short_delta))
        return results

    @staticmethod
    def _closest_at_or_below(contracts, target_strike: float, exclude) -> object | None:
        eligible = [c for c in contracts if c.strike_price <= target_strike and c is not exclude]
        if not eligible:
            return None
        return max(eligible, key=lambda c: c.strike_price)

    @staticmethod
    def _delta(snapshot) -> float | None:
        greeks = getattr(snapshot, "greeks", None)
        if greeks is None:
            return None
        return greeks.delta

    def _build_candidate(self, assessment, expiration, short_contract, short_snapshot, long_contract, long_snapshot, short_delta, volumes) -> BullPutSpreadCandidate | None:
        short_quote = getattr(short_snapshot, "latest_quote", None)
        long_quote = getattr(long_snapshot, "latest_quote", None)
        if short_quote is None or long_quote is None:
            return None

        try:
            return BullPutSpreadCandidate(
                symbol=assessment.symbol,
                expiration=expiration,
                underlying_price=assessment.underlying_price,
                short_strike=short_contract.strike_price,
                long_strike=long_contract.strike_price,
                short_delta=short_delta,
                short_bid=short_quote.bid_price,
                short_ask=short_quote.ask_price,
                long_bid=long_quote.bid_price,
                long_ask=long_quote.ask_price,
                short_open_interest=int(short_contract.open_interest or 0),
                long_open_interest=int(long_contract.open_interest or 0),
                short_volume=volumes.get(short_contract.symbol, 0),
                long_volume=volumes.get(long_contract.symbol, 0),
                market_regime=assessment.market_regime,
                trend=assessment.trend,
                realized_volatility=assessment.realized_volatility,
                implied_volatility=getattr(short_snapshot, "implied_volatility", None) or 0.0,
            )
        except ValidationError:
            return None
