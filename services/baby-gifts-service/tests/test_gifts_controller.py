"""Unit tests for gifts_controller module."""

import pytest


class TestGiftsCRUD:
    """Tests for gift CRUD operations."""

    def test_add_gift_creates_id(self, tmp_data_dir):
        """add_gift should create a unique gift ID."""
        from gifts_controller import add_gift

        gift = add_gift({"name": "Test Gift"})

        assert gift["id"].startswith("g_")
        assert gift["name"] == "Test Gift"
        assert gift["reserved_by"] is None

    def test_add_gift_sets_defaults(self, tmp_data_dir):
        """add_gift should set default values for optional fields."""
        from gifts_controller import add_gift

        gift = add_gift({"name": "Minimal Gift"})

        assert gift["description"] == ""
        assert gift["url"] == ""
        assert gift["price_range"] == ""
        assert gift["priority"] == 2
        assert gift["hidden"] is False

    def test_get_gift_returns_existing(self, tmp_data_dir):
        """get_gift should return an existing gift."""
        from gifts_controller import add_gift, get_gift

        created = add_gift({"name": "Findable Gift"})
        found = get_gift(created["id"])

        assert found is not None
        assert found["name"] == "Findable Gift"

    def test_get_gift_returns_none_for_missing(self, tmp_data_dir):
        """get_gift should return None for non-existent gift."""
        from gifts_controller import get_gift

        result = get_gift("nonexistent_id")
        assert result is None

    def test_update_gift_modifies_fields(self, tmp_data_dir):
        """update_gift should modify specified fields."""
        from gifts_controller import add_gift, update_gift

        gift = add_gift({"name": "Original Name"})
        updated = update_gift(gift["id"], {"name": "Updated Name", "priority": 1})

        assert updated is not None
        assert updated["name"] == "Updated Name"
        assert updated["priority"] == 1

    def test_update_gift_returns_none_for_missing(self, tmp_data_dir):
        """update_gift should return None for non-existent gift (valid format)."""
        from gifts_controller import update_gift

        # Use a valid format (13+ digit timestamp + 8 hex chars) that doesn't exist
        result = update_gift("g_9999999999999_abcd1234", {"name": "New"})
        assert result is None

    def test_update_gift_invalid_format_returns_400(self, tmp_data_dir):
        """update_gift should return 400 for invalid gift_id format."""
        from gifts_controller import update_gift

        result = update_gift("invalid-format", {"name": "New"})

        assert isinstance(result, tuple)
        assert result[0] is None
        assert result[1] == 400
        assert "Invalid gift_id format" in result[2]

    def test_update_gift_empty_id_returns_400(self, tmp_data_dir):
        """update_gift should return 400 for empty gift_id."""
        from gifts_controller import update_gift

        result = update_gift("", {"name": "New"})

        assert isinstance(result, tuple)
        assert result[0] is None
        assert result[1] == 400
        assert "Invalid gift_id format" in result[2]

    def test_update_gift_none_id_returns_400(self, tmp_data_dir):
        """update_gift should return 400 for None gift_id."""
        from gifts_controller import update_gift

        result = update_gift(None, {"name": "New"})

        assert isinstance(result, tuple)
        assert result[0] is None
        assert result[1] == 400

    def test_update_gift_accepts_uuid_format(self, tmp_data_dir):
        """update_gift should accept valid UUID format."""
        from gifts_controller import add_gift, update_gift

        # Create a gift to ensure data file exists
        add_gift({"name": "Test"})

        # Valid UUID format should pass validation but return None (not found)
        result = update_gift("550e8400-e29b-41d4-a716-446655440000", {"name": "New"})
        assert result is None  # Valid format, but gift doesn't exist

    def test_update_gift_valid_id_not_found_returns_none(self, tmp_data_dir):
        """update_gift with valid format but non-existent ID returns None (404)."""
        from gifts_controller import update_gift

        result = update_gift("g_9999999999999_deadbeef", {"name": "New"})
        assert result is None

    def test_delete_gift_removes_gift(self, tmp_data_dir):
        """delete_gift should remove an existing gift."""
        from gifts_controller import add_gift, delete_gift, get_gift

        gift = add_gift({"name": "To Delete"})
        result = delete_gift(gift["id"])

        assert result is True
        assert get_gift(gift["id"]) is None

    def test_delete_gift_returns_false_for_missing(self, tmp_data_dir):
        """delete_gift should return False for non-existent gift (valid format)."""
        from gifts_controller import delete_gift

        # Use valid format that doesn't exist
        result = delete_gift("g_9999999999999_deadbeef")
        assert result is False

    def test_delete_gift_returns_false_for_invalid_id(self, tmp_data_dir):
        """delete_gift should return False for invalid gift_id format."""
        from gifts_controller import delete_gift

        result = delete_gift("nonexistent")
        assert result is False

    def test_delete_gift_rejects_path_traversal(self, tmp_data_dir):
        """delete_gift should reject path traversal attempts."""
        from gifts_controller import delete_gift

        result = delete_gift("../../../etc/passwd")
        assert result is False


