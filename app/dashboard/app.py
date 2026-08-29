from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from app.alpaca.client import AlpacaClients
from app.config.settings import Settings
from app.database.repository import DecisionRepository


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "options_alpha.db"))
ACCOUNT_FETCH_TIMEOUT_SECONDS = 5.0
ACCOUNT_CACHE_TTL_SECONDS = 10.0
app = FastAPI(title="Riskgate")
_account_cache: dict[str, object] = {"data": None, "fetched_at": 0.0}


def _database_target() -> str:
    """DATABASE_URL (e.g. a Supabase postgresql:// URL) takes priority so the
    hosted dashboard can share one journal with GitHub Actions and local
    development; falls back to the local SQLite file (DATABASE_PATH) used in
    development and tests."""
    return os.getenv("DATABASE_URL") or str(DATABASE_PATH)


def account_snapshot() -> dict[str, float] | None:
    """Live portfolio snapshot from Alpaca. Returns None if credentials are
    missing, paper mode is misconfigured, or the API is unreachable — the
    dashboard degrades gracefully rather than failing to render.

    Cached for ACCOUNT_CACHE_TTL_SECONDS: this is a real network call to
    Alpaca on every invocation, so navigating back to the Overview page
    repeatedly within a few seconds would otherwise repeat it needlessly —
    the account balance doesn't change that often. Explicitly NOT cached
    when DASHBOARD_FETCH_ACCOUNT=false or credentials are missing, so tests
    that toggle those between calls keep working."""
    if os.getenv("DASHBOARD_FETCH_ACCOUNT", "true").lower() != "true":
        return None
    if _account_cache["data"] is not None and time.monotonic() - _account_cache["fetched_at"] < ACCOUNT_CACHE_TTL_SECONDS:
        return _account_cache["data"]  # type: ignore[return-value]
    try:
        settings = Settings.from_env(PROJECT_ROOT / ".env")
        settings.require_paper_mode()
        settings.require_credentials()
        settings = settings.model_copy(update={"request_timeout_seconds": ACCOUNT_FETCH_TIMEOUT_SECONDS})
        account = AlpacaClients(settings).verify_account()
        equity = float(account.equity)
        last_equity = float(account.last_equity) if account.last_equity else equity
        snapshot = {
            "equity": equity,
            "cash": float(account.cash) if account.cash else 0.0,
            "buying_power": float(account.buying_power) if account.buying_power else 0.0,
            "daily_pnl": round(equity - last_equity, 2),
            "daily_pnl_pct": round((equity - last_equity) / last_equity * 100, 2) if last_equity else 0.0,
        }
        _account_cache["data"] = snapshot
        _account_cache["fetched_at"] = time.monotonic()
        return snapshot
    except Exception:
        return None


def recent_decisions(
    start: str | None = None, end: str | None = None,
    symbol: str | None = None, final_decision: str | None = None,
) -> list[dict[str, object]]:
    repository = DecisionRepository(_database_target())
    try:
        return repository.list_recent(start=start, end=end, symbol=symbol, final_decision=final_decision)
    finally:
        repository.close()


def recent_trades(
    start: str | None = None, end: str | None = None,
    symbol: str | None = None, status: str | None = None,
) -> list[dict[str, object]]:
    repository = DecisionRepository(_database_target())
    try:
        return repository.list_recent_trades(start=start, end=end, symbol=symbol, status=status)
    finally:
        repository.close()


def known_symbols() -> list[str]:
    repository = DecisionRepository(_database_target())
    try:
        return repository.distinct_symbols()
    finally:
        repository.close()


def daily_kpis(start: str | None = None, end: str | None = None) -> list[dict[str, object]]:
    """Per-day scan/approve counts merged with per-day closed-trade P&L, so
    'is everything going okay today' doesn't require scrolling raw rows."""
    repository = DecisionRepository(_database_target())
    try:
        decisions_by_day = {row["day"]: row for row in repository.daily_decision_counts(start=start, end=end)}
        trades_by_day = {row["day"]: row for row in repository.daily_trade_pnl(start=start, end=end)}
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


def _preset_range(days: int) -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


@app.get("/api/decisions")
def decisions(
    start: str | None = None, end: str | None = None,
    symbol: str | None = None, final_decision: str | None = None,
) -> list[dict[str, object]]:
    return recent_decisions(start, end, symbol, final_decision)


@app.get("/api/trades")
def trades(
    start: str | None = None, end: str | None = None,
    symbol: str | None = None, status: str | None = None,
) -> list[dict[str, object]]:
    return recent_trades(start, end, symbol, status)


@app.get("/api/daily-kpis")
def daily_kpis_endpoint(start: str | None = None, end: str | None = None) -> list[dict[str, object]]:
    return daily_kpis(start, end)


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


