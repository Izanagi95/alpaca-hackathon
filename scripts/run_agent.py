"""The autonomous agent loop: scans the configured watchlist with live Alpaca
data, builds real Bull Put Spread candidates, scores them, asks the AI
Analyst for a proposal, and runs every candidate through the deterministic
Risk Engine and TradeWorkflow. This is what previously had to be done by
hand for a single candidate in tests/scripts.

Run with `DRY_RUN=true` (the default) to see what the agent would do without
submitting anything:

    .\\.venv\\Scripts\\python.exe scripts\\run_agent.py
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agents.ai_decision import AIDecisionLayer
from app.agents.market_analyst import MarketAnalyst
from app.agents.options_scanner import OptionsScanner
from app.agents.workflow import TradeWorkflow
from app.alpaca.client import AlpacaClients
from app.alpaca.market_data import MarketDataService
from app.alpaca.options import OptionsDataService
from app.config.settings import Settings
from app.database.repository import DecisionRepository
from app.execution.order_manager import OrderManager
from app.risk.risk_engine import RiskContext, RiskEngine
from app.strategy.scoring import score_candidate


def _no_ai_provider(_: dict) -> dict:
    raise RuntimeError(
        "AI_PROVIDER is 'none'; set AI_PROVIDER=anthropic (with ANTHROPIC_API_KEY) or "
        "AI_PROVIDER=featherless (with FEATHERLESS_API_KEY and AI_MODEL)"
    )


def _build_ai_provider(settings: Settings):
    if settings.ai_provider == "anthropic":
        from app.agents.ai_provider import build_anthropic_provider

        return build_anthropic_provider(settings)
    if settings.ai_provider == "featherless":
        from app.agents.ai_provider import build_featherless_provider

        return build_featherless_provider(settings)
    return _no_ai_provider


def _risk_context(clients: AlpacaClients, journal: DecisionRepository, settings: Settings) -> RiskContext:
    account = clients.verify_account()
    equity = float(account.equity)
    last_equity = float(account.last_equity) if account.last_equity else equity
    daily_pnl_fraction = (equity - last_equity) / last_equity if last_equity else 0.0

    open_trades = journal.list_open_trades()
    open_symbols = frozenset(str(trade["symbol"]) for trade in open_trades)
    portfolio_risk_used = sum(
        float(trade["max_loss"]) * int(trade["contracts"]) for trade in open_trades
    ) / equity if equity else 0.0

    return RiskContext(
        equity=equity,
        daily_pnl_fraction=daily_pnl_fraction,
        open_positions=len(open_trades),
        open_symbols=open_symbols,
        portfolio_risk_used=portfolio_risk_used,
    )


def main() -> int:
    settings = Settings.from_env(PROJECT_ROOT / ".env")
    settings.require_paper_mode()
    settings.require_credentials()

    clients = AlpacaClients(settings)
    market_data = MarketDataService(clients)
    options_data = OptionsDataService(clients)
    market_analyst = MarketAnalyst(market_data)
    scanner = OptionsScanner(options_data, settings)

    journal = DecisionRepository(settings.database_url or PROJECT_ROOT / "options_alpha.db")
    ai_layer = AIDecisionLayer(_build_ai_provider(settings))
    order_manager = OrderManager(settings, clients)
    workflow = TradeWorkflow(ai_layer, RiskEngine(settings), order_manager, journal)

    context = _risk_context(clients, journal, settings)
    print(f"AGENT START equity={context.equity} open_positions={context.open_positions} watchlist={settings.watchlist}")

    scanned = approved = rejected = 0
    for symbol in settings.watchlist:
        assessment = market_analyst.assess(symbol)
        if assessment is None:
            print(f"SKIP symbol={symbol} reason=insufficient_price_history")
            continue

        candidates = scanner.scan(assessment)
        print(f"SCAN symbol={symbol} candidates={len(candidates)} regime={assessment.market_regime}")

        for candidate in candidates:
            scanned += 1
            quant_score = score_candidate(candidate, settings)
            print(f"CANDIDATE symbol={symbol} short={candidate.short_strike} long={candidate.long_strike} quant_score={quant_score}")

            result = workflow.evaluate(candidate, context)
            if result.risk_decision.approved:
                approved += 1
                print(f"APPROVED symbol={symbol} contracts={result.risk_decision.contracts} submitted={result.execution.submitted}")
                # Reflect this approval immediately so a second candidate for the
                # same symbol later in this same scan sees it as open exposure —
                # RiskContext is otherwise only computed once, before the loop.
                risk_used = float(candidate.max_loss_per_contract) * result.risk_decision.contracts / context.equity if context.equity else 0.0
                context = dataclasses.replace(
                    context,
                    open_positions=context.open_positions + 1,
                    open_symbols=context.open_symbols | {candidate.symbol},
                    portfolio_risk_used=context.portfolio_risk_used + risk_used,
                )
            else:
                rejected += 1
                print(f"REJECTED symbol={symbol} reasons={result.risk_decision.reasons}")

    journal.close()
    print(f"AGENT DONE scanned={scanned} approved={approved} rejected={rejected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
