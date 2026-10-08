"""Tests for the high-risk schema migrations in ``profiles/db.py``.

The migration helpers upgrade an on-disk SQLite database from the legacy
name-based schema (``profiles`` keyed by ``name``, ``user_profiles`` with a
``profile`` name column) to the current ID-based schema (UUID primary keys and a
``profile_id`` foreign column). They run exactly once per deployment, in place,
on real user data — so a regression silently corrupts or drops profile
assignments. These tests exercise:

* ``_migrate_profiles_table``        — old → new profiles schema
* ``_migrate_user_profiles_table``   — old → new user_profiles schema
* ``_ensure_builtin_profiles``       — idempotent seeding of built-ins
* ``init_database``                  — the full orchestration end-to-end

Every test uses the shared ``temp_auth_db`` fixture (see ``conftest.py``), which
points ``profiles.db.AUTH_DB_PATH`` at a throwaway SQLite file and closes WAL
handles deterministically on teardown. Behaviour under test is unchanged; this
module only adds coverage.
"""

import sqlite3
import uuid
from pathlib import Path

from profiles import db
from profiles.constants import (
    BUILTIN_NAME_TO_ID,
    BUILTIN_PROFILES,
    DEFAULT_PROFILE_ID,
)


# ---------------------------------------------------------------------------
# Helpers for building legacy-schema databases
# ---------------------------------------------------------------------------
def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a bare connection to the test DB (row access by name)."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _create_old_profiles_table(db_path: Path, *, with_builtin: bool, rows):
    """Create the LEGACY name-based ``profiles`` table and insert ``rows``.

    ``with_builtin`` toggles the extra ``builtin`` column that an even older
    schema carried. ``rows`` is a list of tuples matching the column order.
    """
    conn = _connect(db_path)
    try:
        if with_builtin:
            conn.execute(
                """
                CREATE TABLE profiles (
                    name        TEXT PRIMARY KEY,
                    level       INTEGER NOT NULL,
                    description TEXT DEFAULT '',
                    builtin     INTEGER DEFAULT 0
                )
                """
            )
            conn.executemany(
                "INSERT INTO profiles (name, level, description, builtin) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
        else:
            conn.execute(
                """
                CREATE TABLE profiles (
                    name        TEXT PRIMARY KEY,
                    level       INTEGER NOT NULL,
                    description TEXT DEFAULT ''
                )
                """
            )
            conn.executemany(
                "INSERT INTO profiles (name, level, description) VALUES (?, ?, ?)",
                rows,
            )
        conn.commit()
    finally:
        conn.close()


def _create_old_user_profiles_table(db_path: Path, rows):
    """Create the LEGACY name-based ``user_profiles`` table and insert ``rows``."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE user_profiles (
                username TEXT NOT NULL,
                profile  TEXT NOT NULL,
                PRIMARY KEY (username, profile)
            )
            """
        )
        conn.executemany(
            "INSERT INTO user_profiles (username, profile) VALUES (?, ?)", rows
        )
        conn.commit()
    finally:
        conn.close()


def _table_columns(db_path: Path, table: str) -> set[str]:
    conn = _connect(db_path)
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cur.fetchall()}
    finally:
        conn.close()


def _table_exists(db_path: Path, table: str) -> bool:
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def _fetch_profiles(db_path: Path) -> dict[str, sqlite3.Row]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, level, description, protected FROM profiles"
        ).fetchall()
        return {row["name"]: row for row in rows}
    finally:
        conn.close()


def _fetch_user_profiles(db_path: Path) -> list[sqlite3.Row]:
    conn = _connect(db_path)
    try:
        return conn.execute("SELECT username, profile_id FROM user_profiles").fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# _migrate_profiles_table
