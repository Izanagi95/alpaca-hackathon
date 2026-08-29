from app.database.repository import DecisionRepository, decisions_table, trades_table


def _seed(repo: DecisionRepository) -> None:
    with repo._engine.begin() as conn:
        conn.execute(decisions_table.insert().values(
            timestamp="2026-08-10T10:00:00+00:00", symbol="AAPL", market_data="{}", options_data="{}",
            ai_decision="{}", ai_rationale="[]", risk_checks="{}", final_decision="APPROVE",
        ))
        conn.execute(decisions_table.insert().values(
            timestamp="2026-08-20T10:00:00+00:00", symbol="SPY", market_data="{}", options_data="{}",
            ai_decision="{}", ai_rationale="[]", risk_checks="{}", final_decision="REJECT",
        ))
        conn.execute(trades_table.insert().values(
            opened_at="2026-08-10T10:00:00+00:00", closed_at=None,
            symbol="AAPL", strategy="bull_put_spread", expiration="2026-09-25",
            short_strike=240, long_strike=235, contracts=2, entry_credit=1.1,
            max_profit=110, max_loss=390, ai_score=80, confidence=0.8,
            client_order_id="a", execution_status="dry_run", exit_reason=None, realized_pnl=None,
        ))
        conn.execute(trades_table.insert().values(
            opened_at="2026-08-20T10:00:00+00:00", closed_at="2026-08-21T10:00:00+00:00",
            symbol="SPY", strategy="bull_put_spread", expiration="2026-09-25",
            short_strike=700, long_strike=695, contracts=1, entry_credit=1.0,
            max_profit=100, max_loss=400, ai_score=85, confidence=0.9,
            client_order_id="b", execution_status="closed", exit_reason="profit_target", realized_pnl=60.0,
        ))


def test_list_recent_filters_by_date_range(tmp_path) -> None:
    repo = DecisionRepository(tmp_path / "f1.db")
    _seed(repo)

    rows = repo.list_recent(start="2026-08-15", end="2026-08-31")

    assert len(rows) == 1
    assert rows[0]["symbol"] == "SPY"
    repo.close()


def test_list_recent_filters_by_symbol_and_decision(tmp_path) -> None:
    repo = DecisionRepository(tmp_path / "f2.db")
    _seed(repo)

    assert len(repo.list_recent(symbol="AAPL")) == 1
    assert len(repo.list_recent(final_decision="REJECT")) == 1
    assert len(repo.list_recent(symbol="AAPL", final_decision="REJECT")) == 0
    repo.close()


def test_list_recent_trades_filters_by_status_and_date(tmp_path) -> None:
    repo = DecisionRepository(tmp_path / "f3.db")
    _seed(repo)

    assert len(repo.list_recent_trades(status="closed")) == 1
    assert len(repo.list_recent_trades(start="2026-08-15", end="2026-08-31")) == 1
    assert len(repo.list_recent_trades(start="2026-08-01", end="2026-08-05")) == 0
    repo.close()


def test_distinct_symbols_returns_sorted_unique_list(tmp_path) -> None:
    repo = DecisionRepository(tmp_path / "f4.db")
    _seed(repo)

    assert repo.distinct_symbols() == ["AAPL", "SPY"]
    repo.close()
