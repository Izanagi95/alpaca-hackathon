from fastapi.testclient import TestClient

from app.dashboard import app as dashboard_module


def test_dashboard_renders_empty_journal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_module, "DATABASE_PATH", tmp_path / "dashboard.db")
    monkeypatch.setenv("DASHBOARD_FETCH_ACCOUNT", "false")
    client = TestClient(dashboard_module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "PAPER TRADING MODE" in response.text
    assert "No decisions recorded" in response.text
    assert "Portfolio" in response.text
    assert "unavailable" in response.text


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
