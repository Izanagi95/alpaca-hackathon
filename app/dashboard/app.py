from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from app.alpaca.client import AlpacaClients
from app.config.settings import Settings
from app.database.repository import DecisionRepository


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "options_alpha.db"))
ACCOUNT_FETCH_TIMEOUT_SECONDS = 5.0
app = FastAPI(title="Options Alpha Agent")


def _database_target() -> str:
    """DATABASE_URL (e.g. a Supabase postgresql:// URL) takes priority so the
    hosted dashboard can share one journal with GitHub Actions and local
    development; falls back to the local SQLite file (DATABASE_PATH) used in
    development and tests."""
    return os.getenv("DATABASE_URL") or str(DATABASE_PATH)


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
    repository = DecisionRepository(_database_target())
    try:
        return repository.list_recent()
    finally:
        repository.close()


def recent_trades() -> list[dict[str, object]]:
    repository = DecisionRepository(_database_target())
    try:
        return repository.list_recent_trades()
    finally:
        repository.close()


def daily_kpis(days: int) -> list[dict[str, object]]:
    """Per-day scan/approve counts merged with per-day closed-trade P&L, so
    'is everything going okay today' doesn't require scrolling raw rows."""
    repository = DecisionRepository(_database_target())
    try:
        decisions_by_day = {row["day"]: row for row in repository.daily_decision_counts(days=days)}
        trades_by_day = {row["day"]: row for row in repository.daily_trade_pnl(days=days)}
    finally:
        repository.close()

    days_seen = sorted(set(decisions_by_day) | set(trades_by_day), reverse=True)
    merged = []
    for day in days_seen:
        d = decisions_by_day.get(day, {"scanned": 0, "approved": 0})
        t = trades_by_day.get(day, {"closed": 0, "wins": 0, "losses": 0, "realized_pnl": None})
        scanned = d["scanned"]
        approved = d["approved"]
        merged.append({
            "day": day,
            "scanned": scanned,
            "approved": approved,
            "approval_pct": round(approved / scanned * 100, 1) if scanned else 0.0,
            "closed": t["closed"],
            "wins": t["wins"],
            "losses": t["losses"],
            "realized_pnl": t["realized_pnl"],
        })
    return merged


@app.get("/api/decisions")
def decisions() -> list[dict[str, object]]:
    return recent_decisions()


@app.get("/api/trades")
def trades() -> list[dict[str, object]]:
    return recent_trades()


@app.get("/api/daily-kpis")
def daily_kpis_endpoint(days: int = Query(default=14, ge=1, le=365)) -> list[dict[str, object]]:
    return daily_kpis(days)


@app.get("/api/account")
def account() -> dict[str, float] | dict[str, None]:
    return account_snapshot() or {"equity": None, "cash": None, "buying_power": None, "daily_pnl": None, "daily_pnl_pct": None}


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_ts(raw: str) -> str:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.strftime("%b %d, %H:%M")
    except ValueError:
        return str(raw)


def _decision_badge(final_decision: str) -> str:
    css_class = "badge-approve" if final_decision == "APPROVE" else "badge-reject"
    return f'<span class="badge {css_class}">{final_decision}</span>'


def _status_badge(status: str) -> str:
    css_class = {
        "submitted": "badge-approve", "closed": "badge-neutral",
        "dry_run": "badge-muted", "closed_dry_run": "badge-muted",
    }.get(status, "badge-muted")
    return f'<span class="badge {css_class}">{status}</span>'


def _pnl_text(value: float | None) -> str:
    if value is None:
        return '<span class="muted">-</span>'
    css_class = "pnl-positive" if value >= 0 else "pnl-negative"
    sign = "+" if value >= 0 else ""
    return f'<span class="{css_class}">{sign}${value:,.2f}</span>'


def _pnl_bar(value: float | None, max_abs: float) -> str:
    if value is None or max_abs <= 0:
        return '<div class="bar-track"></div>'
    width = min(100, abs(value) / max_abs * 100)
    side_class = "bar-positive" if value >= 0 else "bar-negative"
    justify = "flex-end" if value < 0 else "flex-start"
    return (
        f'<div class="bar-track" style="justify-content:{justify}">'
        f'<div class="bar-fill {side_class}" style="width:{width:.1f}%"></div></div>'
    )


