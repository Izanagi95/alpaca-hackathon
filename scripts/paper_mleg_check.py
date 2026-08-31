from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agents.ai_decision import AIDecisionLayer
from app.alpaca.client import AlpacaClients
from app.alpaca.market_data import MarketDataService
from app.alpaca.options import OptionsDataService
from app.config.settings import Settings
from app.database.repository import DecisionRepository
from app.execution.order_manager import OrderManager
from app.risk.risk_engine import RiskContext, RiskEngine
from app.strategy.bull_put_spread import BullPutSpreadCandidate


def main() -> int:
    settings = Settings.from_env(PROJECT_ROOT / ".env")
    settings.require_paper_mode()
    settings.require_credentials()
    clients = AlpacaClients(settings)
    account = clients.verify_account()
    symbol = "SPY"
    stock_quotes = MarketDataService(clients).latest_quotes([symbol])
    stock_quote = getattr(stock_quotes, "quotes", stock_quotes)[symbol]
    underlying_price = float(stock_quote.ask_price or stock_quote.bid_price)

    options = OptionsDataService(clients)
    contracts_response = options.contracts(
        [symbol], date.today() + timedelta(days=settings.min_dte), date.today() + timedelta(days=settings.max_dte)
    )
    contracts = [contract for contract in getattr(contracts_response, "option_contracts", contracts_response) if contract.tradable]
    by_expiration: dict[date, dict[float, object]] = {}
    for contract in contracts:
        by_expiration.setdefault(contract.expiration_date, {})[float(contract.strike_price)] = contract

    pair = None
    for expiration, strikes in sorted(by_expiration.items()):
        short_strikes = sorted(strike for strike in strikes if strike < underlying_price * 0.98)
        for short_strike in reversed(short_strikes):
            long_contract = strikes.get(short_strike - 5)
            if long_contract is not None:
                pair = (strikes[short_strike], long_contract)
                break
        if pair:
            break
    if pair is None:
        raise RuntimeError("Could not find a 5-point defined-risk put spread")

    short_contract, long_contract = pair
    option_quotes = options.latest_quotes([short_contract.symbol, long_contract.symbol])
    quotes = getattr(option_quotes, "quotes", option_quotes)
    short_quote = quotes[short_contract.symbol]
    long_quote = quotes[long_contract.symbol]
    short_bid, short_ask = float(short_quote.bid_price), float(short_quote.ask_price)
    long_bid, long_ask = float(long_quote.bid_price), float(long_quote.ask_price)
    candidate = BullPutSpreadCandidate(
        symbol=symbol,
        expiration=short_contract.expiration_date,
        underlying_price=underlying_price,
        short_strike=float(short_contract.strike_price),
        long_strike=float(long_contract.strike_price),
        short_delta=-0.18,
        short_bid=short_bid,
        short_ask=short_ask,
        long_bid=long_bid,
        long_ask=long_ask,
        short_open_interest=int(short_contract.open_interest or 0),
        long_open_interest=int(long_contract.open_interest or 0),
        short_volume=min(int(short_quote.bid_size), int(short_quote.ask_size)),
        long_volume=min(int(long_quote.bid_size), int(long_quote.ask_size)),
        market_regime="bullish",
        trend="bullish",
        realized_volatility=0,
        implied_volatility=0,
    )
    if candidate.midpoint_credit <= 0:
        raise RuntimeError("Selected spread has no positive credit")

    proposal = AIDecisionLayer(lambda _: {
        "decision": "APPROVE", "score": 80, "strategy": "bull_put_spread",
        "confidence": 0.80, "rationale": ["paper mleg integration verification"], "risk_flags": [],
    }).analyze(candidate)
    risk = RiskEngine(settings).evaluate(candidate, RiskContext(float(account.equity), 0, 0), proposal.score)
    journal = DecisionRepository(settings.database_url or PROJECT_ROOT / "riskgate.db")
    try:
        journal.record(candidate, proposal, risk)
        if not risk.approved:
            raise RuntimeError(f"Risk rejected selected spread: {risk.reasons}")
        result = OrderManager(settings, clients).submit_bull_put_spread(candidate, risk)
        if result.dry_run:
            print(f"PAPER MLEG DRY RUN order_id=none contracts={risk.contracts}")
        else:
            print(f"PAPER MLEG SUBMITTED order_id={getattr(result.order, 'id', result.order)} contracts={risk.contracts}")
        return 0
    finally:
        journal.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"PAPER MLEG CHECK FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from error
