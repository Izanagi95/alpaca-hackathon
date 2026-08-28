from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.alpaca.client import AlpacaClients
from app.alpaca.market_data import MarketDataService
from app.alpaca.options import OptionsDataService
from app.config.settings import Settings


def main() -> int:
    settings = Settings.from_env(PROJECT_ROOT / ".env")
    settings.require_paper_mode()
    settings.require_credentials()

    clients = AlpacaClients(settings)
    account = clients.verify_account()
    print(f"ACCOUNT OK status={account.status}")
    print(f"PAPER TRADING MODE equity={account.equity} buying_power={account.buying_power}")

    market_data = MarketDataService(clients)
    quotes = market_data.latest_quotes(settings.watchlist)
    quote_count = len(getattr(quotes, "quotes", quotes))
    if quote_count == 0:
        raise RuntimeError("No stock quotes returned")
    print(f"STOCK DATA OK symbols={quote_count}")

    today = date.today()
    options_data = OptionsDataService(clients)
    contracts = options_data.contracts(
        settings.watchlist,
        today + timedelta(days=settings.min_dte),
        today + timedelta(days=settings.max_dte),
    )
    contract_items = getattr(contracts, "option_contracts", contracts)
    contract_count = len(contract_items)
    if contract_count == 0:
        raise RuntimeError("No option contracts returned; verify options access and market data availability")
    print(f"OPTIONS CONTRACTS OK contracts={contract_count}")

    symbols = [getattr(contract, "symbol", None) for contract in contract_items[:10]]
    symbols = [symbol for symbol in symbols if symbol]
    option_quotes = options_data.latest_quotes(symbols)
    option_quote_count = len(getattr(option_quotes, "quotes", option_quotes))
    if option_quote_count == 0:
        raise RuntimeError("No option quotes returned")
    print(f"OPTIONS QUOTES OK symbols={option_quote_count}")
    print("READ-ONLY INTEGRATION CHECK PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"INTEGRATION CHECK FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from error
