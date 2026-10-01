"""Unit tests for gifts_controller module."""


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
        """update_gift should return None for non-existent gift."""
        from gifts_controller import update_gift

        result = update_gift("nonexistent", {"name": "New"})
        assert result is None

    def test_delete_gift_removes_gift(self, tmp_data_dir):
        """delete_gift should remove an existing gift."""
        from gifts_controller import add_gift, delete_gift, get_gift

        gift = add_gift({"name": "To Delete"})
        result = delete_gift(gift["id"])

        assert result is True
        assert get_gift(gift["id"]) is None

    def test_delete_gift_returns_false_for_missing(self, tmp_data_dir):
        """delete_gift should return False for non-existent gift."""
        from gifts_controller import delete_gift

        result = delete_gift("nonexistent")
        assert result is False


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
        """reserve_gift should fail for non-existent gift."""
        from gifts_controller import reserve_gift

        result = reserve_gift("nonexistent", "token", "User")

        assert result["status"] == "error"
        assert "no encontrado" in result["message"]

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
        """toggle_gift_visibility should fail for non-existent gift."""
        from gifts_controller import toggle_gift_visibility

        result = toggle_gift_visibility("nonexistent")

        assert result["status"] == "error"


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
