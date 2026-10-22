"""Tests for migrations module whitelist validation."""

from __future__ import annotations

import pytest
from migrations import (
    ALLOWED_TABLES,
    COLUMN_NAME_PATTERN,
    validate_migration_params,
)


class TestAllowedTables:
    """Tests for the ALLOWED_TABLES whitelist."""

    def test_allowed_tables_contains_expected_tables(self) -> None:
        """Verify the whitelist contains the tables used in migrations."""
        expected = {"properties", "scored_properties", "telegram_chats", "alerts"}
        assert expected == ALLOWED_TABLES

    def test_allowed_tables_is_frozenset(self) -> None:
        """Whitelist should be immutable."""
        assert isinstance(ALLOWED_TABLES, frozenset)


class TestColumnNamePattern:
    """Tests for the column name validation pattern."""

    @pytest.mark.parametrize(
        "valid_column",
        [
            "id",
            "score_p11",
            "score_r18",
            "dismissed",
            "dismissed_at",
            "viewed",
            "viewed_at",
            "comment",
            "published_at",
            "has_ac",
            "terrain_m2",
            "garage_type",
            "habitability",
            "internet",
            "has_ac_preinstalled",
            "a",
            "a1",
            "a_",
            "a" * 64,  # max length
        ],
    )
    def test_valid_column_names(self, valid_column: str) -> None:
        """Valid column names should match the pattern."""
        assert COLUMN_NAME_PATTERN.match(valid_column) is not None

    @pytest.mark.parametrize(
        "invalid_column",
        [
            "",  # empty
            "1column",  # starts with digit
            "_column",  # starts with underscore
            "Column",  # uppercase
            "COLUMN",  # all uppercase
            "col-name",  # hyphen
            "col.name",  # dot
            "col name",  # space
            "col;DROP TABLE",  # SQL injection attempt
            "a" * 65,  # too long
        ],
    )
    def test_invalid_column_names(self, invalid_column: str) -> None:
        """Invalid column names should not match the pattern."""
        assert COLUMN_NAME_PATTERN.match(invalid_column) is None


class TestValidateMigrationParams:
    """Tests for validate_migration_params function."""

    def test_valid_params_passes(self) -> None:
        """Valid table and column should not raise."""
        # Should not raise
        validate_migration_params("properties", "new_column")
        validate_migration_params("scored_properties", "score_r1")
        validate_migration_params("telegram_chats", "username")
        validate_migration_params("alerts", "alert_type")

    def test_invalid_table_raises_valueerror(self) -> None:
        """Unknown table should raise ValueError."""
        with pytest.raises(ValueError, match="not in the allowed tables whitelist"):
            validate_migration_params("malicious_table", "valid_column")

    def test_sql_injection_table_raises_valueerror(self) -> None:
        """SQL injection in table name should raise ValueError."""
        with pytest.raises(ValueError, match="not in the allowed tables whitelist"):
            validate_migration_params("properties; DROP TABLE users--", "col")

    def test_invalid_column_raises_valueerror(self) -> None:
        """Invalid column name should raise ValueError."""
        with pytest.raises(ValueError, match="does not match allowed pattern"):
            validate_migration_params("properties", "Invalid_Column")

    def test_sql_injection_column_raises_valueerror(self) -> None:
        """SQL injection in column name should raise ValueError."""
        with pytest.raises(ValueError, match="does not match allowed pattern"):
            validate_migration_params("properties", "col; DROP TABLE users--")

    def test_empty_column_raises_valueerror(self) -> None:
        """Empty column name should raise ValueError."""
        with pytest.raises(ValueError, match="does not match allowed pattern"):
            validate_migration_params("properties", "")

    def test_column_starting_with_digit_raises_valueerror(self) -> None:
        """Column starting with digit should raise ValueError."""
        with pytest.raises(ValueError, match="does not match allowed pattern"):
            validate_migration_params("properties", "1invalid")