_CSS = """
:root{
  --bg:#f6f4ef; --surface:#ffffff; --border:#e6e1d6; --border-soft:#f0ece2;
  --text:#1c231f; --text-muted:#6b7268; --accent:#0f7a5c; --accent-soft:#e4f3ec;
  --danger:#c1442a; --danger-soft:#fbe9e5; --neutral:#57606a; --neutral-soft:#eef0f2;
  --radius:14px; --shadow:0 1px 2px rgba(20,20,15,.04), 0 8px 24px -12px rgba(20,20,15,.10);
}
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;
  background:var(--bg);color:var(--text);margin:0;padding:32px 40px 64px;line-height:1.45}
main{max-width:1180px;margin:0 auto}
header{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;
  padding-bottom:24px;margin-bottom:8px;border-bottom:1px solid var(--border)}
header h1{margin:0;font-size:26px;letter-spacing:-.02em}
header p{margin:6px 0 0;color:var(--text-muted);font-size:14px}
.badge-live{background:var(--accent);color:white;padding:8px 14px;border-radius:999px;
  font-weight:600;font-size:12.5px;letter-spacing:.02em;white-space:nowrap}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);
  margin:40px 0 14px;display:flex;align-items:center;gap:16px;font-weight:700}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}
.stat{background:var(--surface);padding:18px 20px;border-radius:var(--radius);
  box-shadow:var(--shadow);border:1px solid var(--border-soft)}
.stat .label{font-size:12.5px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.stat b{display:block;font-size:24px;margin-top:6px;font-weight:700;letter-spacing:-.01em}
.pnl-positive{color:var(--accent)} .pnl-negative{color:var(--danger)}
.muted{color:var(--text-muted)}
.day-filters{display:flex;gap:4px;background:var(--neutral-soft);padding:3px;border-radius:999px;
  margin-left:auto;text-transform:none;letter-spacing:0}
.day-filters a{color:var(--text-muted);text-decoration:none;font-size:12.5px;font-weight:600;
  padding:5px 12px;border-radius:999px}
.day-filters a.active{background:var(--surface);color:var(--text);box-shadow:var(--shadow)}
.day-filters a:hover:not(.active){color:var(--text)}
.card{background:var(--surface);border-radius:var(--radius);box-shadow:var(--shadow);
  border:1px solid var(--border-soft);overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;padding:11px 16px;background:var(--border-soft);color:var(--text-muted);
  font-weight:700;font-size:11.5px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap}
td{padding:11px 16px;border-top:1px solid var(--border-soft);white-space:nowrap;vertical-align:middle}
tbody tr:hover{background:var(--bg)}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:11.5px;font-weight:700;
  letter-spacing:.02em}
.badge-approve{background:var(--accent-soft);color:var(--accent)}
.badge-reject{background:var(--danger-soft);color:var(--danger)}
.badge-neutral{background:var(--neutral-soft);color:var(--neutral)}
.badge-muted{background:var(--border-soft);color:var(--text-muted)}
.bar-track{display:flex;width:130px;height:16px;background:var(--border-soft);border-radius:4px;overflow:hidden}
.bar-fill{height:100%;border-radius:4px}
.bar-positive{background:var(--accent)} .bar-negative{background:var(--danger)}
.rationale-cell{white-space:normal;max-width:340px;color:var(--text-muted);font-size:12.5px}
.empty-state{padding:32px 16px;text-align:center;color:var(--text-muted)}
"""