def _option(value: str, label: str, selected: str | None) -> str:
    is_selected = " selected" if value == (selected or "") else ""
    return f'<option value="{value}"{is_selected}>{label}</option>'


_CSS = """
:root{
  --bg:#f6f4ef; --surface:#ffffff; --border:#e6e1d6; --border-soft:#f0ece2;
  --text:#1c231f; --text-muted:#6b7268; --accent:#0f7a5c; --accent-soft:#e4f3ec;
  --danger:#c1442a; --danger-soft:#fbe9e5; --neutral:#57606a; --neutral-soft:#eef0f2;
  --radius:14px; --shadow:0 1px 2px rgba(20,20,15,.04), 0 8px 24px -12px rgba(20,20,15,.10);
}
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;
  background:var(--bg);color:var(--text);margin:0;padding:0 0 64px;line-height:1.45}
main{max-width:1180px;margin:0 auto;padding:0 40px}
.topbar{background:var(--surface);border-bottom:1px solid var(--border);margin-bottom:32px}
.topbar-inner{max-width:1180px;margin:0 auto;padding:20px 40px 0}
.topbar header{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;
  padding-bottom:20px}
header h1{margin:0;font-size:24px;letter-spacing:-.02em}
header p{margin:6px 0 0;color:var(--text-muted);font-size:13.5px}
.badge-live{background:var(--accent);color:white;padding:8px 14px;border-radius:999px;
  font-weight:600;font-size:12.5px;letter-spacing:.02em;white-space:nowrap}
nav.tabs{display:flex;gap:4px}
nav.tabs a{display:inline-block;padding:11px 6px;margin-right:22px;color:var(--text-muted);
  text-decoration:none;font-size:14px;font-weight:600;border-bottom:2px solid transparent}
nav.tabs a.active{color:var(--accent);border-bottom-color:var(--accent)}
nav.tabs a:hover:not(.active){color:var(--text)}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.04em;color:var(--text-muted);
  margin:0 0 14px;display:flex;align-items:center;gap:16px;font-weight:700;flex-wrap:wrap}
h2:not(:first-child){margin-top:40px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}
.stat{background:var(--surface);padding:18px 20px;border-radius:var(--radius);
  box-shadow:var(--shadow);border:1px solid var(--border-soft)}
.stat .label{font-size:12.5px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.stat b{display:block;font-size:24px;margin-top:6px;font-weight:700;letter-spacing:-.01em}
.pnl-positive{color:var(--accent)} .pnl-negative{color:var(--danger)}
.muted{color:var(--text-muted)}
.day-filters{display:flex;gap:4px;background:var(--neutral-soft);padding:3px;border-radius:999px;
  text-transform:none;letter-spacing:0}
.day-filters a{color:var(--text-muted);text-decoration:none;font-size:12.5px;font-weight:600;
  padding:5px 12px;border-radius:999px}
.day-filters a.active{background:var(--surface);color:var(--text);box-shadow:var(--shadow)}
.day-filters a:hover:not(.active){color:var(--text)}
.filter-bar{background:var(--surface);border:1px solid var(--border-soft);border-radius:var(--radius);
  box-shadow:var(--shadow);padding:14px 18px;margin-bottom:18px;display:flex;align-items:flex-end;
  gap:14px;flex-wrap:wrap;font-size:13px}
.filter-bar .field{display:flex;flex-direction:column;gap:5px}
.filter-bar label{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--text-muted);font-weight:700}
.filter-bar input,.filter-bar select{border:1px solid var(--border);border-radius:8px;padding:7px 10px;
  font-size:13px;font-family:inherit;background:var(--bg);color:var(--text)}
.filter-bar button{background:var(--accent);color:white;border:none;border-radius:8px;padding:8px 16px;
  font-size:13px;font-weight:700;cursor:pointer}
.filter-bar button:hover{opacity:.9}
.filter-bar .clear{color:var(--text-muted);text-decoration:none;font-size:12.5px;font-weight:600}
.filter-bar .clear:hover{color:var(--text)}
.card{background:var(--surface);border-radius:var(--radius);box-shadow:var(--shadow);
  border:1px solid var(--border-soft);overflow:hidden;overflow-x:auto}
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

_NAV_ITEMS = [
    ("/", "Overview"),
    ("/kpis", "Daily KPIs"),
    ("/trades", "Positions & Trades"),
    ("/decisions", "Decision Journal"),
]


def _page(title: str, active_path: str, body: str) -> str:
    nav_links = "".join(
        f'<a href="{path}"{" class=\"active\"" if path == active_path else ""}>{label}</a>'
        for path, label in _NAV_ITEMS
    )
    return f"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Riskgate — {title}</title>
<style>{_CSS}</style></head>
<body>
<div class="topbar"><div class="topbar-inner">
  <header>
    <div><h1>Riskgate</h1><p>Autonomous Bull Put Spread agent — decision journal and trade log</p></div>
    <span class="badge-live">PAPER TRADING MODE — NO REAL CAPITAL</span>
  </header>
  <nav class="tabs">{nav_links}</nav>
</div></div>
<main>{body}
</main></body></html>"""