# ---------------------------------------------------------------------------
class TestMigrateProfilesTable:
    """Legacy name-based ``profiles`` → ID-based schema."""

    def test_noop_when_table_absent(self, temp_auth_db):
        """No profiles table yet → migration is a safe no-op (nothing created)."""
        db._migrate_profiles_table()
        assert not _table_exists(temp_auth_db, "profiles")

    def test_noop_when_already_new_schema(self, temp_auth_db):
        """A table already keyed by ``id`` must be left completely untouched."""
        # _open_db creates the new (id-based) schema.
        conn = db._open_db()
        pid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO profiles (id, name, level, description, protected) "
            "VALUES (?, ?, ?, ?, 0)",
            (pid, "KEEPME", 2, "unchanged"),
        )
        conn.commit()
        conn.close()

        db._migrate_profiles_table()

        profiles = _fetch_profiles(temp_auth_db)
        assert set(profiles) == {"KEEPME"}
        assert profiles["KEEPME"]["id"] == pid
        assert profiles["KEEPME"]["description"] == "unchanged"

    def test_happy_path_builtin_profiles_get_known_ids(self, temp_auth_db):
        """Built-in names migrate to their canonical UUIDs and protected flags."""
        _create_old_profiles_table(
            temp_auth_db,
            with_builtin=False,
            rows=[
                ("SUPER", 0, "admin"),
                ("GAMER", 3, "gaming"),
            ],
        )

        db._migrate_profiles_table()

        profiles = _fetch_profiles(temp_auth_db)
        assert "id" in _table_columns(temp_auth_db, "profiles")

        assert profiles["SUPER"]["id"] == BUILTIN_NAME_TO_ID["SUPER"]
        assert profiles["SUPER"]["level"] == 0
        # SUPER is protected in the registry → protected flag preserved on migrate.
        assert profiles["SUPER"]["protected"] == 1

        assert profiles["GAMER"]["id"] == BUILTIN_NAME_TO_ID["GAMER"]
        assert profiles["GAMER"]["protected"] == 0

    def test_happy_path_custom_profile_gets_generated_uuid(self, temp_auth_db):
        """An unknown (custom) name gets a fresh UUID and protected=0."""
        _create_old_profiles_table(
            temp_auth_db,
            with_builtin=False,
            rows=[("CUSTOM_ONE", 2, "a custom profile")],
        )

        db._migrate_profiles_table()

        profiles = _fetch_profiles(temp_auth_db)
        row = profiles["CUSTOM_ONE"]
        # Not a built-in id, but a valid UUID.
        assert row["id"] not in BUILTIN_PROFILES
        parsed = uuid.UUID(row["id"])
        assert str(parsed) == row["id"]
        assert row["level"] == 2
        assert row["description"] == "a custom profile"
        assert row["protected"] == 0

    def test_migrates_old_schema_with_builtin_column(self, temp_auth_db):
        """The even-older schema carrying a ``builtin`` column migrates cleanly."""
        _create_old_profiles_table(
            temp_auth_db,
            with_builtin=True,
            rows=[
                ("SUPER", 0, "admin", 1),
                ("CUSTOM_TWO", 1, "custom", 0),
            ],
        )

        db._migrate_profiles_table()

        cols = _table_columns(temp_auth_db, "profiles")
        assert "id" in cols
        assert "builtin" not in cols  # dropped by the new schema

        profiles = _fetch_profiles(temp_auth_db)
        assert profiles["SUPER"]["id"] == BUILTIN_NAME_TO_ID["SUPER"]
        assert profiles["SUPER"]["protected"] == 1
        assert profiles["CUSTOM_TWO"]["id"] not in BUILTIN_PROFILES
        assert profiles["CUSTOM_TWO"]["protected"] == 0

    def test_null_description_becomes_empty_string(self, temp_auth_db):
        """A NULL legacy description is normalised to '' (not NULL) on migrate."""
        conn = _connect(temp_auth_db)
        conn.execute(
            "CREATE TABLE profiles (name TEXT PRIMARY KEY, level INTEGER NOT NULL, "
            "description TEXT)"
        )
        conn.execute(
            "INSERT INTO profiles (name, level, description) VALUES (?, ?, ?)",
            ("CUSTOM_NULL", 1, None),
        )
        conn.commit()
        conn.close()

        db._migrate_profiles_table()

        profiles = _fetch_profiles(temp_auth_db)
        assert profiles["CUSTOM_NULL"]["description"] == ""

    def test_idempotent_second_run_is_noop(self, temp_auth_db):
        """Running the migration twice leaves identical data (ID stays stable)."""
        _create_old_profiles_table(
            temp_auth_db,
            with_builtin=False,
            rows=[("CUSTOM_IDEM", 2, "x")],
        )

        db._migrate_profiles_table()
        first = _fetch_profiles(temp_auth_db)
        first_id = first["CUSTOM_IDEM"]["id"]

        db._migrate_profiles_table()  # second run: already id-based → no-op
        second = _fetch_profiles(temp_auth_db)

        assert second["CUSTOM_IDEM"]["id"] == first_id
        assert len(second) == 1


