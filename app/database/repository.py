from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlparse, urlunsplit, urlsplit

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    Table,
    Text,
    case,
    create_engine,
    func,
    insert,
    select,
    text,
    update,
)

from app.agents.ai_decision import AIProposal
from app.execution.order_manager import ExecutionResult
from app.execution.position_manager import ExitDecision
from app.risk.risk_engine import RiskDecision
from app.strategy.bull_put_spread import BullPutSpreadCandidate

metadata = MetaData()

decisions_table = Table(
    "decisions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("timestamp", Text, nullable=False),
    Column("symbol", Text, nullable=False),
    Column("market_data", Text, nullable=False),
    Column("options_data", Text, nullable=False),
    Column("ai_decision", Text, nullable=False),
    Column("ai_rationale", Text, nullable=False),
    Column("risk_checks", Text, nullable=False),
    Column("final_decision", Text, nullable=False),
)

trades_table = Table(
    "trades",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("opened_at", Text, nullable=False),
    Column("closed_at", Text),
    Column("symbol", Text, nullable=False),
    Column("strategy", Text, nullable=False),
    Column("expiration", Text, nullable=False),
    Column("short_strike", Float, nullable=False),
    Column("long_strike", Float, nullable=False),
    Column("contracts", Integer, nullable=False),
    Column("entry_credit", Float, nullable=False),
    Column("max_profit", Float, nullable=False),
    Column("max_loss", Float, nullable=False),
    Column("ai_score", Integer, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("client_order_id", Text, nullable=False),
    Column("execution_status", Text, nullable=False),
    Column("exit_reason", Text),
    Column("realized_pnl", Float),
)


def _strip_unsupported_query_params(url: str) -> str:
    """Removes query parameters that libpq/psycopg2 doesn't recognize as
    connection options — e.g. Supabase's `pgbouncer=true`, a hint meant for
    other drivers (asyncpg/Prisma) to disable server-side prepared
    statements, not a real libpq option. psycopg2 raises 'invalid dsn:
    invalid connection option' if it's left in. `options` (used for
    search_path) is preserved untouched."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "pgbouncer"]
    new_query = urlencode(pairs, quote_via=quote)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def _search_path_schema(url: str) -> str | None:
    """Extracts the schema name from a `?options=-c search_path=<schema>`
    query parameter, e.g. Supabase's convention of putting the target
    schema directly in DATABASE_URL rather than hardcoding it in code:
    `postgresql://...?options=-c%20search_path%3Dalpaca`."""
    options = parse_qs(urlparse(url).query).get("options", [None])[0]
    if not options:
        return None
    match = re.search(r"-c\s*search_path=([A-Za-z_][A-Za-z0-9_]*)", options)
    return match.group(1) if match else None


class DecisionRepository:
    """Works against local SQLite (default, used by tests and local dev) or a
    remote Postgres database such as Supabase (pass a `postgresql://...` URL)
    — the same table definitions and queries run against either, via
    SQLAlchemy Core, so GitHub Actions, local development and a hosted
    dashboard can all share one journal instead of juggling a separate
    SQLite file per environment. On Postgres, which schema to use is read
    directly from DATABASE_URL's `options=-c search_path=...` parameter
    (Postgres resolves unqualified table names against it), not hardcoded
    here — only the one-time `CREATE SCHEMA IF NOT EXISTS` bootstrap needs
    to know the name, so it's parsed back out of the same URL.
    """

    def __init__(self, database_url: str | Path = "options_alpha.db") -> None:
        url = str(database_url)
        if "://" not in url:
            url = f"sqlite:///{url}"
        url = _strip_unsupported_query_params(url)
        engine = create_engine(url, future=True)
        if engine.dialect.name.startswith("postgres"):
            schema = _search_path_schema(url)
            if schema:
                with engine.begin() as conn:
                    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        self._engine = engine
        metadata.create_all(self._engine)

    def record(
        self,
        candidate: BullPutSpreadCandidate,
        proposal: AIProposal,
        risk_decision: RiskDecision,
    ) -> None:
        market_data = candidate.model_dump(mode="json", include={"symbol", "underlying_price", "market_regime", "trend", "realized_volatility", "implied_volatility"})
        options_data = candidate.model_dump(mode="json", include={"expiration", "short_strike", "long_strike", "short_delta", "short_bid", "short_ask", "long_bid", "long_ask", "short_open_interest", "long_open_interest", "short_volume", "long_volume"})
        final_decision = "APPROVE" if proposal.decision == "APPROVE" and risk_decision.approved else "REJECT"
        with self._engine.begin() as conn:
            conn.execute(
                insert(decisions_table).values(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    symbol=candidate.symbol,
                    market_data=json.dumps(market_data),
                    options_data=json.dumps(options_data),
                    ai_decision=proposal.model_dump_json(),
                    ai_rationale=json.dumps(proposal.rationale),
                    risk_checks=json.dumps({"checks": risk_decision.checks, "reasons": risk_decision.reasons}),
                    final_decision=final_decision,
                )
            )

    def count(self) -> int:
        with self._engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(decisions_table)).scalar_one())

    def record_trade_open(
        self,
        candidate: BullPutSpreadCandidate,
        proposal: AIProposal,
        risk_decision: RiskDecision,
        execution: ExecutionResult,
    ) -> int | None:
        if not execution.submitted:
            return None
        with self._engine.begin() as conn:
            result = conn.execute(
                insert(trades_table).values(
                    opened_at=datetime.now(timezone.utc).isoformat(),
                    symbol=candidate.symbol,
                    strategy="bull_put_spread",
                    expiration=candidate.expiration.isoformat(),
                    short_strike=candidate.short_strike,
                    long_strike=candidate.long_strike,
                    contracts=risk_decision.contracts,
                    entry_credit=candidate.midpoint_credit,
                    max_profit=round(candidate.midpoint_credit * 100, 2),
                    max_loss=candidate.max_loss_per_contract,
                    ai_score=proposal.score,
                    confidence=proposal.confidence,
                    client_order_id=execution.client_order_id,
                    execution_status="dry_run" if execution.dry_run else "submitted",
                )
            )
            return int(result.inserted_primary_key[0])

    def record_trade_close(
        self,
        trade_id: int,
        exit_decision: ExitDecision,
        execution: ExecutionResult,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(trades_table)
                .where(trades_table.c.id == trade_id)
                .values(
                    closed_at=datetime.now(timezone.utc).isoformat(),
                    exit_reason=exit_decision.reason.value,
                    realized_pnl=exit_decision.current_pnl,
                    execution_status="closed_dry_run" if execution.dry_run else "closed",
                )
            )

    def list_open_trades(self) -> list[dict[str, object]]:
        columns = [
            trades_table.c.id, trades_table.c.opened_at, trades_table.c.symbol, trades_table.c.expiration,
            trades_table.c.short_strike, trades_table.c.long_strike, trades_table.c.contracts,
            trades_table.c.entry_credit, trades_table.c.max_profit, trades_table.c.max_loss,
        ]
        with self._engine.connect() as conn:
            rows = conn.execute(select(*columns).where(trades_table.c.closed_at.is_(None))).all()
        return [dict(row._mapping) for row in rows]

    def list_recent_trades(self, limit: int = 50) -> list[dict[str, object]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(trades_table).order_by(trades_table.c.id.desc()).limit(limit)
            ).all()
        return [dict(row._mapping) for row in rows]

    def list_recent(self, limit: int = 50) -> list[dict[str, object]]:
        columns = [
            decisions_table.c.timestamp, decisions_table.c.symbol,
            decisions_table.c.ai_decision, decisions_table.c.final_decision,
        ]
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(*columns).order_by(decisions_table.c.id.desc()).limit(limit)
            ).all()
        return [dict(row._mapping) for row in rows]

    def daily_decision_counts(self, days: int = 14) -> list[dict[str, object]]:
        """Scanned/approved counts per day (`timestamp`'s first 10 chars, i.e.
        its date — `substr` is standard SQL and works identically on SQLite
        and Postgres, avoiding dialect-specific date functions)."""
        day = func.substr(decisions_table.c.timestamp, 1, 10).label("day")
        approved = func.sum(case((decisions_table.c.final_decision == "APPROVE", 1), else_=0)).label("approved")
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(day, func.count().label("scanned"), approved)
                .group_by(day)
                .order_by(day.desc())
                .limit(days)
            ).all()
        return [dict(row._mapping) for row in rows]

    def daily_trade_pnl(self, days: int = 14) -> list[dict[str, object]]:
        """Closed-trade counts and realized P&L per day (grouped by
        `closed_at`'s date). Only trades that have actually closed are
        included — open positions have no realized P&L yet."""
        day = func.substr(trades_table.c.closed_at, 1, 10).label("day")
        wins = func.sum(case((trades_table.c.realized_pnl > 0, 1), else_=0)).label("wins")
        losses = func.sum(case((trades_table.c.realized_pnl < 0, 1), else_=0)).label("losses")
        pnl = func.sum(trades_table.c.realized_pnl).label("realized_pnl")
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(day, func.count().label("closed"), wins, losses, pnl)
                .where(trades_table.c.closed_at.is_not(None))
                .group_by(day)
                .order_by(day.desc())
                .limit(days)
            ).all()
        return [dict(row._mapping) for row in rows]

    def close(self) -> None:
        self._engine.dispose()
