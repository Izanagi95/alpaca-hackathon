from pathlib import Path

from app.database.repository import DecisionRepository


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
