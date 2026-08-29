from app.database.repository import DecisionRepository, decisions_table, trades_table


def test_daily_decision_counts_groups_by_date(tmp_path) -> None:
    repo = DecisionRepository(tmp_path / "kpi.db")
    with repo._engine.begin() as conn:
        conn.execute(decisions_table.insert().values(
            timestamp="2026-08-27T10:00:00+00:00", symbol="AAPL", market_data="{}", options_data="{}",
            ai_decision="{}", ai_rationale="[]", risk_checks="{}", final_decision="APPROVE",
        ))
        conn.execute(decisions_table.insert().values(
            timestamp="2026-08-27T11:00:00+00:00", symbol="MSFT", market_data="{}", options_data="{}",
            ai_decision="{}", ai_rationale="[]", risk_checks="{}", final_decision="REJECT",
        ))
        conn.execute(decisions_table.insert().values(
            timestamp="2026-08-28T09:00:00+00:00", symbol="SPY", market_data="{}", options_data="{}",
            ai_decision="{}", ai_rationale="[]", risk_checks="{}", final_decision="APPROVE",
        ))

    rows = {row["day"]: row for row in repo.daily_decision_counts(days=30)}

    assert rows["2026-08-27"]["scanned"] == 2
    assert rows["2026-08-27"]["approved"] == 1
    assert rows["2026-08-28"]["scanned"] == 1
    assert rows["2026-08-28"]["approved"] == 1
    repo.close()


def test_daily_trade_pnl_only_counts_closed_trades(tmp_path) -> None:
    repo = DecisionRepository(tmp_path / "kpi2.db")
    with repo._engine.begin() as conn:
        # closed on 2026-08-27: one win, one loss
        conn.execute(trades_table.insert().values(
            opened_at="2026-08-25T10:00:00+00:00", closed_at="2026-08-27T15:00:00+00:00",
            symbol="AAPL", strategy="bull_put_spread", expiration="2026-09-25",
            short_strike=240, long_strike=235, contracts=2, entry_credit=1.1,
            max_profit=110, max_loss=390, ai_score=80, confidence=0.8,
            client_order_id="a", execution_status="closed", exit_reason="profit_target", realized_pnl=80.0,
        ))
        conn.execute(trades_table.insert().values(
            opened_at="2026-08-26T10:00:00+00:00", closed_at="2026-08-27T16:00:00+00:00",
            symbol="MSFT", strategy="bull_put_spread", expiration="2026-09-25",
            short_strike=400, long_strike=395, contracts=1, entry_credit=0.9,
            max_profit=90, max_loss=410, ai_score=75, confidence=0.7,
            client_order_id="b", execution_status="closed", exit_reason="stop_loss", realized_pnl=-150.0,
        ))
        # still open — must not be counted
        conn.execute(trades_table.insert().values(
            opened_at="2026-08-27T10:00:00+00:00", closed_at=None,
            symbol="SPY", strategy="bull_put_spread", expiration="2026-09-25",
            short_strike=700, long_strike=695, contracts=1, entry_credit=1.0,
            max_profit=100, max_loss=400, ai_score=85, confidence=0.9,
            client_order_id="c", execution_status="dry_run", exit_reason=None, realized_pnl=None,
        ))

    rows = repo.daily_trade_pnl(days=30)
    assert len(rows) == 1
    day_row = rows[0]
    assert day_row["day"] == "2026-08-27"
    assert day_row["closed"] == 2
    assert day_row["wins"] == 1
    assert day_row["losses"] == 1
    assert day_row["realized_pnl"] == -70.0
    repo.close()
