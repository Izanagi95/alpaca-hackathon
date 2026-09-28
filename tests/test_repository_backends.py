from pathlib import Path

from app.database.repository import DecisionRepository, _pin_psycopg2_driver, _search_path_schema


def test_pin_psycopg2_driver_names_the_driver_on_a_bare_postgres_url() -> None:
    # SQLAlchemy's default driver choice for a driver-less postgresql:// URL
    # is not a stable contract across versions (2.1 switched it from psycopg2
    # to psycopg v3, which this project doesn't install) — naming it
    # explicitly is what keeps a routine dependency upgrade from breaking
    # every scheduled run with ModuleNotFoundError.
    url = "postgresql://user:pw@host:6543/postgres?options=-c%20search_path%3Dalpaca"
    assert _pin_psycopg2_driver(url) == (
        "postgresql+psycopg2://user:pw@host:6543/postgres?options=-c%20search_path%3Dalpaca"
    )


def test_pin_psycopg2_driver_leaves_an_already_pinned_driver_alone() -> None:
    url = "postgresql+psycopg2://user:pw@host/db"
    assert _pin_psycopg2_driver(url) == url


def test_pin_psycopg2_driver_does_not_corrupt_a_sqlite_url() -> None:
    # Reconstructing every URL via urlsplit/urlunsplit loses a slash on an
    # authority-less sqlite:///file.db URL, so anything that isn't the exact
    # scheme being rewritten must come back byte-for-byte unchanged.
    url = "sqlite:///riskgate.db"
    assert _pin_psycopg2_driver(url) == url


def test_search_path_schema_extracted_from_options_param() -> None:
    url = "postgresql://user:pw@host:6543/postgres?options=-c%20search_path%3Dalpaca&pgbouncer=true"
    assert _search_path_schema(url) == "alpaca"


def test_search_path_schema_handles_no_space_variant() -> None:
    url = "postgresql://user:pw@host:6543/postgres?options=-csearch_path%3Dalpaca"
    assert _search_path_schema(url) == "alpaca"


def test_search_path_schema_none_when_absent() -> None:
    url = "postgresql://user:pw@host:6543/postgres"
    assert _search_path_schema(url) is None


def test_search_path_schema_none_for_sqlite() -> None:
    assert _search_path_schema("sqlite:///riskgate.db") is None


def test_bare_path_becomes_a_local_sqlite_url(tmp_path) -> None:
    db_path = tmp_path / "journal.db"
    repository = DecisionRepository(db_path)

    assert str(repository._engine.url).startswith("sqlite:///")
    assert db_path.exists()  # actually created the local file
    repository.close()


def test_bare_string_path_also_becomes_a_local_sqlite_url(tmp_path) -> None:
    db_path = str(tmp_path / "journal2.db")
    repository = DecisionRepository(db_path)

    assert str(repository._engine.url).startswith("sqlite:///")
    repository.close()


def test_a_url_is_used_as_is_without_local_file_creation(tmp_path) -> None:
    # Use another local sqlite URL (not a real Postgres server) just to prove
    # a string containing "://" is passed straight to SQLAlchemy rather than
    # being treated as a filesystem path — the "://" detection is what lets a
    # postgresql://... (Supabase) URL work the same way in production.
    db_path = tmp_path / "explicit.db"
    url = f"sqlite:///{db_path}"
    repository = DecisionRepository(url)

    assert str(repository._engine.url) == url
    assert db_path.exists()
    repository.close()