class TestGiftIdValidation:
    """Tests for gift_id validation helper."""

    def test_validate_gift_id_accepts_valid_uuid(self, tmp_data_dir):
        """_validate_gift_id should return True for valid UUID."""
        from gifts_controller import _validate_gift_id

        assert _validate_gift_id("550e8400-e29b-41d4-a716-446655440000") is True
        assert _validate_gift_id("6ba7b810-9dad-11d1-80b4-00c04fd430c8") is True

    def test_validate_gift_id_accepts_native_format(self, tmp_data_dir):
        """_validate_gift_id should return True for native g_timestamp_hex format."""
        from gifts_controller import _validate_gift_id

        # Valid native format: g_<13+ digit timestamp>_<8 hex chars>
        assert _validate_gift_id("g_1729432800000_a1b2c3d4") is True
        assert _validate_gift_id("g_9999999999999_deadbeef") is True
        assert _validate_gift_id("g_1234567890123_00000000") is True

    def test_validate_gift_id_rejects_invalid(self, tmp_data_dir):
        """_validate_gift_id should return False for invalid formats."""
        from gifts_controller import _validate_gift_id

        assert _validate_gift_id("not-a-uuid") is False
        # Short timestamp (less than 13 digits)
        assert _validate_gift_id("g_12345_abc") is False
        # Short hex (less than 8 chars)
        assert _validate_gift_id("g_1234567890123_abc") is False
        assert _validate_gift_id("") is False

    def test_validate_gift_id_handles_none(self, tmp_data_dir):
        """_validate_gift_id should handle None gracefully."""
        from gifts_controller import _validate_gift_id

        assert _validate_gift_id(None) is False

    def test_validate_gift_id_rejects_path_traversal(self, tmp_data_dir):
        """_validate_gift_id should reject path traversal attempts."""
        from gifts_controller import _validate_gift_id

        assert _validate_gift_id("../../../etc/passwd") is False
        assert _validate_gift_id("g_1234567890123/../../../etc") is False
        assert _validate_gift_id("..\\..\\windows\\system32") is False
        assert _validate_gift_id("/etc/passwd") is False
        assert _validate_gift_id("C:\\windows\\system32") is False

    def test_validate_gift_id_rejects_too_long(self, tmp_data_dir):
        """_validate_gift_id should reject excessively long IDs."""
        from gifts_controller import _validate_gift_id

        # Over 50 chars
        assert _validate_gift_id("g_" + "1" * 60 + "_abcd1234") is False
        assert _validate_gift_id("a" * 100) is False


