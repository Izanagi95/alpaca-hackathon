from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
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
    # The closing order's id, kept so a submitted-but-unfilled exit can be
    # followed up on: a trade is only really closed once this order fills.
    Column("close_client_order_id", Text),
)

scan_summary_table = Table(
    "scan_summary",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("timestamp", Text, nullable=False),
    Column("symbol", Text, nullable=False),
    # Rejected candidates no longer get a decisions row each — a single scan
    # commonly rejects 100+ candidates per symbol, almost all before the AI is
    # even asked, and journaling every one of them grew the journal past
    # 700,000 rows for a window that produced about 100 real trades. One row
    # here replaces all of them: how many were rejected, how many of those
    # had passed pre-screening (so the AI was actually asked), and which
    # gates/reasons did the rejecting.
    Column("rejected", Integer, nullable=False),
    Column("rejected_reached_ai", Integer, nullable=False),
    Column("gate_counts", Text, nullable=False),
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


def _pin_psycopg2_driver(url: str) -> str:
    """Rewrites a driver-less `postgresql://` URL to `postgresql+psycopg2://`.

    SQLAlchemy resolves a bare `postgresql://` scheme to whichever DB-API
    driver it currently prefers when none is named — and that preference is
    not a stable contract: SQLAlchemy 2.1 switched it from psycopg2 to
    psycopg (v3), which this project doesn't install, breaking every run with
    `ModuleNotFoundError: No module named 'psycopg'` the day that release
    reached PyPI, with no code change on this side. Naming the driver
    explicitly makes the choice ours, not whatever `create_engine` defaults
    to this week. A URL that already names a driver (e.g. `+psycopg2`,
    `+pg8000`) is left alone.
    """
    # Reconstructing via urlunsplit unconditionally corrupts an
    # authority-less sqlite URL (`sqlite:///file.db` loses a slash on a
    # round trip), so anything that isn't the exact scheme being rewritten
    # is returned untouched rather than rebuilt.
    if urlsplit(url).scheme != "postgresql":
        return url
    parts = urlsplit(url)._replace(scheme="postgresql+psycopg2")
    return urlunsplit(parts)


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


@lru_cache(maxsize=8)
def _build_engine(url: str):
    """Engine construction — including the CREATE SCHEMA/create_all bootstrap,
    each a network round trip on Postgres — is expensive enough that doing it
    on every DecisionRepository(...) call (e.g. once per web request) made
    every page load noticeably slow. Cached per URL so it only happens once
    per process; the connection pool underneath is then reused across
    requests instead of reconnecting every time."""
    engine = create_engine(url, future=True)
    if engine.dialect.name.startswith("postgres"):
        schema = _search_path_schema(url)
        if schema:
            with engine.begin() as conn:
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    metadata.create_all(engine)
    if engine.dialect.name.startswith("postgres"):
        # create_all only creates missing tables, never adds a column to a
        # table that already exists — so a journal written before
        # close_client_order_id existed needs it added explicitly.
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN IF NOT EXISTS close_client_order_id TEXT"))
    return engine


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

    def __init__(self, database_url: str | Path = "riskgate.db") -> None:
        url = str(database_url)
        if "://" not in url:
            url = f"sqlite:///{url}"
        url = _strip_unsupported_query_params(url)
        url = _pin_psycopg2_driver(url)
        self._engine = _build_engine(url)

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

    def record_scan_summary(
        self, symbol: str, rejected: int, rejected_reached_ai: int, gate_counts: dict[str, int],
    ) -> None:
        """Replaces one decisions row per rejected candidate with one row per
        symbol per scan — see scan_summary_table for why."""
        if rejected <= 0:
            return
        with self._engine.begin() as conn:
            conn.execute(
                insert(scan_summary_table).values(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    symbol=symbol,
                    rejected=rejected,
                    rejected_reached_ai=rejected_reached_ai,
                    gate_counts=json.dumps(gate_counts),
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
        """A live close order is only *submitted* here, not filled — leaving
        closed_at unset keeps the trade in list_open_trades() so the monitor
        follows it until the exit actually fills. Marking it closed on submit
        instead stranded real positions at the broker with nothing watching
        them. A dry run has no order to wait for, so it closes immediately."""
        if execution.dry_run:
            values = {
                "closed_at": datetime.now(timezone.utc).isoformat(),
                "exit_reason": exit_decision.reason.value,
                "realized_pnl": exit_decision.current_pnl,
                "execution_status": "closed_dry_run",
            }
        else:
            values = {
                "exit_reason": exit_decision.reason.value,
                "realized_pnl": exit_decision.current_pnl,
                "execution_status": "closing",
                "close_client_order_id": execution.client_order_id,
            }
        with self._engine.begin() as conn:
            conn.execute(update(trades_table).where(trades_table.c.id == trade_id).values(**values))

    def record_trade_close_filled(self, trade_id: int) -> None:
        """Finalises a trade whose closing order has actually filled."""
        with self._engine.begin() as conn:
            conn.execute(
                update(trades_table)
                .where(trades_table.c.id == trade_id)
                .values(closed_at=datetime.now(timezone.utc).isoformat(), execution_status="closed")
            )

    def record_close_order_failed(self, trade_id: int, remaining_contracts: int | None = None) -> None:
        """Puts a trade back under management after its closing order died
        (canceled/expired/rejected) — whatever did not close is still open at
        the broker, so the exit has to be re-evaluated and re-sent, for the
        remaining size if the close filled only partially."""
        values: dict[str, object] = {
            "execution_status": "submitted",
            "close_client_order_id": None,
            "exit_reason": None,
            "realized_pnl": None,
        }
        if remaining_contracts is not None and remaining_contracts > 0:
            values["contracts"] = remaining_contracts
        with self._engine.begin() as conn:
            conn.execute(update(trades_table).where(trades_table.c.id == trade_id).values(**values))

    def record_partial_fill(self, trade_id: int, filled_contracts: int) -> None:
        """Resizes a trade to the contracts that actually filled, so exit
        thresholds and any closing order match the real position rather than
        the size that was originally requested."""
        with self._engine.begin() as conn:
            conn.execute(
                update(trades_table).where(trades_table.c.id == trade_id).values(contracts=filled_contracts)
            )

    def record_trade_unfilled(self, trade_id: int, order_status: str) -> None:
        """Marks a trade whose opening order never became a real position
        (canceled/expired/rejected before fill) as closed with zero P&L, so
        list_open_trades() stops handing it to the monitor forever."""
        with self._engine.begin() as conn:
            conn.execute(
                update(trades_table)
                .where(trades_table.c.id == trade_id)
                .values(
                    closed_at=datetime.now(timezone.utc).isoformat(),
                    exit_reason=f"opening_order_{order_status}",
                    realized_pnl=0.0,
                    execution_status=f"never_filled_{order_status}",
                )
            )

    def list_open_trades(self) -> list[dict[str, object]]:
        columns = [
            trades_table.c.id, trades_table.c.opened_at, trades_table.c.symbol, trades_table.c.expiration,
            trades_table.c.short_strike, trades_table.c.long_strike, trades_table.c.contracts,
            trades_table.c.entry_credit, trades_table.c.max_profit, trades_table.c.max_loss,
            trades_table.c.client_order_id, trades_table.c.execution_status,
            trades_table.c.close_client_order_id,
        ]
        with self._engine.connect() as conn:
            rows = conn.execute(select(*columns).where(trades_table.c.closed_at.is_(None))).all()
        return [dict(row._mapping) for row in rows]

    def list_recent_trades(
        self, limit: int = 200, start: str | None = None, end: str | None = None,
        symbol: str | None = None, status: str | None = None,
    ) -> list[dict[str, object]]:
        """start/end are inclusive "YYYY-MM-DD" bounds compared against
        opened_at (ISO8601 text sorts/compares correctly as a string, no date
        parsing needed) — a real date-range filter, not just 'last N rows'."""
        query = select(trades_table).order_by(trades_table.c.id.desc()).limit(limit)
        if start:
            query = query.where(trades_table.c.opened_at >= start)
        if end:
            query = query.where(trades_table.c.opened_at < f"{end}T23:59:59.999999")
        if symbol:
            query = query.where(trades_table.c.symbol == symbol)
        if status:
            query = query.where(trades_table.c.execution_status == status)
        with self._engine.connect() as conn:
            rows = conn.execute(query).all()
        return [dict(row._mapping) for row in rows]

    def list_recent(
        self, limit: int = 200, start: str | None = None, end: str | None = None,
        symbol: str | None = None, final_decision: str | None = None,
    ) -> list[dict[str, object]]:
        columns = [
            decisions_table.c.timestamp, decisions_table.c.symbol,
            decisions_table.c.ai_decision, decisions_table.c.final_decision,
            # The strikes and the individual gate results are what tell one
            # candidate apart from another: a single scan evaluates every
            # viable strike pair on every expiration, so without these the rows
            # are indistinguishable.
            decisions_table.c.options_data, decisions_table.c.risk_checks,
        ]
        query = self._filtered_decisions(
            select(*columns).order_by(decisions_table.c.id.desc()).limit(limit),
            start, end, symbol, final_decision,
        )
        with self._engine.connect() as conn:
            rows = conn.execute(query).all()
        return [dict(row._mapping) for row in rows]

    def _filtered_decisions(
        self, query, start: str | None, end: str | None,
        symbol: str | None, final_decision: str | None,
    ):
        """Applies the journal's filters to any decisions query, so a row
        listing and a count of those rows can never drift apart."""
        if start:
            query = query.where(decisions_table.c.timestamp >= start)
        if end:
            query = query.where(decisions_table.c.timestamp < f"{end}T23:59:59.999999")
        if symbol:
            query = query.where(decisions_table.c.symbol == symbol)
        if final_decision:
            query = query.where(decisions_table.c.final_decision == final_decision)
        return query

    def _scan_summary_sum(
        self, column_name: str, start: str | None, end: str | None, symbol: str | None,
    ) -> int:
        column = scan_summary_table.c[column_name]
        query = select(func.coalesce(func.sum(column), 0))
        if start:
            query = query.where(scan_summary_table.c.timestamp >= start)
        if end:
            query = query.where(scan_summary_table.c.timestamp < f"{end}T23:59:59.999999")
        if symbol:
            query = query.where(scan_summary_table.c.symbol == symbol)
        with self._engine.connect() as conn:
            return int(conn.execute(query).scalar_one())

    def count_decisions(
        self, start: str | None = None, end: str | None = None,
        symbol: str | None = None, final_decision: str | None = None,
    ) -> dict[str, int]:
        """Total and approved candidate counts for a filter.

        Summary figures have to be aggregated in the database, not derived from
        a page of rows: `list_recent` caps its result, so counting what it
        returns reports the cap. With 40,000+ scanned candidates and 32
        approvals, that misreads as "200 scanned, 0 approved".

        Rejected candidates stopped getting an individual decisions row (see
        record_scan_summary) — their count lives in scan_summary instead, so
        the total adds that in rather than undercounting everything scanned
        since the cutover. Added only when the filter doesn't ask for
        APPROVE-only, since every scan_summary row is, by construction,
        rejections.
        """
        total_query = self._filtered_decisions(
            select(func.count()).select_from(decisions_table), start, end, symbol, final_decision
        )
        approved_query = self._filtered_decisions(
            select(func.count()).select_from(decisions_table), start, end, symbol, final_decision
        ).where(decisions_table.c.final_decision == "APPROVE")
        with self._engine.connect() as conn:
            total = int(conn.execute(total_query).scalar_one())
            approved = int(conn.execute(approved_query).scalar_one())
        if final_decision != "APPROVE":
            total += self._scan_summary_sum("rejected", start, end, symbol)
        return {"total": total, "approved": approved}

    def count_trades(
        self, start: str | None = None, end: str | None = None,
        symbol: str | None = None, status: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(trades_table)
        if start:
            query = query.where(trades_table.c.opened_at >= start)
        if end:
            query = query.where(trades_table.c.opened_at < f"{end}T23:59:59.999999")
        if symbol:
            query = query.where(trades_table.c.symbol == symbol)
        if status:
            query = query.where(trades_table.c.execution_status == status)
        with self._engine.connect() as conn:
            return int(conn.execute(query).scalar_one())

    #: The deterministic gates, in the order the engine applies them.
    RISK_GATES = (
        "paper_mode", "dte", "credit", "liquidity_spread", "open_interest", "volume",
        "defined_risk", "position_limit", "daily_loss", "portfolio_risk",
        "duplicate_exposure", "sizing", "ai_score",
    )

    def count_gate_failures(
        self, start: str | None = None, end: str | None = None, symbol: str | None = None,
    ) -> dict[str, int]:
        """How many candidates each risk gate turned away.

        Counted with one conditional-sum pass over the text column rather than
        by parsing 40,000+ JSON blobs in Python, which would mean transferring
        the whole journal to render one panel. Matching on `"<gate>": false`
        works identically on SQLite and Postgres, so the dashboard behaves the
        same against a local file and against Supabase.

        A candidate can fail several gates at once, so these do not sum to the
        rejection count — that is the point: it shows which constraint is
        actually binding.

        Rejections since the scan_summary cutover (see record_scan_summary)
        never reach this table at all, so their gate counts — stored as one
        JSON object per scan — are parsed and summed in here on top of
        whatever historical REJECT rows remain. Summing in Python rather than
        in SQL is fine at this volume: scan_summary has one row per symbol per
        scan, not one per candidate, so there are orders of magnitude fewer of
        them to fetch.
        """
        columns = [
            func.sum(
                case((decisions_table.c.risk_checks.like(f'%"{gate}": false%'), 1), else_=0)
            ).label(gate)
            for gate in self.RISK_GATES
        ]
        query = select(*columns).where(decisions_table.c.final_decision == "REJECT")
        if start:
            query = query.where(decisions_table.c.timestamp >= start)
        if end:
            query = query.where(decisions_table.c.timestamp < f"{end}T23:59:59.999999")
        if symbol:
            query = query.where(decisions_table.c.symbol == symbol)
        with self._engine.connect() as conn:
            row = conn.execute(query).one()
        counts = {gate: int(value or 0) for gate, value in zip(self.RISK_GATES, row)}

        summary_query = select(scan_summary_table.c.gate_counts)
        if start:
            summary_query = summary_query.where(scan_summary_table.c.timestamp >= start)
        if end:
            summary_query = summary_query.where(scan_summary_table.c.timestamp < f"{end}T23:59:59.999999")
        if symbol:
            summary_query = summary_query.where(scan_summary_table.c.symbol == symbol)
        with self._engine.connect() as conn:
            for (blob,) in conn.execute(summary_query):
                for gate, value in json.loads(blob).items():
                    counts[gate] = counts.get(gate, 0) + int(value)
        return counts

    def count_ai_consulted(
        self, start: str | None = None, end: str | None = None, symbol: str | None = None,
    ) -> int:
        """Candidates that reached the AI, i.e. survived every deterministic
        gate that runs before it. The gap between this and the scanned total is
        what pre-screening saves in API calls.

        Every decisions row left after the scan_summary cutover is either an
        approval (which always reached the AI — nothing gets approved without
        it) or a historical rejection from before the cutover, so this query
        is still correct on its own for those; rejections since the cutover
        add their own reached-AI count from scan_summary on top.
        """
        query = select(func.count()).select_from(decisions_table).where(
            ~decisions_table.c.ai_decision.like("%ai_skipped_deterministic_reject%")
        )
        if start:
            query = query.where(decisions_table.c.timestamp >= start)
        if end:
            query = query.where(decisions_table.c.timestamp < f"{end}T23:59:59.999999")
        if symbol:
            query = query.where(decisions_table.c.symbol == symbol)
        with self._engine.connect() as conn:
            consulted = int(conn.execute(query).scalar_one())
        return consulted + self._scan_summary_sum("rejected_reached_ai", start, end, symbol)

    def distinct_symbols(self) -> list[str]:
        with self._engine.connect() as conn:
            rows = conn.execute(select(decisions_table.c.symbol).distinct().order_by(decisions_table.c.symbol)).all()
        return [row[0] for row in rows]

    def daily_decision_counts(self, start: str | None = None, end: str | None = None) -> list[dict[str, object]]:
        """Scanned/approved counts per day (`timestamp`'s first 10 chars, i.e.
        its date — `substr` is standard SQL and works identically on SQLite
        and Postgres, avoiding dialect-specific date functions). start/end
        are inclusive "YYYY-MM-DD" bounds — a real date range, not a LIMIT
        on however many grouped days happen to exist, which would silently
        span more calendar time than intended whenever a day has no rows."""
        day = func.substr(decisions_table.c.timestamp, 1, 10).label("day")
        approved = func.sum(case((decisions_table.c.final_decision == "APPROVE", 1), else_=0)).label("approved")
        query = select(day, func.count().label("scanned"), approved).group_by(day).order_by(day.desc())
        if start:
            query = query.where(decisions_table.c.timestamp >= start)
        if end:
            query = query.where(decisions_table.c.timestamp < f"{end}T23:59:59.999999")
        with self._engine.connect() as conn:
            rows = conn.execute(query).all()
        return [dict(row._mapping) for row in rows]

    def daily_trade_pnl(self, start: str | None = None, end: str | None = None) -> list[dict[str, object]]:
        """Closed-trade counts and realized P&L per day (grouped by
        `closed_at`'s date, filtered by the same inclusive date range as
        daily_decision_counts). Only trades that have actually closed are
        included — open positions have no realized P&L yet."""
        day = func.substr(trades_table.c.closed_at, 1, 10).label("day")
        wins = func.sum(case((trades_table.c.realized_pnl > 0, 1), else_=0)).label("wins")
        losses = func.sum(case((trades_table.c.realized_pnl < 0, 1), else_=0)).label("losses")
        pnl = func.sum(trades_table.c.realized_pnl).label("realized_pnl")
        query = (
            select(day, func.count().label("closed"), wins, losses, pnl)
            .where(trades_table.c.closed_at.is_not(None))
            .group_by(day)
            .order_by(day.desc())
        )
        if start:
            query = query.where(trades_table.c.closed_at >= start)
        if end:
            query = query.where(trades_table.c.closed_at < f"{end}T23:59:59.999999")
        with self._engine.connect() as conn:
            rows = conn.execute(query).all()
        return [dict(row._mapping) for row in rows]

    def close(self) -> None:
        """A no-op: `self._engine` is a process-wide cache shared by every
        DecisionRepository built from the same URL (see `_build_engine`), so
        disposing it here would break every other instance still using it —
        e.g. the next web request. SQLAlchemy's connection pool manages idle
        connections on its own; there is nothing this needs to release
        per-instance. Kept as a method (rather than removed) so every
        existing call site — scripts and tests alike — doesn't need to
        change just because closing is no longer meaningful per-instance."""