@app.get("/", response_class=HTMLResponse)
def dashboard(days: int = Query(default=14, ge=1, le=365)) -> str:
    decision_rows = recent_decisions()
    approved = sum(1 for d in decision_rows if d["final_decision"] == "APPROVE")
    rejected = len(decision_rows) - approved

    rows = []
    for decision in decision_rows:
        proposal = json.loads(str(decision["ai_decision"]))
        risk_flags = proposal.get("risk_flags", [])
        ai_not_consulted = "ai_skipped_deterministic_reject" in risk_flags
        ai_score_display = '<span class="muted">not consulted</span>' if ai_not_consulted else f"<b>{proposal.get('score', 0)}</b>"
        rows.append(
            "<tr><td>{timestamp}</td><td><b>{symbol}</b></td><td>{ai}</td><td>{final}</td>"
            "<td class=\"muted\">{reason}</td><td class=\"rationale-cell\">{why}</td></tr>".format(
                timestamp=_format_ts(decision["timestamp"]),
                symbol=decision["symbol"],
                ai=ai_score_display,
                final=_decision_badge(str(decision["final_decision"])),
                reason=_escape(", ".join(risk_flags) or "none"),
                why=_escape(", ".join(proposal.get("rationale", []))),
            )
        )
    decisions_table = "".join(rows) or '<tr><td colspan="6" class="empty-state">No decisions recorded yet</td></tr>'

    trade_rows = []
    for trade in recent_trades():
        pnl = trade["realized_pnl"]
        trade_rows.append(
            "<tr><td>{opened}</td><td><b>{symbol}</b></td><td>{expiration}</td><td>{short}/{long}</td>"
            "<td>{contracts}</td><td>${credit:.2f}</td><td>{status}</td><td>{closed}</td>"
            "<td class=\"muted\">{exit_reason}</td><td>{pnl}</td></tr>".format(
                opened=_format_ts(trade["opened_at"]),
                symbol=trade["symbol"],
                expiration=trade["expiration"],
                short=trade["short_strike"],
                long=trade["long_strike"],
                contracts=trade["contracts"],
                credit=float(trade["entry_credit"]),
                status=_status_badge(str(trade["execution_status"])),
                closed=_format_ts(trade["closed_at"]) if trade["closed_at"] else '<span class="muted">open</span>',
                exit_reason=trade["exit_reason"] or "-",
                pnl=_pnl_text(pnl),
            )
        )
    trades_table = "".join(trade_rows) or '<tr><td colspan="10" class="empty-state">No trades recorded yet</td></tr>'

    kpi_data = daily_kpis(days)
    max_abs_pnl = max((abs(r["realized_pnl"]) for r in kpi_data if r["realized_pnl"] is not None), default=0)
    kpi_rows = []
    for row in kpi_data:
        kpi_rows.append(
            "<tr><td><b>{day}</b></td><td>{scanned}</td><td>{approved}</td><td>{approval_pct}%</td>"
            "<td>{closed}</td><td class=\"pnl-positive\">{wins}</td><td class=\"pnl-negative\">{losses}</td>"
            "<td>{bar}</td><td>{pnl}</td></tr>".format(
                day=row["day"], scanned=row["scanned"], approved=row["approved"],
                approval_pct=row["approval_pct"], closed=row["closed"], wins=row["wins"],
                losses=row["losses"], bar=_pnl_bar(row["realized_pnl"], max_abs_pnl), pnl=_pnl_text(row["realized_pnl"]),
            )
        )
    kpi_table = "".join(kpi_rows) or '<tr><td colspan="9" class="empty-state">No data yet for this window</td></tr>'
    day_filters = "".join(
        f'<a href="/?days={option}"{" class=\"active\"" if option == days else ""}>{option}d</a>'
        for option in (7, 14, 30, 90)
    )

    account_data = account_snapshot()
    if account_data is not None:
        pnl_class = "pnl-positive" if account_data["daily_pnl"] >= 0 else "pnl-negative"
        sign = "+" if account_data["daily_pnl"] >= 0 else ""
        portfolio_stats = f"""
  <div class="stat"><div class="label">Equity</div><b>${account_data['equity']:,.2f}</b></div>
  <div class="stat"><div class="label">Cash</div><b>${account_data['cash']:,.2f}</b></div>
  <div class="stat"><div class="label">Buying power</div><b>${account_data['buying_power']:,.2f}</b></div>
  <div class="stat"><div class="label">Daily P&amp;L</div><b class="{pnl_class}">{sign}${account_data['daily_pnl']:,.2f} ({account_data['daily_pnl_pct']:+.2f}%)</b></div>"""
    else:
        portfolio_stats = '\n  <div class="stat"><div class="label">Portfolio</div><b class="muted">unavailable</b></div>'

    return f"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Options Alpha Agent</title>
<style>{_CSS}</style></head>
<body><main>
<header>
  <div><h1>Options Alpha Agent</h1><p>Autonomous Bull Put Spread agent — decision journal and trade log</p></div>
  <span class="badge-live">PAPER TRADING MODE — NO REAL CAPITAL</span>
</header>

<h2>Portfolio</h2>
<div class="stats">{portfolio_stats}
</div>

<h2>Agent activity</h2>
<div class="stats">
  <div class="stat"><div class="label">Scanned candidates</div><b>{len(decision_rows)}</b></div>
  <div class="stat"><div class="label">Approved</div><b class="pnl-positive">{approved}</b></div>
  <div class="stat"><div class="label">Rejected</div><b class="muted">{rejected}</b></div>
</div>

<h2>Daily KPIs<span class="day-filters">{day_filters}</span></h2>
<div class="card"><table><thead><tr><th>Day</th><th>Scanned</th><th>Approved</th><th>Approval %</th>
<th>Closed</th><th>Wins</th><th>Losses</th><th>P&amp;L</th><th></th></tr></thead>
<tbody>{kpi_table}</tbody></table></div>

<h2>Positions &amp; trades</h2>
<div class="card"><table><thead><tr><th>Opened</th><th>Symbol</th><th>Expiration</th><th>Strikes</th>
<th>Contracts</th><th>Credit</th><th>Status</th><th>Closed</th><th>Exit reason</th><th>P&amp;L</th></tr></thead>
<tbody>{trades_table}</tbody></table></div>

<h2>Decision journal — why each candidate was approved or rejected</h2>
<div class="card"><table><thead><tr><th>Timestamp</th><th>Symbol</th><th>AI score</th><th>Decision</th>
<th>Risk flags</th><th>Rationale</th></tr></thead><tbody>{decisions_table}</tbody></table></div>

</main></body></html>"""