def _portfolio_stats_html() -> str:
    account_data = account_snapshot()
    if account_data is not None:
        pnl_class = "pnl-positive" if account_data["daily_pnl"] >= 0 else "pnl-negative"
        sign = "+" if account_data["daily_pnl"] >= 0 else ""
        return f"""
  <div class="stat"><div class="label">Equity</div><b>${account_data['equity']:,.2f}</b></div>
  <div class="stat"><div class="label">Cash</div><b>${account_data['cash']:,.2f}</b></div>
  <div class="stat"><div class="label">Buying power</div><b>${account_data['buying_power']:,.2f}</b></div>
  <div class="stat"><div class="label">Daily P&amp;L</div><b class="{pnl_class}">{sign}${account_data['daily_pnl']:,.2f} ({account_data['daily_pnl_pct']:+.2f}%)</b></div>"""
    return '\n  <div class="stat"><div class="label">Portfolio</div><b class="muted">unavailable</b></div>'


@app.get("/", response_class=HTMLResponse)
def overview_page() -> str:
    decision_rows = recent_decisions()
    approved = sum(1 for d in decision_rows if d["final_decision"] == "APPROVE")
    rejected = len(decision_rows) - approved

    body = f"""
<h2>Portfolio</h2>
<div class="stats">{_portfolio_stats_html()}
</div>

<h2>Agent activity</h2>
<div class="stats">
  <div class="stat"><div class="label">Scanned candidates</div><b>{len(decision_rows)}</b></div>
  <div class="stat"><div class="label">Approved</div><b class="pnl-positive">{approved}</b></div>
  <div class="stat"><div class="label">Rejected</div><b class="muted">{rejected}</b></div>
</div>"""
    return _page("Overview", "/", body)


@app.get("/kpis", response_class=HTMLResponse)
def kpis_page(start: str | None = None, end: str | None = None) -> str:
    if not start and not end:
        start, end = _preset_range(14)
    kpi_data = daily_kpis(start, end)
    max_abs_pnl = max((abs(r["realized_pnl"]) for r in kpi_data if r["realized_pnl"] is not None), default=0)
    total_pnl = sum(r["realized_pnl"] for r in kpi_data if r["realized_pnl"] is not None)
    total_scanned = sum(r["scanned"] for r in kpi_data)
    total_approved = sum(r["approved"] for r in kpi_data)

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
    kpi_table = "".join(kpi_rows) or '<tr><td colspan="9" class="empty-state">No data for this range</td></tr>'

    presets = "".join(
        f'<a href="/kpis?start={p_start}&end={p_end}"{" class=\"active\"" if (start, end) == (p_start, p_end) else ""}>{label}</a>'
        for label, (p_start, p_end) in (
            ("7d", _preset_range(7)), ("14d", _preset_range(14)),
            ("30d", _preset_range(30)), ("90d", _preset_range(90)),
        )
    )

    body = f"""
<h2>Daily KPIs<span class="day-filters">{presets}</span></h2>
<form class="filter-bar" method="get" action="/kpis">
  <div class="field"><label>From</label><input type="date" name="start" value="{start or ''}"></div>
  <div class="field"><label>To</label><input type="date" name="end" value="{end or ''}"></div>
  <button type="submit">Apply</button>
  <a class="clear" href="/kpis">Reset</a>
</form>

<div class="stats">
  <div class="stat"><div class="label">Scanned in range</div><b>{total_scanned}</b></div>
  <div class="stat"><div class="label">Approved in range</div><b class="pnl-positive">{total_approved}</b></div>
  <div class="stat"><div class="label">Days with data</div><b>{len(kpi_data)}</b></div>
  <div class="stat"><div class="label">Total realized P&amp;L</div><b>{_pnl_text(total_pnl if kpi_data else None)}</b></div>
</div>

<h2>By day</h2>
<div class="card"><table><thead><tr><th>Day</th><th>Scanned</th><th>Approved</th><th>Approval %</th>
<th>Closed</th><th>Wins</th><th>Losses</th><th>P&amp;L</th><th></th></tr></thead>
<tbody>{kpi_table}</tbody></table></div>"""
    return _page("Daily KPIs", "/kpis", body)