class TestGiftReservations:
    """Tests for gift reservation operations."""

    def test_reserve_gift_marks_reserved(self, tmp_data_dir):
        """reserve_gift should mark a gift as reserved."""
        from gifts_controller import add_gift, reserve_gift

        gift = add_gift({"name": "Reservable Gift"})
        result = reserve_gift(gift["id"], "test_token", "Test User")

        assert result["status"] == "ok"
        assert result["gift"]["reserved_by"] == "test_token"
        assert result["gift"]["reserved_by_name"] == "Test User"
        assert result["gift"]["reserved_at"] is not None

    def test_reserve_already_reserved_fails(self, tmp_data_dir):
        """reserve_gift should fail for already reserved gift."""
        from gifts_controller import add_gift, reserve_gift

        gift = add_gift({"name": "Already Reserved"})
        reserve_gift(gift["id"], "first_token", "First User")
        result = reserve_gift(gift["id"], "second_token", "Second User")

        assert result["status"] == "error"
        assert "ya está reservado" in result["message"]

    def test_reserve_nonexistent_gift_fails(self, tmp_data_dir):
        """reserve_gift should fail for non-existent gift with valid ID format."""
        from gifts_controller import reserve_gift

        # Use valid format that doesn't exist
        result = reserve_gift("g_9999999999999_deadbeef", "token", "User")

        assert result["status"] == "error"
        assert "no encontrado" in result["message"]

    def test_reserve_invalid_gift_id_fails(self, tmp_data_dir):
        """reserve_gift should fail for invalid gift_id format."""
        from gifts_controller import reserve_gift

        result = reserve_gift("nonexistent", "token", "User")

        assert result["status"] == "error"
        assert "Invalid gift_id" in result["message"]

    def test_reserve_path_traversal_rejected(self, tmp_data_dir):
        """reserve_gift should reject path traversal attempts."""
        from gifts_controller import reserve_gift

        result = reserve_gift("../../../etc/passwd", "token", "User")

        assert result["status"] == "error"
        assert "Invalid gift_id" in result["message"]

    def test_unreserve_own_reservation_succeeds(self, tmp_data_dir):
        """unreserve_gift should succeed for own reservation."""
        from gifts_controller import add_gift, reserve_gift, unreserve_gift

        gift = add_gift({"name": "To Unreserve"})
        reserve_gift(gift["id"], "my_token", "Me")
        result = unreserve_gift(gift["id"], "my_token", is_admin=False)

        assert result["status"] == "ok"
        assert result["gift"]["reserved_by"] is None

    def test_unreserve_others_reservation_fails(self, tmp_data_dir):
        """unreserve_gift should fail for another user's reservation."""
        from gifts_controller import add_gift, reserve_gift, unreserve_gift

        gift = add_gift({"name": "Not Mine"})
        reserve_gift(gift["id"], "other_token", "Other User")
        result = unreserve_gift(gift["id"], "my_token", is_admin=False)

        assert result["status"] == "error"
        assert "no puedes cancelar" in result["message"].lower()

    def test_admin_can_unreserve_any(self, tmp_data_dir):
        """admin unreserve_gift should succeed for any reservation."""
        from gifts_controller import add_gift, reserve_gift, unreserve_gift

        gift = add_gift({"name": "Admin Override"})
        reserve_gift(gift["id"], "user_token", "User")
        result = unreserve_gift(gift["id"], "admin_token", is_admin=True)

        assert result["status"] == "ok"

    def test_unreserve_not_reserved_fails(self, tmp_data_dir):
        """unreserve_gift should fail for non-reserved gift."""
        from gifts_controller import add_gift, unreserve_gift

        gift = add_gift({"name": "Not Reserved"})
        result = unreserve_gift(gift["id"], "token", is_admin=False)

        assert result["status"] == "error"
        assert "no está reservado" in result["message"]

    def test_unreserve_invalid_gift_id_fails(self, tmp_data_dir):
        """unreserve_gift should fail for invalid gift_id format."""
        from gifts_controller import unreserve_gift

        result = unreserve_gift("nonexistent", "token", is_admin=False)

        assert result["status"] == "error"
        assert "Invalid gift_id" in result["message"]

    def test_unreserve_path_traversal_rejected(self, tmp_data_dir):
        """unreserve_gift should reject path traversal attempts."""
        from gifts_controller import unreserve_gift

        result = unreserve_gift("../../../etc/passwd", "token", is_admin=False)

        assert result["status"] == "error"
        assert "Invalid gift_id" in result["message"]


class TestGiftVisibility:
    """Tests for gift visibility toggle."""

    def test_toggle_visibility_hides_gift(self, tmp_data_dir):
        """toggle_gift_visibility should hide a visible gift."""
        from gifts_controller import add_gift, toggle_gift_visibility

        gift = add_gift({"name": "Visible Gift", "hidden": False})
        result = toggle_gift_visibility(gift["id"])

        assert result["status"] == "ok"
        assert result["hidden"] is True

    def test_toggle_visibility_shows_gift(self, tmp_data_dir):
        """toggle_gift_visibility should show a hidden gift."""
        from gifts_controller import add_gift, toggle_gift_visibility

        gift = add_gift({"name": "Hidden Gift"})
        toggle_gift_visibility(gift["id"])  # Hide it
        result = toggle_gift_visibility(gift["id"])  # Show it

        assert result["status"] == "ok"
        assert result["hidden"] is False

    def test_toggle_nonexistent_fails(self, tmp_data_dir):
        """toggle_gift_visibility should fail for non-existent gift (valid format)."""
        from gifts_controller import toggle_gift_visibility

        # Use valid format that doesn't exist
        result = toggle_gift_visibility("g_9999999999999_deadbeef")

        assert result["status"] == "error"
        assert "no encontrado" in result["message"]

    def test_toggle_invalid_gift_id_fails(self, tmp_data_dir):
        """toggle_gift_visibility should fail for invalid gift_id format."""
        from gifts_controller import toggle_gift_visibility

        result = toggle_gift_visibility("nonexistent")

        assert result["status"] == "error"
        assert "Invalid gift_id" in result["message"]

    def test_toggle_path_traversal_rejected(self, tmp_data_dir):
        """toggle_gift_visibility should reject path traversal attempts."""
        from gifts_controller import toggle_gift_visibility

        result = toggle_gift_visibility("../../../etc/passwd")

        assert result["status"] == "error"
        assert "Invalid gift_id" in result["message"]


