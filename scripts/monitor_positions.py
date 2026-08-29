"""Position monitoring loop: evaluates exit rules for every open trade and,
when a rule fires, submits the closing multi-leg order and journals the
realized P&L. Connects Phase 6 (PositionManager) to the trade journal, which
was previously implemented but never wired into an executable path.

Run repeatedly (e.g. from a scheduler) with:

    .\\.venv\\Scripts\\python.exe scripts\\monitor_positions.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.alpaca.client import AlpacaClients
from app.alpaca.options import OptionsDataService
from app.config.settings import Settings
from app.database.repository import DecisionRepository
from app.execution.order_manager import OrderManager
from app.execution.position_manager import ManagedPosition, PositionManager
from app.strategy.bull_put_spread import BullPutSpreadCandidate


def _leg_symbol(symbol: str, expiration: date, strike: float) -> str:
    return f"{symbol}{expiration:%y%m%d}P{int(strike * 1000):08d}"


def _current_debit(options_data: OptionsDataService, symbol: str, expiration: date, short_strike: float, long_strike: float) -> float:
    short_symbol = _leg_symbol(symbol, expiration, short_strike)
    long_symbol = _leg_symbol(symbol, expiration, long_strike)
    quotes = options_data.latest_quotes([short_symbol, long_symbol])
    short_quote = quotes[short_symbol]
    long_quote = quotes[long_symbol]
    short_mid = (short_quote.bid_price + short_quote.ask_price) / 2
    long_mid = (long_quote.bid_price + long_quote.ask_price) / 2
    return round(short_mid - long_mid, 4)


def main() -> int:
    settings = Settings.from_env(PROJECT_ROOT / ".env")
    settings.require_paper_mode()

    journal = DecisionRepository(settings.database_url or PROJECT_ROOT / "options_alpha.db")
    position_manager = PositionManager(settings)
    clients = None
    if not settings.dry_run:
        settings.require_credentials()
        clients = AlpacaClients(settings)
    order_manager = OrderManager(settings, clients)
    options_data = OptionsDataService(clients) if clients else None

    open_trades = journal.list_open_trades()
    print(f"MONITOR START open_trades={len(open_trades)}")

    for trade in open_trades:
        expiration = date.fromisoformat(str(trade["expiration"]))
        dte = (expiration - date.today()).days

        try:
            current_debit = (
                _current_debit(options_data, str(trade["symbol"]), expiration, float(trade["short_strike"]), float(trade["long_strike"]))
                if options_data is not None
                else float(trade["entry_credit"])  # dry-run fallback: no live quote source
            )
        except Exception as error:  # fail closed: never guess a fill price
            print(f"SKIP trade_id={trade['id']} reason=quote_unavailable error={error}")
            continue

        position = ManagedPosition(
            symbol=str(trade["symbol"]),
            contracts=int(trade["contracts"]),
            entry_credit=float(trade["entry_credit"]),
            current_debit=current_debit,
            max_profit=float(trade["max_profit"]),
            max_loss=float(trade["max_loss"]),
            dte=dte,
            market_regime="BULLISH",  # regime re-check requires a fresh Market Analyst run; see README limitation
        )
        exit_decision = position_manager.evaluate_exit(position)
        if not exit_decision.should_exit:
            print(f"HOLD trade_id={trade['id']} symbol={trade['symbol']} pnl={exit_decision.current_pnl}")
            continue

        candidate = BullPutSpreadCandidate(
            symbol=str(trade["symbol"]), expiration=expiration, underlying_price=1,
            short_strike=float(trade["short_strike"]), long_strike=float(trade["long_strike"]),
            short_delta=-0.01, short_bid=0, short_ask=0, long_bid=0, long_ask=0,
            short_open_interest=0, long_open_interest=0, short_volume=0, long_volume=0,
            market_regime="bullish", trend="bullish", realized_volatility=0, implied_volatility=0,
        )
        execution = order_manager.close_bull_put_spread(candidate, position, exit_decision)
        journal.record_trade_close(int(trade["id"]), exit_decision, execution)
        print(f"EXIT trade_id={trade['id']} reason={exit_decision.reason} pnl={exit_decision.current_pnl} submitted={execution.submitted}")

    journal.close()
    print(f"MONITOR DONE at={datetime.utcnow().isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
