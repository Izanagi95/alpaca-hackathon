from fastapi.testclient import TestClient

from app.dashboard import app as dashboard_module


def test_overview_page_renders_with_nav_and_empty_portfolio(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", tmp_path / "dashboard.db")
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")
    client = TestClient(dashboard_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "PAPER TRADING MODE" in response.text
    assert "Portfolio" in response.text
    assert "unavailable" in response.text
    assert "Daily KPIs" in response.text  # nav link present on every page
    assert "Positions & Trades" in response.text
    assert "Decision Journal" in response.text


def test_kpis_page_renders_empty_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", tmp_path / "kpis.db")
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")
    client = TestClient(dashboard_module.app)

    response = client.get("/kpis?start=2026-08-01&end=2026-08-07")

    assert response.status_code == 200
    assert "No data for this range" in response.text


def test_trades_page_renders_empty_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", tmp_path / "trades.db")
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")
    client = TestClient(dashboard_module.app)

    response = client.get("/trades")

    assert response.status_code == 200
    assert "No trades match these filters" in response.text


def test_decisions_page_renders_empty_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", tmp_path / "decisions.db")
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")
    client = TestClient(dashboard_module.app)

    response = client.get("/decisions")

    assert response.status_code == 200
    assert "No decisions match these filters" in response.text


def test_decisions_page_date_filter_excludes_out_of_range_rows(tmp_path, monkeypatch) -> None:
    from app.database.repository import DecisionRepository, decisions_table

    db_path = tmp_path / "filter.db"
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", db_path)
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")

    repo = DecisionRepository(db_path)
    with repo._engine.begin() as conn:
        conn.execute(decisions_table.insert().values(
            timestamp="2026-01-01T10:00:00+00:00", symbol="OLD", market_data="{}", options_data="{}",
            ai_decision="{}", ai_rationale="[]", risk_checks="{}", final_decision="APPROVE",
        ))
        conn.execute(decisions_table.insert().values(
            timestamp="2026-08-20T10:00:00+00:00", symbol="NEW", market_data="{}", options_data="{}",
            ai_decision="{}", ai_rationale="[]", risk_checks="{}", final_decision="REJECT",
        ))

    client = TestClient(dashboard_module.app)
    response = client.get("/decisions?start=2026-08-01&end=2026-08-31")

    # "OLD" itself may still appear in the symbol filter dropdown (it lists every
    # known symbol regardless of the active date range) — check the actual table
    # row content (the formatted timestamp) instead of a raw substring match.
    assert "Aug 20" in response.text
    assert "Jan 01" not in response.text


def test_trades_page_symbol_filter_form_preselects_value(tmp_path, monkeypatch) -> None:
    from app.database.repository import DecisionRepository, decisions_table

    db_path = tmp_path / "symbolfilter.db"
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", db_path)
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")

    repo = DecisionRepository(db_path)
    with repo._engine.begin() as conn:
        conn.execute(decisions_table.insert().values(
            timestamp="2026-08-20T10:00:00+00:00", symbol="AAPL", market_data="{}", options_data="{}",
            ai_decision="{}", ai_rationale="[]", risk_checks="{}", final_decision="APPROVE",
        ))

    client = TestClient(dashboard_module.app)
    response = client.get("/trades?symbol=AAPL")

    assert response.status_code == 200
    assert 'value="AAPL" selected' in response.text


def test_overview_names_the_journal_it_is_reading(tmp_path, monkeypatch) -> None:
    """Portfolio figures and journal tables are configured independently, so the
    page has to say which account and which journal it is showing."""
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", tmp_path / "identity.db")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")
    client = TestClient(dashboard_module.app)

    response = client.get("/")

    assert "identity.db" in response.text
    assert "are unavailable" in response.text  # account fetching is off


def test_overview_reports_the_postgres_schema_from_database_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", tmp_path / "unused.db")
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pw@host:5432/postgres?options=-c%20search_path%3Dmyschema",
    )

    assert dashboard_module._journal_schema() == "schema myschema"


def _seed_decision(repo, *, timestamp: str, symbol: str, final_decision: str) -> None:
    from app.database.repository import decisions_table

    with repo._engine.begin() as conn:
        conn.execute(decisions_table.insert().values(
            timestamp=timestamp, symbol=symbol, market_data="{}",
            options_data='{"short_strike": 100, "long_strike": 95, "expiration": "2026-09-18"}',
            ai_decision='{"score": 80, "rationale": [], "risk_flags": []}',
            ai_rationale="[]", risk_checks='{"reasons": []}', final_decision=final_decision,
        ))


