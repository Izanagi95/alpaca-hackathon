"""A THEORETICAL, simulated backtest — not a validated historical
performance result.

Alpaca's available historical options data does not go back far enough (nor
carry reconstructable historical bid/ask, open interest or IV) to replay
what this strategy would actually have done on real historical option
quotes. Rather than fake that with invented numbers, this module instead:

  1. Uses REAL historical stock closing prices (Alpaca daily bars).
  2. Reconstructs a THEORETICAL option price at each point in time with the
     Black-Scholes model, using realized volatility computed from a
     strictly causal, backward-looking window (never data from the future
     relative to the simulated "current day" — no look-ahead bias).
  3. Reuses the actual production code for position sizing
     (`calculate_contracts`) and exit rules (`PositionManager.evaluate_exit`)
     so this at least validates the mechanics, not a re-implementation of
     them.

What this does NOT validate: real historical liquidity (open interest,
volume, bid/ask spread), a real historical implied volatility surface, or
the AI Analyst's judgment (no LLM is called here). Treat the result as a
sanity check on the rule logic, never as expected real-world performance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.backtest.black_scholes import call_delta, call_price, put_delta, put_price
from app.config.settings import Settings
from app.execution.position_manager import (
    BEARISH_REGIMES,
    BULLISH_REGIMES,
    ExitReason,
    ManagedPosition,
    PositionManager,
)
from app.strategy.position_sizing import calculate_contracts

TRADING_DAYS_PER_YEAR = 252
_STRIKE_STEP_FRACTION = 0.01  # grid search step, as a fraction of spot price

BULL_PUT = "bull_put_spread"
BEAR_CALL = "bear_call_spread"


@dataclass(frozen=True)
class SimulatedTrade:
    symbol: str
    entry_date: date
    exit_date: date
    short_strike: float
    long_strike: float
    contracts: int
    entry_credit: float
    exit_reason: str
    realized_pnl: float
    strategy: str = BULL_PUT


def _spread_debit(strategy: str, spot: float, short_strike: float, long_strike: float, time_to_expiry: float, volatility: float) -> float:
    """What it costs to buy the spread back: short leg's price minus long
    leg's, priced with the option type the spread is actually made of."""
    price = call_price if strategy == BEAR_CALL else put_price
    return price(spot, short_strike, time_to_expiry, volatility) - price(spot, long_strike, time_to_expiry, volatility)


def _settlement_debit(strategy: str, spot: float, short_strike: float, long_strike: float) -> float:
    if strategy == BEAR_CALL:
        return max(spot - short_strike, 0.0) - max(spot - long_strike, 0.0)
    return max(short_strike - spot, 0.0) - max(long_strike - spot, 0.0)


@dataclass
class BacktestResult:
    symbol: str
    trades: list[SimulatedTrade] = field(default_factory=list)
    equity_curve: list[tuple[date, float]] = field(default_factory=list)
    starting_equity: float = 0.0
    ending_equity: float = 0.0


def _realized_volatility(closes: list[float]) -> float:
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _regime(closes: list[float]) -> str:
    short_ma = sum(closes[-10:]) / 10
    long_ma = sum(closes[-20:]) / 20
    if short_ma > long_ma * 1.01:
        return "BULLISH"
    if short_ma < long_ma * 0.99:
        return "BEARISH"
    return "NEUTRAL-BULLISH" if short_ma >= long_ma else "NEUTRAL-BEARISH"


def _find_short_strike(spot: float, time_to_expiry_years: float, volatility: float, settings: Settings, strategy: str = BULL_PUT) -> float | None:
    """The short strike sits out of the money on the side the spread is
    betting against: below spot for a bull put, above it for a bear call."""
    target_delta = (settings.target_short_delta_min + settings.target_short_delta_max) / 2
    step = max(spot * _STRIKE_STEP_FRACTION, 0.5)
    best_strike, best_diff = None, float("inf")

    if strategy == BEAR_CALL:
        strike, limit, delta_of = spot + step, spot * 1.5, call_delta
    else:
        strike, limit, delta_of = spot * 0.5, spot, put_delta

    while strike < limit:
        delta = delta_of(spot, strike, time_to_expiry_years, volatility)
        diff = abs(abs(delta) - target_delta)
        if diff < best_diff:
            best_strike, best_diff = strike, diff
        strike += step
    return best_strike