# ---------------------------------------------------------------------------
# _migrate_user_profiles_table
# ---------------------------------------------------------------------------
class TestMigrateUserProfilesTable:
    """Legacy name-based ``user_profiles`` → ``profile_id`` schema."""

    def test_noop_when_table_absent(self, temp_auth_db):
        db._migrate_user_profiles_table()
        assert not _table_exists(temp_auth_db, "user_profiles")

    def test_noop_when_already_new_schema(self, temp_auth_db):
        """A table already carrying ``profile_id`` is left untouched."""
        conn = _connect(temp_auth_db)
        conn.execute(
            "CREATE TABLE user_profiles (username TEXT NOT NULL, "
            "profile_id TEXT NOT NULL, PRIMARY KEY (username, profile_id))"
        )
        conn.execute(
            "INSERT INTO user_profiles (username, profile_id) VALUES (?, ?)",
            ("alice", BUILTIN_NAME_TO_ID["SUPER"]),
        )
        conn.commit()
        conn.close()

        db._migrate_user_profiles_table()

        rows = _fetch_user_profiles(temp_auth_db)
        assert len(rows) == 1
        assert rows[0]["username"] == "alice"
        assert rows[0]["profile_id"] == BUILTIN_NAME_TO_ID["SUPER"]

    def test_noop_on_unknown_schema(self, temp_auth_db):
        """A table with neither ``profile`` nor ``profile_id`` is left as-is."""
        conn = _connect(temp_auth_db)
        conn.execute(
            "CREATE TABLE user_profiles (username TEXT NOT NULL, something_else TEXT)"
        )
        conn.execute(
            "INSERT INTO user_profiles (username, something_else) VALUES (?, ?)",
            ("bob", "mystery"),
        )
        conn.commit()
        conn.close()

        db._migrate_user_profiles_table()

        cols = _table_columns(temp_auth_db, "user_profiles")
        assert cols == {"username", "something_else"}

    def test_happy_path_builtin_name_resolves_to_id(self, temp_auth_db):
        """A built-in profile NAME is mapped to its canonical ID."""
        _create_old_user_profiles_table(
            temp_auth_db,
            rows=[("egnal", "SUPER"), ("virchi", "FAMILIA_PRINCIPAL")],
        )

        db._migrate_user_profiles_table()

        assert "profile_id" in _table_columns(temp_auth_db, "user_profiles")
        rows = {
            r["username"]: r["profile_id"] for r in _fetch_user_profiles(temp_auth_db)
        }
        assert rows["egnal"] == BUILTIN_NAME_TO_ID["SUPER"]
        assert rows["virchi"] == BUILTIN_NAME_TO_ID["FAMILIA_PRINCIPAL"]

    def test_custom_profile_name_resolved_via_profiles_table(self, temp_auth_db):
        """A custom (non-built-in) name is resolved by looking it up in profiles."""
        custom_id = str(uuid.uuid4())
        conn = _connect(temp_auth_db)
        # New-schema profiles table containing a custom profile by name.
        conn.execute(
            "CREATE TABLE profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
            "level INTEGER NOT NULL, description TEXT DEFAULT '', protected INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO profiles (id, name, level) VALUES (?, ?, ?)",
            (custom_id, "MY_CUSTOM", 2),
        )
        conn.commit()
        conn.close()

        _create_old_user_profiles_table(temp_auth_db, rows=[("carol", "MY_CUSTOM")])

        db._migrate_user_profiles_table()

        rows = {
            r["username"]: r["profile_id"] for r in _fetch_user_profiles(temp_auth_db)
        }
        assert rows["carol"] == custom_id

    def test_unknown_profile_falls_back_to_default(self, temp_auth_db):
        """An unresolvable profile name falls back to DEFAULT_PROFILE_ID.

        A ``profiles`` table exists (as it always does after
        ``_migrate_profiles_table`` runs first), but it does not contain the
        referenced name, so the lookup finds no row and the code defaults.
        """
        # Empty new-schema profiles table: the name lookup will miss.
        conn = _connect(temp_auth_db)
        conn.execute(
            "CREATE TABLE profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
            "level INTEGER NOT NULL, description TEXT DEFAULT '', protected INTEGER DEFAULT 0)"
        )
        conn.commit()
        conn.close()

        _create_old_user_profiles_table(temp_auth_db, rows=[("dave", "GHOST_PROFILE")])

        db._migrate_user_profiles_table()

        rows = {
            r["username"]: r["profile_id"] for r in _fetch_user_profiles(temp_auth_db)
        }
        assert rows["dave"] == DEFAULT_PROFILE_ID

    def test_idempotent_second_run_is_noop(self, temp_auth_db):
        _create_old_user_profiles_table(temp_auth_db, rows=[("egnal", "SUPER")])

        db._migrate_user_profiles_table()
        first = _fetch_user_profiles(temp_auth_db)

        db._migrate_user_profiles_table()
        second = _fetch_user_profiles(temp_auth_db)

        assert len(first) == len(second) == 1
        assert second[0]["profile_id"] == BUILTIN_NAME_TO_ID["SUPER"]


