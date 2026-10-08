"""Tests for the shared SQLite connection-management helpers.

These mirror the behaviour the dashboard profile DB relies on: commit on
success, rollback on error, and — most importantly — always close the
connection so WAL side-files (-wal/-shm) are released (prevents WinError 32 on
Windows temp-dir cleanup and state leaking between tests).
"""

import sqlite3

import pytest

from smart_home_common.sqlite_helpers import (
    SqliteHelper,
    open_connection,
    sqlite_connection,
)


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")


# ---------------------------------------------------------------------------
# open_connection
# ---------------------------------------------------------------------------
def test_open_connection_sets_row_factory_by_default(tmp_path):
    conn = open_connection(tmp_path / "a.db")
    try:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        row = conn.execute("SELECT x FROM t").fetchone()
        # sqlite3.Row supports index AND key access.
        assert row[0] == 1
        assert row["x"] == 1
    finally:
        conn.close()


def test_open_connection_enables_wal_on_file_db(tmp_path):
    conn = open_connection(tmp_path / "a.db")
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_open_connection_creates_parent_dirs(tmp_path):
    nested = tmp_path / "deep" / "nested" / "dir" / "a.db"
    assert not nested.parent.exists()
    conn = open_connection(nested)
    try:
        assert nested.parent.exists()
    finally:
        conn.close()


def test_open_connection_wal_disabled(tmp_path):
    conn = open_connection(tmp_path / "a.db", wal=False)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        # Default journal mode is 'delete' when WAL is not requested.
        assert mode.lower() != "wal"
    finally:
        conn.close()


def test_open_connection_memory_db_skips_wal():
    conn = open_connection(":memory:")
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        # In-memory databases use the 'memory' journal mode; WAL is never set.
        assert mode.lower() != "wal"
    finally:
        conn.close()


def test_open_connection_row_factory_none_returns_tuples(tmp_path):
    conn = open_connection(tmp_path / "a.db", row_factory=None)
    try:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        row = conn.execute("SELECT x FROM t").fetchone()
        assert isinstance(row, tuple)
        assert row == (1,)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# sqlite_connection context manager
# ---------------------------------------------------------------------------
def test_commits_on_success(tmp_path):
    db = tmp_path / "a.db"
    with sqlite_connection(db, init=_schema) as conn:
        conn.execute("INSERT INTO kv VALUES (?, ?)", ("a", "1"))

    # Re-open in a fresh connection: the row must have been committed.
    with sqlite_connection(db, init=_schema) as conn:
        row = conn.execute("SELECT v FROM kv WHERE k = ?", ("a",)).fetchone()
        assert row["v"] == "1"


def test_rolls_back_on_error(tmp_path):
    db = tmp_path / "a.db"
    # Seed one row in its own committed transaction.
    with sqlite_connection(db, init=_schema) as conn:
        conn.execute("INSERT INTO kv VALUES (?, ?)", ("keep", "1"))

    # A body that writes then raises must leave NOTHING from that body behind.
    with pytest.raises(RuntimeError):
        with sqlite_connection(db, init=_schema) as conn:
            conn.execute("INSERT INTO kv VALUES (?, ?)", ("drop", "2"))
            raise RuntimeError("boom")

    with sqlite_connection(db, init=_schema) as conn:
        rows = {r["k"]: r["v"] for r in conn.execute("SELECT k, v FROM kv").fetchall()}
    assert rows == {"keep": "1"}


def test_connection_closed_after_context(tmp_path):
    with sqlite_connection(tmp_path / "a.db", init=_schema) as conn:
        pass
    # Operating on a closed connection raises ProgrammingError.
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_connection_closed_even_on_error(tmp_path):
    captured = {}
    with pytest.raises(RuntimeError):
        with sqlite_connection(tmp_path / "a.db", init=_schema) as conn:
            captured["conn"] = conn
            raise RuntimeError("boom")
    with pytest.raises(sqlite3.ProgrammingError):
        captured["conn"].execute("SELECT 1")


def test_init_error_still_closes_connection(tmp_path):
    def bad_init(conn):
        raise ValueError("schema failed")

    with pytest.raises(ValueError, match="schema failed"):
        with sqlite_connection(tmp_path / "a.db", init=bad_init):
            pass  # pragma: no cover - body never runs
    # No assertion on the connection object (not exposed); the point is that
    # the error propagated and did not hang / leak. A follow-up open proves the
    # file is usable.
    with sqlite_connection(tmp_path / "a.db", init=_schema) as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1


def test_no_init_leaves_schema_untouched(tmp_path):
    db = tmp_path / "a.db"
    # Without init, there is no table -> querying it errors.
    with pytest.raises(sqlite3.OperationalError):
        with sqlite_connection(db) as conn:
            conn.execute("SELECT * FROM kv").fetchall()


def test_wal_sidecar_files_released_for_temp_cleanup(tmp_path):
    """The whole reason this helper exists: after the context exits, the WAL
    handles are released so the DB file and its -wal/-shm siblings can be
    deleted (the WinError 32 scenario)."""
    db = tmp_path / "a.db"
    with sqlite_connection(db, init=_schema) as conn:
        conn.execute("INSERT INTO kv VALUES (?, ?)", ("a", "1"))

    # If the connection were still open, unlinking the file on Windows would
    # raise PermissionError. On POSIX it would succeed regardless, so this is a
    # best-effort guard that at minimum must not raise.
    db.unlink()
    assert not db.exists()


# ---------------------------------------------------------------------------
# SqliteHelper
# ---------------------------------------------------------------------------
def test_helper_connect_runs_schema(tmp_path):
    db = SqliteHelper(tmp_path / "a.db", init=_schema)
    with db.connect() as conn:
        conn.execute("INSERT INTO kv VALUES (?, ?)", ("a", "1"))
    with db.connect() as conn:
        assert conn.execute("SELECT v FROM kv WHERE k='a'").fetchone()["v"] == "1"


def test_helper_connect_raw_skips_schema(tmp_path):
    db = SqliteHelper(tmp_path / "a.db", init=_schema)
    # connect_raw does not create the table, so querying it errors.
    with pytest.raises(sqlite3.OperationalError):
        with db.connect_raw() as conn:
            conn.execute("SELECT * FROM kv").fetchall()


def test_helper_connect_with_schema_false_matches_connect_raw(tmp_path):
    db = SqliteHelper(tmp_path / "a.db", init=_schema)
    with pytest.raises(sqlite3.OperationalError):
        with db.connect(with_schema=False) as conn:
            conn.execute("SELECT * FROM kv").fetchall()


def test_helper_commits_and_persists_across_connects(tmp_path):
    db = SqliteHelper(tmp_path / "a.db", init=_schema)
    with db.connect() as conn:
        conn.execute("INSERT INTO kv VALUES (?, ?)", ("a", "1"))
        conn.execute("INSERT INTO kv VALUES (?, ?)", ("b", "2"))
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0]
    assert count == 2


def test_helper_connection_closed_after_context(tmp_path):
    db = SqliteHelper(tmp_path / "a.db", init=_schema)
    with db.connect() as conn:
        pass
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_helper_exposes_db_path(tmp_path):
    path = tmp_path / "a.db"
    db = SqliteHelper(path, init=_schema)
    assert db.db_path == path
