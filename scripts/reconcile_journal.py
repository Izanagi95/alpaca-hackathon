"""Reconciles the trade journal against the broker's own record, trade by trade.

The journal records a trade when its opening order is *submitted*, so it can
disagree with the broker in three distinct ways: a position that never filled,
a position that filled at a different size than requested, and a realized P&L
computed from quotes rather than from actual fills. This script identifies
which of those applies to every row and totals the difference, so a journal
figure is never mistaken for account performance.

It needs credentials and DATABASE_URL for the *same* account — a mismatched
pair produces zero matches, which is reported rather than silently treated as
"every trade is missing at the broker".
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest

from app.alpaca.client import AlpacaClients
from app.config.settings import Settings
from app.database.repository import DecisionRepository, trades_table

CONTRACT_MULTIPLIER = 100


def _fetch_orders(clients: AlpacaClients, since: datetime) -> dict[str, object]:
    """Every order placed since `since`, indexed by client order id. Indexed in
    one pass rather than looked up per trade, so a journal of any size costs the
    same handful of API calls."""
    by_client_id: dict[str, object] = {}
    request = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=500, after=since)
    for order in clients.trading.get_orders(request):
        if order.client_order_id:
            by_client_id[order.client_order_id] = order
    return by_client_id


def _net_price_per_contract(order: object, closing: bool) -> float | None:
    """Net premium per contract from the legs' actual fills.

    Opening a bull put spread sells the higher strike and buys the lower one, so
    the credit received is sell_fill - buy_fill. Closing reverses both legs, so
    the debit paid is buy_fill - sell_fill. Returns None when any leg has no
    fill price, since a partial picture would be worse than no number at all.
    """
    legs = getattr(order, "legs", None) or []
    if not legs:
        return None
    sold = bought = None
    for leg in legs:
        price = getattr(leg, "filled_avg_price", None)
        if price is None:
            return None
        if "SELL" in str(leg.side).upper():
            sold = float(price)
        else:
            bought = float(price)
    if sold is None or bought is None:
        return None
    return (bought - sold) if closing else (sold - bought)


def _filled_contracts(order: object) -> int:
    legs = getattr(order, "legs", None) or []
    if legs:
        return min(int(float(getattr(leg, "filled_qty", 0) or 0)) for leg in legs)
    return int(float(getattr(order, "filled_qty", 0) or 0))


def main() -> int:
    settings = Settings.from_env(PROJECT_ROOT / ".env")
    settings.require_paper_mode()
    settings.require_credentials()

    clients = AlpacaClients(settings)
    account = clients.verify_account()

    repository = DecisionRepository(settings.database_url or PROJECT_ROOT / "riskgate.db")
    with repository._engine.connect() as connection:
        trades = [dict(row._mapping) for row in connection.execute(
            select(trades_table).order_by(trades_table.c.opened_at)
        ).all()]

    print(f"account_id={account.id} account_number={account.account_number} equity={account.equity}")
    print(f"journal_trades={len(trades)}")
    if not trades:
        print("nothing to reconcile")
        return 0

    earliest = min(str(t["opened_at"]) for t in trades)
    since = datetime.fromisoformat(earliest.replace("Z", "+00:00")) - timedelta(days=1)
    orders = _fetch_orders(clients, since.astimezone(timezone.utc))
    print(f"broker_orders_since_{since.date()}={len(orders)}")

    matched = sum(1 for t in trades if str(t["client_order_id"]) in orders)
    if matched == 0:
        print()
        print("MISMATCH: none of the journal's orders exist on this account.")
        print("The credentials and DATABASE_URL point at different accounts -")
        print("reconciliation is meaningless until they name the same one.")
        return 2
    print(f"matched_openings={matched}/{len(trades)}")
    print()

    verdicts: Counter[str] = Counter()
    journal_realized = 0.0
    # Only rows the broker can price are compared head to head; mixing in rows
    # with no broker counterpart would make the difference meaningless, since
    # one side of it would simply be absent.
    comparable_journal = 0.0
    comparable_broker = 0.0
    unexplained_total = 0.0
    unexplained: list[str] = []

    for trade in trades:
        label = (
            f"{str(trade['opened_at'])[:16]} {trade['symbol']:<5} "
            f"{float(trade['short_strike']):.0f}/{float(trade['long_strike']):.0f} "
            f"x{trade['contracts']}"
        )
        journal_pnl = trade["realized_pnl"]
        if journal_pnl is not None:
            journal_realized += float(journal_pnl)

        opening = orders.get(str(trade["client_order_id"]))
        if opening is None:
            verdicts["missing_at_broker"] += 1
            print(f"MISSING     {label} - no such order on this account")
            if journal_pnl:
                unexplained_total += float(journal_pnl)
                unexplained.append(f"{label}: journal {float(journal_pnl):+.2f}, order not at broker")
            continue

        opened_contracts = _filled_contracts(opening)
        if opened_contracts == 0:
            # The defining failure mode: nothing ever filled, so any P&L the
            # journal carries for this row was computed against a position the
            # broker never held.
            verdicts["never_filled"] += 1
            status = str(opening.status).split(".")[-1]
            note = f" - journal claims {float(journal_pnl):+.2f}" if journal_pnl else ""
            print(f"UNFILLED    {label} broker_status={status}{note}")
            if journal_pnl:
                unexplained_total += float(journal_pnl)
                unexplained.append(f"{label}: journal {float(journal_pnl):+.2f}, never filled")
            continue

        if opened_contracts != int(trade["contracts"]):
            verdicts["size_mismatch"] += 1
            print(f"SIZE        {label} - broker filled {opened_contracts}")

        if trade["closed_at"] is None:
            verdicts["open"] += 1
            continue

        closing = orders.get(str(trade["close_client_order_id"] or ""))
        if closing is None or _filled_contracts(closing) == 0:
            verdicts["closed_without_broker_close"] += 1
            note = f" journal {float(journal_pnl):+.2f}" if journal_pnl else ""
            print(f"NO CLOSE    {label} - journal closed, broker never closed it;{note}")
            if journal_pnl:
                unexplained_total += float(journal_pnl)
                unexplained.append(f"{label}: journal {float(journal_pnl):+.2f}, no filled closing order")
            continue

        credit = _net_price_per_contract(opening, closing=False)
        debit = _net_price_per_contract(closing, closing=True)
        if credit is None or debit is None:
            verdicts["unpriceable"] += 1
            print(f"NO PRICE    {label} - fills lack prices, cannot recompute")
            continue

        actual = (credit - debit) * CONTRACT_MULTIPLIER * min(opened_contracts, _filled_contracts(closing))
        comparable_broker += actual
        comparable_journal += float(journal_pnl or 0.0)
        delta = actual - float(journal_pnl or 0.0)
        if abs(delta) < 0.51:
            verdicts["reconciled"] += 1
        else:
            verdicts["pnl_mismatch"] += 1
            print(f"PNL DIFF    {label} - journal {float(journal_pnl or 0):+.2f} vs broker {actual:+.2f} ({delta:+.2f})")

    print()
    print("--- verdicts ---")
    for name, count in sorted(verdicts.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<28} {count}")

    print()
    print("--- realized P&L ---")
    print(f"  journal total, every row            {journal_realized:+.2f}")
    print(f"  of which has no broker position     {unexplained_total:+.2f}")
    print()
    print("  rows the broker can price, compared head to head:")
    print(f"    journal                           {comparable_journal:+.2f}")
    print(f"    recomputed from actual fills      {comparable_broker:+.2f}")
    print(f"    difference                        {comparable_broker - comparable_journal:+.2f}")

    if unexplained:
        print()
        print("--- journal P&L with no broker position behind it ---")
        for line in unexplained:
            print(f"  {line}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"RECONCILE FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from error