# ---------------------------------------------------------------------------
# _ensure_builtin_profiles
# ---------------------------------------------------------------------------
class TestEnsureBuiltinProfiles:
    def test_seeds_all_builtins(self, temp_auth_db):
        db._ensure_builtin_profiles()

        profiles = _fetch_profiles(temp_auth_db)
        for pid, spec in BUILTIN_PROFILES.items():
            name = spec["name"]
            assert name in profiles
            assert profiles[name]["id"] == pid
            assert profiles[name]["level"] == spec["level"]
            assert bool(profiles[name]["protected"]) is spec["protected"]

    def test_idempotent_does_not_duplicate(self, temp_auth_db):
        db._ensure_builtin_profiles()
        db._ensure_builtin_profiles()

        profiles = _fetch_profiles(temp_auth_db)
        assert len(profiles) == len(BUILTIN_PROFILES)

    def test_preserves_existing_custom_profiles(self, temp_auth_db):
        """Seeding built-ins must not clobber a pre-existing custom profile."""
        custom_id = db.create_profile("MY_APP_PROFILE", 2, "keep me")

        db._ensure_builtin_profiles()

        profiles = _fetch_profiles(temp_auth_db)
        assert "MY_APP_PROFILE" in profiles
        assert profiles["MY_APP_PROFILE"]["id"] == custom_id
        # built-ins also present alongside the custom one.
        assert len(profiles) == len(BUILTIN_PROFILES) + 1


# ---------------------------------------------------------------------------
# init_database (full orchestration)
# ---------------------------------------------------------------------------
class TestInitDatabase:
    def test_fresh_database_seeds_builtins_only(self, temp_auth_db):
        """On a brand-new DB, init just creates schema + seeds built-ins."""
        db.init_database()

        profiles = _fetch_profiles(temp_auth_db)
        assert len(profiles) == len(BUILTIN_PROFILES)
        assert "profile_id" in _table_columns(temp_auth_db, "user_profiles")

    def test_full_legacy_upgrade_end_to_end(self, temp_auth_db):
        """Legacy profiles AND user_profiles migrate, then built-ins are seeded."""
        _create_old_profiles_table(
            temp_auth_db,
            with_builtin=False,
            rows=[
                ("SUPER", 0, "admin"),
                ("CUSTOM_TEAM", 2, "a team"),
            ],
        )
        _create_old_user_profiles_table(
            temp_auth_db,
            rows=[
                ("egnal", "SUPER"),
                ("mallory", "CUSTOM_TEAM"),
            ],
        )

        db.init_database()

        # profiles upgraded to id-based and built-ins seeded (SUPER already there).
        profiles = _fetch_profiles(temp_auth_db)
        assert profiles["SUPER"]["id"] == BUILTIN_NAME_TO_ID["SUPER"]
        assert "CUSTOM_TEAM" in profiles
        custom_id = profiles["CUSTOM_TEAM"]["id"]
        # Every built-in now present.
        for spec in BUILTIN_PROFILES.values():
            assert spec["name"] in profiles

        # user_profiles upgraded to profile_id, names resolved to ids.
        user_rows = {
            r["username"]: r["profile_id"] for r in _fetch_user_profiles(temp_auth_db)
        }
        assert user_rows["egnal"] == BUILTIN_NAME_TO_ID["SUPER"]
        assert user_rows["mallory"] == custom_id

    def test_idempotent_second_init_is_stable(self, temp_auth_db):
        """Running init twice must not duplicate rows or change ids."""
        _create_old_profiles_table(
            temp_auth_db, with_builtin=False, rows=[("CUSTOM_X", 1, "x")]
        )
        _create_old_user_profiles_table(temp_auth_db, rows=[("egnal", "SUPER")])

        db.init_database()
        first_profiles = _fetch_profiles(temp_auth_db)
        first_users = _fetch_user_profiles(temp_auth_db)

        db.init_database()
        second_profiles = _fetch_profiles(temp_auth_db)
        second_users = _fetch_user_profiles(temp_auth_db)

        assert len(first_profiles) == len(second_profiles)
        assert first_profiles["CUSTOM_X"]["id"] == second_profiles["CUSTOM_X"]["id"]
        assert len(first_users) == len(second_users) == 1

    def test_migrated_data_readable_through_public_api(self, temp_auth_db):
        """End-to-end: after init, the public getters return the migrated data."""
        _create_old_profiles_table(
            temp_auth_db, with_builtin=False, rows=[("CUSTOM_API", 2, "api test")]
        )
        _create_old_user_profiles_table(temp_auth_db, rows=[("erin", "CUSTOM_API")])

        db.init_database()

        all_profiles = db.get_all_profiles()
        custom = db.get_profile_by_name("CUSTOM_API")
        assert custom is not None
        assert custom["id"] in all_profiles
        assert custom["level"] == 2

        assigned = db.get_user_profiles("erin")
        assert assigned == [custom["id"]]
