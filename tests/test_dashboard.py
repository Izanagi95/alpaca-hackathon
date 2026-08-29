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

    response = client.get("/kpis?days=7")

    assert response.status_code == 200
    assert "No data yet for this window" in response.text


def test_trades_page_renders_empty_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", tmp_path / "trades.db")
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")
    client = TestClient(dashboard_module.app)

    response = client.get("/trades")

    assert response.status_code == 200
    assert "No trades recorded yet" in response.text


def test_decisions_page_renders_empty_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", tmp_path / "decisions.db")
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")
    client = TestClient(dashboard_module.app)

    response = client.get("/decisions")

    assert response.status_code == 200
    assert "No decisions recorded yet" in response.text


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
