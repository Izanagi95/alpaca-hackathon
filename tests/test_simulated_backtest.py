import math
import random
from datetime import date, timedelta

from app.backtest.simulated_backtest import BEAR_CALL, BULL_PUT, simulate_symbol
from app.config.settings import Settings


def _dates(n: int, start: date) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def _random_walk_closes(n: int, drift: float, daily_vol: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    price = 100.0
    closes = [price]
    for _ in range(n - 1):
        price *= math.exp(drift + daily_vol * rng.gauss(0, 1))
        closes.append(price)
    return closes


def test_steady_uptrend_produces_trades_with_consistent_equity() -> None:
    # Pinned to the bull-put-only path: this characterises that side of the
    # strategy, and the bear call leg has its own tests below.
    n = 250
    closes = _random_walk_closes(n, drift=0.0015, daily_vol=0.018, seed=42)
    dates = _dates(n, date(2025, 1, 1))
    settings = Settings()

    result = simulate_symbol("TEST", dates, closes, settings, allow_bear_call=False)

    assert len(result.trades) > 0
    total_pnl = sum(t.realized_pnl for t in result.trades)
    assert result.ending_equity == round(result.starting_equity + total_pnl, 2) or abs(
        result.ending_equity - (result.starting_equity + total_pnl)
    ) < 0.01
    for trade in result.trades:
        assert trade.long_strike < trade.short_strike
        assert trade.contracts > 0
        assert trade.exit_date >= trade.entry_date


def test_downtrend_never_holds_past_the_target_expiration() -> None:
    # A persistent downtrend is never itself a valid entry regime (the strategy
    # only enters bullish/neutral-bullish), so any position opened on transient
    # noise must close via profit target, stop loss, time exit or regime exit —
    # never held for its full nominal term untouched.
    n = 250
    closes = _random_walk_closes(n, drift=-0.0015, daily_vol=0.018, seed=42)
    dates = _dates(n, date(2025, 1, 1))
    settings = Settings()
    target_dte = (settings.min_dte + settings.max_dte) // 2

    result = simulate_symbol("TEST", dates, closes, settings, allow_bear_call=False)

    assert len(result.trades) > 0  # noise does open a few positions
    for trade in result.trades:
        assert (trade.exit_date - trade.entry_date).days <= target_dte
        assert trade.exit_reason in {"profit_target", "stop_loss", "time_exit", "regime_exit"}


def test_intraday_data_catches_a_stop_loss_before_a_full_day_gap_would() -> None:
    # A big one-day drop reprices the spread from healthy to a large loss.
    # With only the daily close available, the exit is checked once, after
    # the whole drop has already happened. With intraday bars available, the
    # walk should catch the loss partway through that day (closer to the
    # configured stop threshold, not the full end-of-day magnitude).
    n = 60
    closes = _random_walk_closes(n, drift=0.001, daily_vol=0.01, seed=7)
    drop_day = 30
    closes[drop_day] = closes[drop_day - 1] * 0.85  # a sharp single-day drop
    dates = _dates(n, date(2025, 1, 1))
    settings = Settings()

    without_intraday = simulate_symbol("TEST", dates, closes, settings, allow_bear_call=False)
    intraday_by_date = {
        dates[drop_day]: [
            closes[drop_day - 1] * (1 - fraction * 0.15) for fraction in (0.25, 0.5, 0.75, 1.0)
        ]
    }
    with_intraday = simulate_symbol(
        "TEST", dates, closes, settings, intraday_by_date=intraday_by_date, allow_bear_call=False
    )

    trades_touching_drop_day_without = [t for t in without_intraday.trades if t.entry_date < dates[drop_day] <= t.exit_date]
    trades_touching_drop_day_with = [t for t in with_intraday.trades if t.entry_date < dates[drop_day] <= t.exit_date]
    if trades_touching_drop_day_without and trades_touching_drop_day_with:
        worst_without = min(t.realized_pnl for t in trades_touching_drop_day_without)
        worst_with = min(t.realized_pnl for t in trades_touching_drop_day_with)
        assert worst_with >= worst_without  # intraday catches it no later, so the loss is no worse


def test_downtrend_opens_bear_call_spreads_with_mirrored_geometry() -> None:
    # The bull-put-only path sits out a falling market entirely; with the bear
    # call leg enabled the same tape is tradeable, selling the call above spot
    # and buying the further one for protection.
    n = 250
    closes = _random_walk_closes(n, drift=-0.0015, daily_vol=0.018, seed=42)
    dates = _dates(n, date(2025, 1, 1))
    settings = Settings()

    result = simulate_symbol("TEST", dates, closes, settings, allow_bear_call=True)

    bear_calls = [t for t in result.trades if t.strategy == BEAR_CALL]
    assert bear_calls, "a sustained downtrend should produce bear call spreads"
    for trade in bear_calls:
        assert trade.long_strike > trade.short_strike  # mirror of the bull put
        assert trade.entry_credit > 0  # a credit spread must bring money in
        assert trade.contracts > 0


def test_enabling_bear_calls_only_adds_trades_never_removes_bull_puts() -> None:
    n = 250
    closes = _random_walk_closes(n, drift=-0.0005, daily_vol=0.02, seed=11)
    dates = _dates(n, date(2025, 1, 1))
    settings = Settings()

    puts_only = simulate_symbol("TEST", dates, closes, settings, allow_bear_call=False)
    both = simulate_symbol("TEST", dates, closes, settings, allow_bear_call=True)

    assert all(t.strategy == BULL_PUT for t in puts_only.trades)
    assert len(both.trades) >= len(puts_only.trades)


def test_every_trade_has_a_credit_and_coherent_strike_order() -> None:
    n = 250
    closes = _random_walk_closes(n, drift=0.0005, daily_vol=0.02, seed=3)
    dates = _dates(n, date(2025, 1, 1))

    result = simulate_symbol("TEST", dates, closes, Settings(), allow_bear_call=True)

    assert result.trades
    for trade in result.trades:
        assert trade.entry_credit > 0
        if trade.strategy == BEAR_CALL:
            assert trade.long_strike > trade.short_strike
        else:
            assert trade.long_strike < trade.short_strike


def test_mismatched_lengths_raise() -> None:
    import pytest

    with pytest.raises(ValueError):
        simulate_symbol("TEST", [date(2025, 1, 1)], [100.0, 101.0], Settings())