@app.get("/trades", response_class=HTMLResponse)
def trades_page(
    start: str | None = None, end: str | None = None,
    symbol: str | None = None, status: str | None = None,
) -> str:
    filtered = recent_trades(start, end, symbol or None, status or None)
    open_count = sum(1 for t in filtered if not t["closed_at"])
    closed = [t for t in filtered if t["closed_at"]]
    wins = sum(1 for t in closed if (t["realized_pnl"] or 0) > 0)
    losses = sum(1 for t in closed if (t["realized_pnl"] or 0) < 0)
    total_pnl = sum(t["realized_pnl"] for t in closed if t["realized_pnl"] is not None)

    trade_rows = []
    for trade in filtered:
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
    trades_table = "".join(trade_rows) or '<tr><td colspan="10" class="empty-state">No trades match these filters</td></tr>'

    symbol_options = "".join(_option(s, s, symbol) for s in known_symbols())
    status_options = "".join(
        _option(value, label, status)
        for value, label in (("submitted", "Submitted"), ("closed", "Closed"), ("dry_run", "Dry run"), ("closed_dry_run", "Closed (dry run)"))
    )

    body = f"""
<h2>Positions &amp; trades</h2>
<form class="filter-bar" method="get" action="/trades">
  <div class="field"><label>From</label><input type="date" name="start" value="{start or ''}"></div>
  <div class="field"><label>To</label><input type="date" name="end" value="{end or ''}"></div>
  <div class="field"><label>Symbol</label><select name="symbol"><option value="">All</option>{symbol_options}</select></div>
  <div class="field"><label>Status</label><select name="status"><option value="">All</option>{status_options}</select></div>
  <button type="submit">Apply</button>
  <a class="clear" href="/trades">Reset</a>
</form>

<div class="stats">
  <div class="stat"><div class="label">Matching trades</div><b>{len(filtered)}</b></div>
  <div class="stat"><div class="label">Open</div><b>{open_count}</b></div>
  <div class="stat"><div class="label">Wins / Losses</div><b><span class="pnl-positive">{wins}</span> / <span class="pnl-negative">{losses}</span></b></div>
  <div class="stat"><div class="label">Realized P&amp;L</div><b>{_pnl_text(total_pnl if closed else None)}</b></div>
</div>

<div class="card"><table><thead><tr><th>Opened</th><th>Symbol</th><th>Expiration</th><th>Strikes</th>
<th>Contracts</th><th>Credit</th><th>Status</th><th>Closed</th><th>Exit reason</th><th>P&amp;L</th></tr></thead>
<tbody>{trades_table}</tbody></table></div>"""
    return _page("Positions & Trades", "/trades", body)


@app.get("/decisions", response_class=HTMLResponse)
def decisions_page(
    start: str | None = None, end: str | None = None,
    symbol: str | None = None, final_decision: str | None = None,
) -> str:
    filtered = recent_decisions(start, end, symbol or None, final_decision or None)
    approved = sum(1 for d in filtered if d["final_decision"] == "APPROVE")
    rejected = len(filtered) - approved

    rows = []
    for decision in filtered:
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
    decisions_table = "".join(rows) or '<tr><td colspan="6" class="empty-state">No decisions match these filters</td></tr>'

    symbol_options = "".join(_option(s, s, symbol) for s in known_symbols())
    decision_options = "".join(_option(v, v, final_decision) for v in ("APPROVE", "REJECT"))

    body = f"""
<h2>Decision journal — why each candidate was approved or rejected</h2>
<form class="filter-bar" method="get" action="/decisions">
  <div class="field"><label>From</label><input type="date" name="start" value="{start or ''}"></div>
  <div class="field"><label>To</label><input type="date" name="end" value="{end or ''}"></div>
  <div class="field"><label>Symbol</label><select name="symbol"><option value="">All</option>{symbol_options}</select></div>
  <div class="field"><label>Decision</label><select name="final_decision"><option value="">All</option>{decision_options}</select></div>
  <button type="submit">Apply</button>
  <a class="clear" href="/decisions">Reset</a>
</form>

<div class="stats">
  <div class="stat"><div class="label">Matching candidates</div><b>{len(filtered)}</b></div>
  <div class="stat"><div class="label">Approved</div><b class="pnl-positive">{approved}</b></div>
  <div class="stat"><div class="label">Rejected</div><b class="muted">{rejected}</b></div>
  <div class="stat"><div class="label">Approval rate</div><b>{round(approved / len(filtered) * 100, 1) if filtered else 0}%</b></div>
</div>

<div class="card"><table><thead><tr><th>Timestamp</th><th>Symbol</th><th>AI score</th><th>Decision</th>
<th>Risk flags</th><th>Rationale</th></tr></thead><tbody>{decisions_table}</tbody></table></div>"""
    return _page("Decision Journal", "/decisions", body)