def test_summary_counts_come_from_the_database_not_the_visible_rows(tmp_path, monkeypatch) -> None:
    """The row listing is capped, so counting it reports the cap. With 40k+
    scanned candidates that misread as "200 scanned, 0 approved" - the summary
    has to be aggregated in the database instead."""
    from app.database.repository import DecisionRepository

    db_path = tmp_path / "counts.db"
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", db_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")

    repo = DecisionRepository(db_path)
    for i in range(4):
        _seed_decision(repo, timestamp=f"2026-08-2{i}T10:00:00+00:00", symbol="QQQ", final_decision="REJECT")
    _seed_decision(repo, timestamp="2026-08-25T10:00:00+00:00", symbol="QQQ", final_decision="APPROVE")

    # No rows reach the table, yet the tiles must still report the journal.
    monkeypatch.setattr(dashboard_module, "recent_decisions", lambda *a, **k: [])
    response = TestClient(dashboard_module.app).get("/")

    assert "Scanned candidates" in response.text
    assert ">5<" in response.text  # total, not the length of the row list
    assert ">1<" in response.text  # approved


def test_count_decisions_honours_filters(tmp_path) -> None:
    from app.database.repository import DecisionRepository

    repo = DecisionRepository(tmp_path / "countfilter.db")
    _seed_decision(repo, timestamp="2026-01-01T10:00:00+00:00", symbol="OLD", final_decision="APPROVE")
    _seed_decision(repo, timestamp="2026-08-20T10:00:00+00:00", symbol="NEW", final_decision="APPROVE")
    _seed_decision(repo, timestamp="2026-08-21T10:00:00+00:00", symbol="NEW", final_decision="REJECT")

    assert repo.count_decisions() == {"total": 3, "approved": 2}
    assert repo.count_decisions(start="2026-08-01", end="2026-08-31") == {"total": 2, "approved": 1}
    assert repo.count_decisions(symbol="NEW") == {"total": 2, "approved": 1}
    assert repo.count_decisions(final_decision="REJECT") == {"total": 1, "approved": 0}


def test_decisions_table_distinguishes_rows_by_strike_and_failed_gates(tmp_path, monkeypatch) -> None:
    """Every candidate in a scan shares symbol, timestamp and generic rationale;
    the strikes and the gates it failed are what tell them apart."""
    from app.database.repository import DecisionRepository, decisions_table

    db_path = tmp_path / "gates.db"
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", db_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")

    repo = DecisionRepository(db_path)
    with repo._engine.begin() as conn:
        conn.execute(decisions_table.insert().values(
            timestamp="2026-08-20T10:00:00+00:00", symbol="QQQ", market_data="{}",
            options_data='{"short_strike": 705, "long_strike": 700, "expiration": "2026-09-14"}',
            ai_decision='{"score": 0, "rationale": [], "risk_flags": ["ai_skipped_deterministic_reject"]}',
            ai_rationale="[]",
            risk_checks='{"reasons": ["credit", "duplicate_exposure", "ai_score"]}',
            final_decision="REJECT",
        ))

    response = TestClient(dashboard_module.app).get("/decisions")

    assert "705/700" in response.text
    assert "2026-09-14" in response.text
    assert "duplicate_exposure" in response.text
    assert "credit" in response.text
    # The AI was never consulted, so its score gate failing is an artefact of
    # the default zero rather than a finding worth reporting beside real ones.
    assert "ai_score" not in response.text


def test_account_snapshot_disabled_via_env(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")

    assert dashboard_module.account_snapshot() is None


def test_account_snapshot_degrades_gracefully_without_credentials(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "true")
    monkeypatch.setattr(dashboard_module, "PROJECT_ROOT", tmp_path)  # no .env here -> no credentials

    assert dashboard_module.account_snapshot() is None


def test_api_account_endpoint_returns_null_fields_when_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")
    client = TestClient(dashboard_module.app)

    response = client.get("/api/account")

    assert response.status_code == 200
    assert response.json() == {"equity": None, "cash": None, "buying_power": None, "daily_pnl": None, "daily_pnl_pct": None}
