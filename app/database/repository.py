from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.ai_decision import AIProposal
from app.execution.order_manager import ExecutionResult
from app.execution.position_manager import ExitDecision
from app.risk.risk_engine import RiskDecision
from app.strategy.bull_put_spread import BullPutSpreadCandidate


class DecisionRepository:
    def __init__(self, database_path: str | Path = "options_alpha.db") -> None:
        self._connection = sqlite3.connect(database_path)
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                market_data TEXT NOT NULL,
                options_data TEXT NOT NULL,
                ai_decision TEXT NOT NULL,
                ai_rationale TEXT NOT NULL,
                risk_checks TEXT NOT NULL,
                final_decision TEXT NOT NULL
            )"""
        )
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                expiration TEXT NOT NULL,
                short_strike REAL NOT NULL,
                long_strike REAL NOT NULL,
                contracts INTEGER NOT NULL,
                entry_credit REAL NOT NULL,
                max_profit REAL NOT NULL,
                max_loss REAL NOT NULL,
                ai_score INTEGER NOT NULL,
                confidence REAL NOT NULL,
                client_order_id TEXT NOT NULL,
                execution_status TEXT NOT NULL,
                exit_reason TEXT,
                realized_pnl REAL
            )"""
        )
        self._connection.commit()

    def record(
        self,
        candidate: BullPutSpreadCandidate,
        proposal: AIProposal,
        risk_decision: RiskDecision,
    ) -> None:
        market_data = candidate.model_dump(mode="json", include={"symbol", "underlying_price", "market_regime", "trend", "realized_volatility", "implied_volatility"})
        options_data = candidate.model_dump(mode="json", include={"expiration", "short_strike", "long_strike", "short_delta", "short_bid", "short_ask", "long_bid", "long_ask", "short_open_interest", "long_open_interest", "short_volume", "long_volume"})
        final_decision = "APPROVE" if proposal.decision == "APPROVE" and risk_decision.approved else "REJECT"
        self._connection.execute(
            "INSERT INTO decisions(timestamp, symbol, market_data, options_data, ai_decision, ai_rationale, risk_checks, final_decision) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                candidate.symbol,
                json.dumps(market_data),
                json.dumps(options_data),
                proposal.model_dump_json(),
                json.dumps(proposal.rationale),
                json.dumps({"checks": risk_decision.checks, "reasons": risk_decision.reasons}),
                final_decision,
            ),
        )
        self._connection.commit()

    def count(self) -> int:
        return int(self._connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0])

    def record_trade_open(
        self,
        candidate: BullPutSpreadCandidate,
        proposal: AIProposal,
        risk_decision: RiskDecision,
        execution: ExecutionResult,
    ) -> int | None:
        if not execution.submitted:
            return None
        cursor = self._connection.execute(
            """INSERT INTO trades(
                opened_at, symbol, strategy, expiration, short_strike, long_strike,
                contracts, entry_credit, max_profit, max_loss, ai_score, confidence,
                client_order_id, execution_status
            ) VALUES (?, ?, 'bull_put_spread', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                candidate.symbol,
                candidate.expiration.isoformat(),
                candidate.short_strike,
                candidate.long_strike,
                risk_decision.contracts,
                candidate.midpoint_credit,
                round(candidate.midpoint_credit * 100, 2),
                candidate.max_loss_per_contract,
                proposal.score,
                proposal.confidence,
                execution.client_order_id,
                "dry_run" if execution.dry_run else "submitted",
            ),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    def record_trade_close(
        self,
        trade_id: int,
        exit_decision: ExitDecision,
        execution: ExecutionResult,
    ) -> None:
        self._connection.execute(
            """UPDATE trades SET closed_at = ?, exit_reason = ?, realized_pnl = ?,
               execution_status = ? WHERE id = ?""",
            (
                datetime.now(timezone.utc).isoformat(),
                exit_decision.reason.value,
                exit_decision.current_pnl,
                "closed_dry_run" if execution.dry_run else "closed",
                trade_id,
            ),
        )
        self._connection.commit()

    def list_open_trades(self) -> list[dict[str, object]]:
        columns = [
            "id", "opened_at", "symbol", "expiration", "short_strike", "long_strike",
            "contracts", "entry_credit", "max_profit", "max_loss",
        ]
        rows = self._connection.execute(
            f"SELECT {', '.join(columns)} FROM trades WHERE closed_at IS NULL",
        ).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def list_recent_trades(self, limit: int = 50) -> list[dict[str, object]]:
        columns = [
            "id", "opened_at", "closed_at", "symbol", "strategy", "expiration",
            "short_strike", "long_strike", "contracts", "entry_credit",
            "max_profit", "max_loss", "ai_score", "confidence",
            "client_order_id", "execution_status", "exit_reason", "realized_pnl",
        ]
        rows = self._connection.execute(
            f"SELECT {', '.join(columns)} FROM trades ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def list_recent(self, limit: int = 50) -> list[dict[str, object]]:
        rows = self._connection.execute(
            "SELECT timestamp, symbol, ai_decision, final_decision FROM decisions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "timestamp": row[0],
                "symbol": row[1],
                "ai_decision": row[2],
                "final_decision": row[3],
            }
            for row in rows
        ]

    def close(self) -> None:
        self._connection.close()
