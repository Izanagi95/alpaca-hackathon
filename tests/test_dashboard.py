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