class TestFamiliaUsers:
    """Tests for FAMILIA user detection."""

    def test_egnal_is_familia(self, tmp_data_dir):
        """egnal should be recognized as FAMILIA user."""
        from gifts_controller import is_familia_user

        assert is_familia_user("egnal") is True
        assert is_familia_user("EGNAL") is True

    def test_virchu_is_familia(self, tmp_data_dir):
        """virchu should be recognized as FAMILIA user."""
        from gifts_controller import is_familia_user

        assert is_familia_user("virchu") is True

    def test_other_users_not_familia(self, tmp_data_dir):
        """Other users should not be FAMILIA."""
        from gifts_controller import is_familia_user

        assert is_familia_user("guest") is False
        assert is_familia_user("admin") is False


class TestAtomicSave:
    """Tests that gifts.json is written atomically (crash-safe)."""

    def test_save_recovers_after_crash(self, tmp_data_dir):
        """A crash mid-write leaves the previous gifts.json intact.

        _save_gifts writes to a temp file and os.replace()s it into place. If
        json.dump blows up partway through, the real file must still hold the
        last good data (every reservation would otherwise be lost) and no stray
        .tmp file should remain.
        """
        from unittest.mock import patch

        import gifts_controller
        from gifts_controller import add_gift, get_gifts_data

        # Seed one good gift (written atomically).
        add_gift({"name": "Keep me"})
        good = get_gifts_data()
        assert len(good["gifts"]) == 1

        # Next save explodes partway through serialization.
        with patch.object(
            gifts_controller.json, "dump", side_effect=ValueError("boom")
        ):
            with pytest.raises(ValueError):
                add_gift({"name": "This write crashes"})

        # The previous good file survived and is still valid JSON.
        recovered = get_gifts_data()
        assert len(recovered["gifts"]) == 1
        assert recovered["gifts"][0]["name"] == "Keep me"
        # No leftover temp files in the data dir.
        assert not list(tmp_data_dir.glob(".gifts.json.*.tmp"))

    def test_save_persists_data(self, tmp_data_dir):
        """A normal save round-trips through the atomic writer."""
        from gifts_controller import add_gift, get_gifts_data

        add_gift({"name": "Alpha"})
        add_gift({"name": "Beta"})

        data = get_gifts_data()
        names = {g["name"] for g in data["gifts"]}
        assert names == {"Alpha", "Beta"}
        assert tmp_data_dir.joinpath("gifts.json").exists()



class TestInvitationRetryLimit:
    """Tests for invitation creation retry limit."""

    def test_create_invitation_retries_on_collision(self, tmp_data_dir):
        """create_invitation should retry on IntegrityError (token collision)."""
        from unittest.mock import MagicMock, patch

        import gifts_controller

        # Mock to fail twice then succeed
        call_count = 0
        original_execute = None

        def mock_execute(sql, params=None):
            nonlocal call_count
            if "INSERT INTO invitations" in sql:
                call_count += 1
                if call_count < 3:
                    import sqlite3

                    raise sqlite3.IntegrityError("UNIQUE constraint failed")
            return original_execute(sql, params) if params else original_execute(sql)

        # Create real connection and wrap its execute
        conn = gifts_controller._get_db()
        original_execute = conn.execute

        with patch.object(gifts_controller, "_get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_conn.execute = mock_execute
            mock_conn.commit = conn.commit
            mock_conn.close = conn.close
            mock_get_db.return_value = mock_conn

            result = gifts_controller.create_invitation("Retry Guest")

        assert result["status"] == "ok"
        assert call_count == 3  # Failed twice, succeeded on third

    def test_create_invitation_fails_after_max_retries(self, tmp_data_dir):
        """create_invitation should return error after MAX_INVITATION_RETRIES."""
        from unittest.mock import MagicMock, patch

        import sqlite3

        import gifts_controller

        with patch.object(gifts_controller, "_get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = sqlite3.IntegrityError(
                "UNIQUE constraint failed"
            )
            mock_get_db.return_value = mock_conn

            result = gifts_controller.create_invitation("Failing Guest")

        assert result["status"] == "error"
        assert "unique token" in result["message"].lower()

    def test_create_invitation_logs_error_on_max_retries(self, tmp_data_dir, caplog):
        """create_invitation should log error when max retries reached."""
        from unittest.mock import MagicMock, patch

        import sqlite3

        import gifts_controller

        with patch.object(gifts_controller, "_get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = sqlite3.IntegrityError(
                "UNIQUE constraint failed"
            )
            mock_get_db.return_value = mock_conn

            gifts_controller.create_invitation("Log Test Guest")

        assert "Failed to create invitation after 3 retries" in caplog.text