def simulate_symbol(
    symbol: str, dates: list[date], closes: list[float], settings: Settings,
    starting_equity: float = 100_000.0, intraday_by_date: dict[date, list[float]] | None = None,
    allow_bear_call: bool = True,
) -> BacktestResult:
    """intraday_by_date, when given, maps each trading date to its sequence of
    real intraday close prices (e.g. 5-minute bars). Exit rules are then
    checked against every intraday price, matching the live agent's polling
    cadence, instead of only once per day at the close — a single day's worth
    of intraday data missing simply falls back to that day's daily close."""
    if len(dates) != len(closes):
        raise ValueError("dates and closes must be the same length")

    result = BacktestResult(symbol=symbol, starting_equity=starting_equity, ending_equity=starting_equity)
    position_manager = PositionManager(settings)
    equity = starting_equity
    target_dte = (settings.min_dte + settings.max_dte) // 2
    warmup = 20

    i = warmup
    while i < len(closes):
        window = closes[max(0, i - warmup) : i + 1]
        regime = _regime(window)
        volatility = _realized_volatility(window)
        entry_date = dates[i]
        expiration_date = entry_date + timedelta(days=target_dte)

        # Trade with the detected regime rather than only in bullish tape:
        # a bull put spread when the market is rising, its mirror image when
        # it is falling. Previously every bearish day was simply skipped.
        if regime in BULLISH_REGIMES:
            strategy = BULL_PUT
        elif allow_bear_call and regime in BEARISH_REGIMES:
            strategy = BEAR_CALL
        else:
            i += 1
            continue
        if volatility <= 0:
            i += 1
            continue

        spot = closes[i]
        time_to_expiry = target_dte / 365
        short_strike = _find_short_strike(spot, time_to_expiry, volatility, settings, strategy)
        if short_strike is None:
            i += 1
            continue
        long_strike = short_strike + settings.spread_width if strategy == BEAR_CALL else short_strike - settings.spread_width
        if long_strike <= 0:
            i += 1
            continue

        entry_credit = _spread_debit(strategy, spot, short_strike, long_strike, time_to_expiry, volatility)
        if entry_credit < settings.min_credit:
            i += 1
            continue

        max_loss_per_contract = (settings.spread_width - entry_credit) * 100
        if max_loss_per_contract <= 0:
            i += 1
            continue
        contracts = calculate_contracts(equity, max_loss_per_contract, settings.max_position_risk)
        if contracts <= 0:
            i += 1
            continue

        exit_index, exit_reason, exit_pnl = _walk_position(
            dates, closes, i, expiration_date, short_strike, long_strike,
            entry_credit, contracts, volatility, settings, position_manager,
            intraday_by_date, strategy,
        )

        equity += exit_pnl
        result.trades.append(
            SimulatedTrade(
                symbol=symbol, entry_date=entry_date, exit_date=dates[exit_index],
                short_strike=short_strike, long_strike=long_strike, contracts=contracts,
                entry_credit=round(entry_credit, 4), exit_reason=exit_reason, realized_pnl=round(exit_pnl, 2),
                strategy=strategy,
            )
        )
        result.equity_curve.append((dates[exit_index], round(equity, 2)))
        i = exit_index + 1

    result.ending_equity = equity
    return result


def _walk_position(
    dates: list[date], closes: list[float], entry_index: int, expiration_date: date,
    short_strike: float, long_strike: float, entry_credit: float, contracts: int,
    volatility: float, settings: Settings, position_manager: PositionManager,
    intraday_by_date: dict[date, list[float]] | None = None, strategy: str = BULL_PUT,
) -> tuple[int, str, float]:
    max_loss = (settings.spread_width - entry_credit) * 100
    max_profit = entry_credit * 100
    intraday_by_date = intraday_by_date or {}

    j = entry_index + 1
    while j < len(dates):
        remaining_days = (expiration_date - dates[j]).days
        if remaining_days <= 0:
            break

        time_to_expiry = remaining_days / 365
        window = closes[max(0, j - 20) : j + 1]
        regime_today = _regime(window)
        # Time decay barely moves within a single day, so time_to_expiry is held
        # fixed for the day while spot walks through every intraday price —
        # this is what actually fixes the gap-risk exaggeration: a stop-loss
        # crossed mid-day is caught then, not only once at the day's close.
        intraday_spots = intraday_by_date.get(dates[j]) or [closes[j]]

        for spot in intraday_spots:
            current_debit = _spread_debit(strategy, spot, short_strike, long_strike, time_to_expiry, volatility)
            position = ManagedPosition(
                symbol="", contracts=contracts, entry_credit=entry_credit, current_debit=current_debit,
                max_profit=max_profit, max_loss=max_loss, dte=remaining_days, market_regime=regime_today,
                strategy=strategy,
            )
            exit_decision = position_manager.evaluate_exit(position)
            if exit_decision.should_exit:
                return j, exit_decision.reason.value, exit_decision.current_pnl
        j += 1

    settle_index = min(j, len(dates) - 1)
    settle_debit = _settlement_debit(strategy, closes[settle_index], short_strike, long_strike)
    settle_pnl = round((entry_credit - settle_debit) * 100 * contracts, 2)
    return settle_index, ExitReason.TIME_EXIT.value, settle_pnl
