"""Reusable SQLite connection-management helpers for smart-home services.

This module extracts the connection-management pattern that was fixed in the
dashboard profile system (``dashboard/src/profiles/db.py``) so other services
can reuse it instead of re-implementing it (and re-introducing the same bugs).

The core problem it solves: plain ``with sqlite3.connect(path) as conn:`` commits
(or rolls back) the transaction on exit but DOES NOT close the connection. With
``PRAGMA journal_mode=WAL`` that leaves ``-wal`` / ``-shm`` file handles open,
which:

- leaks state between tests (a later test sees an earlier test's rows), and
- raises ``WinError 32`` ("file in use") when a temp dir is cleaned up on
  Windows.

:func:`sqlite_connection` fixes both: it enables WAL, commits on success,
rolls back on error, and ALWAYS closes the connection in a ``finally`` block so
the WAL side-files are released.

Usage::

    from smart_home_common.sqlite_helpers import sqlite_connection

    # Raw connection (no schema setup):
    with sqlite_connection("/data/app.db") as conn:
        conn.execute("INSERT INTO t (x) VALUES (?)", (1,))
    # -> committed and closed here

    # With a schema-initialiser run once per connection open:
    def ensure_schema(conn):
        conn.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER)")

    with sqlite_connection("/data/app.db", init=ensure_schema) as conn:
        conn.execute("INSERT INTO t (x) VALUES (?)", (1,))

    # Or build a small manager object to carry the path/config once and hand out
    # context managers:
    db = SqliteHelper("/data/app.db", init=ensure_schema)
    with db.connect() as conn:
        rows = conn.execute("SELECT x FROM t").fetchall()
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# Type alias: a callable that prepares a freshly-opened connection (e.g. creates
# tables). It receives the connection and returns nothing.
InitFn = Callable[[sqlite3.Connection], None]


def open_connection(
    db_path: str | Path,
    *,
    wal: bool = True,
    row_factory: Callable[[sqlite3.Cursor, tuple], object] | None = sqlite3.Row,
    check_same_thread: bool = False,
    create_parents: bool = True,
) -> sqlite3.Connection:
    """Open a raw SQLite connection with sensible smart-home defaults.

    This is the low-level primitive. Prefer :func:`sqlite_connection` (or
    :class:`SqliteHelper`), which wrap this in a context manager that commits
    and ALWAYS closes the connection so WAL side-files are released.

    Args:
        db_path: Path to the database file.
        wal: Enable ``PRAGMA journal_mode=WAL`` (default True).
        row_factory: Row factory to set on the connection. Defaults to
            :class:`sqlite3.Row` for name/index access; pass ``None`` to keep
            the stdlib default (plain tuples).
        check_same_thread: Passed through to :func:`sqlite3.connect`. Defaults
            to ``False`` so the connection may be used from a different thread
            (safe here because each caller opens its own short-lived
            connection).
        create_parents: Create the database file's parent directory if missing
            (default True). Ignored for in-memory databases.

    Returns:
        An open :class:`sqlite3.Connection`. The caller is responsible for
        closing it.
    """
    path_str = str(db_path)
    is_memory = path_str == ":memory:" or path_str.startswith("file::memory:")

    if create_parents and not is_memory:
        Path(path_str).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path_str, check_same_thread=check_same_thread)
    if row_factory is not None:
        conn.row_factory = row_factory
    if wal and not is_memory:
        # WAL is pointless (and unsupported) for :memory: databases.
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def sqlite_connection(
    db_path: str | Path,
    *,
    init: InitFn | None = None,
    wal: bool = True,
    row_factory: Callable[[sqlite3.Cursor, tuple], object] | None = sqlite3.Row,
    check_same_thread: bool = False,
    create_parents: bool = True,
) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection, committing on success and ALWAYS closing it.

    Mirrors ``with sqlite3.connect(...)`` implicit-commit semantics but adds:

    - a guaranteed ``conn.close()`` in ``finally`` so WAL ``-wal`` / ``-shm``
      file handles are released (prevents ``WinError 32`` on Windows temp-dir
      cleanup and state leaking between tests), and
    - an explicit ``conn.rollback()`` when the body raises, so a failed block
      never leaves a half-applied transaction behind on the shared connection
      before it is closed.

    Args:
        db_path: Path to the database file.
        init: Optional callable run once against the freshly-opened connection
            before it is yielded — typically to create tables
            (``CREATE TABLE IF NOT EXISTS ...``). Any error it raises propagates
            and the connection is still closed.
        wal: Enable WAL journal mode (default True).
        row_factory: Row factory to set (default :class:`sqlite3.Row`).
        check_same_thread: Passed to :func:`sqlite3.connect` (default False).
        create_parents: Create the parent directory if missing (default True).

    Yields:
        The open :class:`sqlite3.Connection`.
    """
    conn = open_connection(
        db_path,
        wal=wal,
        row_factory=row_factory,
        check_same_thread=check_same_thread,
        create_parents=create_parents,
    )
    try:
        if init is not None:
            init(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class SqliteHelper:
    """Carries a database path + open options and hands out context managers.

    Convenience wrapper for services that touch the same database repeatedly:
    configure the path, WAL mode, row factory and an optional schema-initialiser
    once, then call :meth:`connect` wherever a connection is needed.

    Example::

        def _schema(conn):
            conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")

        db = SqliteHelper("/data/app.db", init=_schema)

        with db.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", ("a", "1"))

        with db.connect() as conn:
            row = conn.execute("SELECT v FROM kv WHERE k = ?", ("a",)).fetchone()
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        init: InitFn | None = None,
        wal: bool = True,
        row_factory: Callable[[sqlite3.Cursor, tuple], object] | None = sqlite3.Row,
        check_same_thread: bool = False,
        create_parents: bool = True,
    ) -> None:
        """Initialise the helper.

        Args:
            db_path: Path to the database file.
            init: Optional schema-initialiser run on every connection open
                (idempotent ``CREATE TABLE IF NOT EXISTS`` statements).
            wal: Enable WAL journal mode (default True).
            row_factory: Row factory (default :class:`sqlite3.Row`).
            check_same_thread: Passed to :func:`sqlite3.connect` (default False).
            create_parents: Create the parent directory if missing (default True).
        """
        self.db_path = db_path
        self._init = init
        self._wal = wal
        self._row_factory = row_factory
        self._check_same_thread = check_same_thread
        self._create_parents = create_parents

    def connect(self, *, with_schema: bool = True) -> AbstractContextManager[sqlite3.Connection]:
        """Return a context manager yielding a managed connection.

        Args:
            with_schema: Run the configured ``init`` schema-initialiser on open
                (default True). Pass ``False`` for a raw connection that skips
                schema creation — e.g. a migration that must inspect the
                existing schema before any table is created.

        Returns:
            A context manager (see :func:`sqlite_connection`).
        """
        return sqlite_connection(
            self.db_path,
            init=self._init if with_schema else None,
            wal=self._wal,
            row_factory=self._row_factory,
            check_same_thread=self._check_same_thread,
            create_parents=self._create_parents,
        )

    def connect_raw(self) -> AbstractContextManager[sqlite3.Connection]:
        """Return a managed connection WITHOUT running the schema-initialiser.

        Shorthand for ``connect(with_schema=False)``, matching the
        ``_raw_db`` / ``_db`` split used in ``dashboard/src/profiles/db.py``.
        """
        return self.connect(with_schema=False)
