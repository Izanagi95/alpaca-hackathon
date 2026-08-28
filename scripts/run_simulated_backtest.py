"""Runs the THEORETICAL simulated backtest (see app/backtest/simulated_backtest.py
for what it does and does not prove) over real historical stock prices for
every symbol in WATCHLIST, and prints a per-symbol and combined summary.

    .\\.venv\\Scripts\\python.exe scripts\\run_simulated_backtest.py [lookback_days]

Requires Alpaca credentials (for historical stock bars only — no options
data, no order submission, no AI calls). Safe to run at any time; it only
reads historical stock prices.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.alpaca.client import AlpacaClients
from app.alpaca.market_data import MarketDataService
from app.backtest.simulated_backtest import simulate_symbol
from app.config.settings import Settings


def _fetch_intraday_by_date(market_data, symbol: str, start) -> dict:
    """Real 5-minute bars, grouped by trading date, so exit rules are checked
    at roughly the same cadence as the live agent's polling loop instead of
    only once per day at the close."""
    bars = market_data.intraday_bars([symbol], start=start, minutes=5)
    data = getattr(bars, "data", bars)
    symbol_bars = data.get(symbol, []) if hasattr(data, "get") else []
    by_date: dict = {}
    for bar in symbol_bars:
        by_date.setdefault(bar.timestamp.date(), []).append(float(bar.close))
    return by_date


def main() -> int:
    lookback_days = int(sys.argv[1]) if len(sys.argv) > 1 else 365

    settings = Settings.from_env(PROJECT_ROOT / ".env")
    settings.require_paper_mode()
    settings.require_credentials()
    clients = AlpacaClients(settings)
    market_data = MarketDataService(clients)

    print("SIMULATED BACKTEST - theoretical (Black-Scholes) reconstruction, NOT a validated")
    print("historical performance result. See app/backtest/simulated_backtest.py docstring.")
    print(f"lookback_days={lookback_days} watchlist={settings.watchlist}\n")

    start = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    total_pnl = 0.0
    total_trades = 0

    for symbol in settings.watchlist:
        bars = market_data.daily_bars([symbol], start=start)
        data = getattr(bars, "data", bars)
        symbol_bars = data.get(symbol, []) if hasattr(data, "get") else []
        if len(symbol_bars) < 40:
            print(f"{symbol}: SKIPPED (insufficient history: {len(symbol_bars)} bars)")
            continue

        dates = [bar.timestamp.date() for bar in symbol_bars]
        closes = [float(bar.close) for bar in symbol_bars]

        intraday_by_date = _fetch_intraday_by_date(market_data, symbol, start)

        result = simulate_symbol(symbol, dates, closes, settings, intraday_by_date=intraday_by_date)

        wins = sum(1 for t in result.trades if t.realized_pnl > 0)
        print(
            f"{symbol}: trades={len(result.trades)} wins={wins} "
            f"pnl={result.ending_equity - result.starting_equity:+.2f} "
            f"(equity {result.starting_equity:.0f} -> {result.ending_equity:.2f})"
        )
        for trade in result.trades:
            print(
                f"  {trade.entry_date} -> {trade.exit_date}  short={trade.short_strike:.1f} "
                f"long={trade.long_strike:.1f} contracts={trade.contracts} "
                f"credit={trade.entry_credit:.2f} exit={trade.exit_reason} pnl={trade.realized_pnl:+.2f}"
            )

        total_pnl += result.ending_equity - result.starting_equity
        total_trades += len(result.trades)

    print(f"\nTOTAL simulated trades={total_trades} combined_pnl={total_pnl:+.2f}")
    print("Reminder: theoretical/simulated only - real liquidity, IV surface and the AI Analyst are not modeled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
