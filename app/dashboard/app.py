from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.alpaca.client import AlpacaClients
from app.config.settings import Settings
from app.database.repository import DecisionRepository


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "options_alpha.db"))
ACCOUNT_FETCH_TIMEOUT_SECONDS = 5.0
app = FastAPI(title="Options Alpha Agent")


def account_snapshot() -> dict[str, float] | None:
    """Live portfolio snapshot from Alpaca. Returns None if credentials are
    missing, paper mode is misconfigured, or the API is unreachable — the
    dashboard degrades gracefully rather than failing to render."""
    if os.getenv("DASHBOARD_FETCH_ACCOUNT", "true").lower() != "true":
        return None
    try:
        settings = Settings.from_env(PROJECT_ROOT / ".env")
        settings.require_paper_mode()
        settings.require_credentials()
        settings = settings.model_copy(update={"request_timeout_seconds": ACCOUNT_FETCH_TIMEOUT_SECONDS})
        account = AlpacaClients(settings).verify_account()
        equity = float(account.equity)
        last_equity = float(account.last_equity) if account.last_equity else equity
        return {
            "equity": equity,
            "cash": float(account.cash) if account.cash else 0.0,
            "buying_power": float(account.buying_power) if account.buying_power else 0.0,
            "daily_pnl": round(equity - last_equity, 2),
            "daily_pnl_pct": round((equity - last_equity) / last_equity * 100, 2) if last_equity else 0.0,
        }
    except Exception:
        return None


def recent_decisions() -> list[dict[str, object]]:
    repository = DecisionRepository(DATABASE_PATH)
    try:
        return repository.list_recent()
    finally:
        repository.close()


def recent_trades() -> list[dict[str, object]]:
    repository = DecisionRepository(DATABASE_PATH)
    try:
        return repository.list_recent_trades()
    finally:
        repository.close()


@app.get("/api/decisions")
def decisions() -> list[dict[str, object]]:
    return recent_decisions()


@app.get("/api/trades")
def trades() -> list[dict[str, object]]:
    return recent_trades()


@app.get("/api/account")
def account() -> dict[str, float] | dict[str, None]:
    return account_snapshot() or {"equity": None, "cash": None, "buying_power": None, "daily_pnl": None, "daily_pnl_pct": None}


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    decision_rows = recent_decisions()
    approved = sum(1 for d in decision_rows if d["final_decision"] == "APPROVE")
    rejected = len(decision_rows) - approved

    rows = []
    for decision in decision_rows:
        proposal = json.loads(str(decision["ai_decision"]))
        risk_flags = proposal.get("risk_flags", [])
        ai_not_consulted = "ai_skipped_deterministic_reject" in risk_flags
        ai_score_display = "n/a (not consulted)" if ai_not_consulted else proposal.get("score", 0)
        rows.append(
            "<tr><td>{timestamp}</td><td>{symbol}</td><td>{ai}</td><td>{final}</td><td>{reason}</td><td>{why}</td></tr>".format(
                timestamp=decision["timestamp"],
                symbol=decision["symbol"],
                ai=ai_score_display,
                final=decision["final_decision"],
                reason=_escape(", ".join(risk_flags) or "none"),
                why=_escape(", ".join(proposal.get("rationale", []))),
            )
        )
    decisions_table = "".join(rows) or '<tr><td colspan="6">No decisions recorded</td></tr>'

    trade_rows = []
    for trade in recent_trades():
        status = trade["execution_status"]
        pnl = trade["realized_pnl"]
        trade_rows.append(
            "<tr><td>{opened}</td><td>{symbol}</td><td>{expiration}</td><td>{short}/{long}</td>"
            "<td>{contracts}</td><td>{credit}</td><td>{status}</td><td>{closed}</td><td>{exit_reason}</td><td>{pnl}</td></tr>".format(
                opened=trade["opened_at"],
                symbol=trade["symbol"],
                expiration=trade["expiration"],
                short=trade["short_strike"],
                long=trade["long_strike"],
                contracts=trade["contracts"],
                credit=trade["entry_credit"],
                status=status,
                closed=trade["closed_at"] or "open",
                exit_reason=trade["exit_reason"] or "-",
                pnl=pnl if pnl is not None else "-",
            )
        )
    trades_table = "".join(trade_rows) or '<tr><td colspan="10">No trades recorded</td></tr>'

    account_data = account_snapshot()
    if account_data is not None:
        pnl_class = "pnl-positive" if account_data["daily_pnl"] >= 0 else "pnl-negative"
        portfolio_stats = f"""
  <div class="stat">Equity<b>${account_data['equity']:,.2f}</b></div>
  <div class="stat">Cash<b>${account_data['cash']:,.2f}</b></div>
  <div class="stat">Buying power<b>${account_data['buying_power']:,.2f}</b></div>
  <div class="stat">Daily P&amp;L<b class="{pnl_class}">${account_data['daily_pnl']:,.2f} ({account_data['daily_pnl_pct']:+.2f}%)</b></div>"""
    else:
        portfolio_stats = '\n  <div class="stat">Portfolio<b>unavailable</b></div>'

    return f"""<!doctype html>
<html><head><title>Options Alpha Agent</title>
<style>body{{font-family:Segoe UI,sans-serif;background:#f4f1ea;color:#1d2925;margin:40px}}main{{max-width:1200px;margin:auto}}header{{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #d9d0c2;padding-bottom:18px}}.badge{{background:#176b5b;color:white;padding:8px 12px;border-radius:4px;font-weight:700}}.stats{{display:flex;gap:16px;margin-top:20px;flex-wrap:wrap}}.stat{{background:white;padding:14px 20px;border-radius:6px;box-shadow:0 1px 2px rgba(0,0,0,.08)}}.stat b{{display:block;font-size:22px}}.pnl-positive{{color:#176b5b}}.pnl-negative{{color:#b3402c}}table{{width:100%;border-collapse:collapse;background:white;margin-top:20px;font-size:14px}}th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #e7e0d6}}th{{background:#1d2925;color:white}}h2{{margin-top:36px}}</style></head>
<body><main><header><div><h1>Options Alpha Agent</h1><p>Autonomous Bull Put Spread agent — decision journal and trade log</p></div><span class="badge">PAPER TRADING MODE — NO REAL CAPITAL</span></header>
<h2>Portfolio</h2>
<div class="stats">{portfolio_stats}
</div>
<h2>Agent activity</h2>
<div class="stats">
  <div class="stat">Scanned candidates<b>{len(decision_rows)}</b></div>
  <div class="stat">Approved<b>{approved}</b></div>
  <div class="stat">Rejected<b>{rejected}</b></div>
</div>
<h2>Positions &amp; trades</h2>
<table><thead><tr><th>Opened</th><th>Symbol</th><th>Expiration</th><th>Short/Long strike</th><th>Contracts</th><th>Entry credit</th><th>Status</th><th>Closed</th><th>Exit reason</th><th>Realized P&amp;L</th></tr></thead><tbody>{trades_table}</tbody></table>
<h2>Decision journal — why each candidate was approved or rejected</h2>
<table><thead><tr><th>Timestamp</th><th>Symbol</th><th>AI score</th><th>Final decision</th><th>Risk flags</th><th>Rationale</th></tr></thead><tbody>{decisions_table}</tbody></table>
</main></body></html>"""
