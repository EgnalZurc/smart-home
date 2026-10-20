"""Unit tests for api/auth/validation.py — Input validation models."""

import pytest
from pydantic import ValidationError

from api.auth.validation import CreateUserRequest, UpdateUserRequest


# ---------------------------------------------------------------------------
# TestCreateUserRequest
# ---------------------------------------------------------------------------


class TestCreateUserRequest:
    """Tests for CreateUserRequest validation."""

    def test_valid_user_creation(self):
        """Accepts valid username, password, display_name."""
        req = CreateUserRequest(
            username="alice123",
            password="securepass",
            display_name="Alice Smith",
        )
        assert req.username == "alice123"
        assert req.password == "securepass"
        assert req.display_name == "Alice Smith"

    def test_username_normalized_to_lowercase(self):
        """Username is normalized to lowercase."""
        req = CreateUserRequest(username="AliceUser", password="securepass")
        assert req.username == "aliceuser"

    def test_username_strips_whitespace(self):
        """Username strips leading/trailing whitespace."""
        req = CreateUserRequest(username="  bob  ", password="securepass")
        assert req.username == "bob"

    def test_username_min_length(self):
        """Rejects username shorter than 3 chars."""
        with pytest.raises(ValidationError) as exc:
            CreateUserRequest(username="ab", password="securepass")
        assert "username" in str(exc.value).lower()

    def test_username_max_length(self):
        """Rejects username longer than 32 chars."""
        with pytest.raises(ValidationError) as exc:
            CreateUserRequest(username="a" * 33, password="securepass")
        assert "username" in str(exc.value).lower()

    def test_username_must_start_with_letter(self):
        """Rejects username starting with number."""
        with pytest.raises(ValidationError) as exc:
            CreateUserRequest(username="123user", password="securepass")
        assert "start with a letter" in str(exc.value).lower()

    def test_username_alphanumeric_underscore_only(self):
        """Rejects username with invalid characters."""
        with pytest.raises(ValidationError) as exc:
            CreateUserRequest(username="user@name", password="securepass")
        assert "letters, numbers, and underscores" in str(exc.value).lower()

    def test_username_allows_underscore(self):
        """Accepts username with underscore."""
        req = CreateUserRequest(username="user_name", password="securepass")
        assert req.username == "user_name"

    def test_password_min_length(self):
        """Rejects password shorter than 8 chars."""
        with pytest.raises(ValidationError) as exc:
            CreateUserRequest(username="alice", password="short")
        assert "8 characters" in str(exc.value).lower()

    def test_password_max_length(self):
        """Rejects password longer than 128 chars."""
        with pytest.raises(ValidationError) as exc:
            CreateUserRequest(username="alice", password="x" * 129)
        assert "128 characters" in str(exc.value).lower()

    def test_password_complexity_requirement(self):
        """Rejects password with less than 3 different characters."""
        with pytest.raises(ValidationError) as exc:
            CreateUserRequest(username="alice", password="aaaaaaaa")
        assert "3 different characters" in str(exc.value).lower()

    def test_display_name_optional(self):
        """Display name is optional, defaults to empty string."""
        req = CreateUserRequest(username="alice", password="securepass")
        assert req.display_name == ""

    def test_display_name_stripped(self):
        """Display name is stripped of whitespace."""
        req = CreateUserRequest(
            username="alice",
            password="securepass",
            display_name="  Alice  ",
        )
        assert req.display_name == "Alice"

    def test_display_name_max_length(self):
        """Rejects display name longer than 64 chars."""
        long_name = "A" * 100
        with pytest.raises(ValidationError) as exc:
            CreateUserRequest(
                username="alice",
                password="securepass",
                display_name=long_name,
            )
        assert "64 characters" in str(exc.value).lower()

    def test_email_optional(self):
        """Email is optional."""
        req = CreateUserRequest(username="alice", password="securepass")
        assert req.email is None

    def test_email_valid_format(self):
        """Accepts valid email format."""
        req = CreateUserRequest(
            username="alice",
            password="securepass",
            email="alice@example.com",
        )
        assert req.email == "alice@example.com"

    def test_email_invalid_format_rejected(self):
        """Rejects invalid email format."""
        with pytest.raises(ValidationError) as exc:
            CreateUserRequest(
                username="alice",
                password="securepass",
                email="not-an-email",
            )
        assert "email" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# TestUpdateUserRequest
# ---------------------------------------------------------------------------


class TestUpdateUserRequest:
    """Tests for UpdateUserRequest validation."""

    def test_all_fields_optional(self):
        """All fields are optional."""
        req = UpdateUserRequest()
        assert req.display_name is None
        assert req.icon is None
        assert req.password is None

    def test_update_display_name(self):
        """Can update display name."""
        req = UpdateUserRequest(display_name="New Name")
        assert req.display_name == "New Name"

    def test_display_name_stripped(self):
        """Display name is stripped of whitespace."""
        req = UpdateUserRequest(display_name="  Padded Name  ")
        assert req.display_name == "Padded Name"

    def test_display_name_max_length(self):
        """Rejects display name longer than 64 chars."""
        with pytest.raises(ValidationError) as exc:
            UpdateUserRequest(display_name="X" * 100)
        assert "64 characters" in str(exc.value).lower()

    def test_update_icon(self):
        """Can update icon."""
        req = UpdateUserRequest(icon="🏠")
        assert req.icon == "🏠"

    def test_icon_empty_string_becomes_none(self):
        """Empty icon string becomes None."""
        req = UpdateUserRequest(icon="")
        assert req.icon is None

    def test_icon_max_length(self):
        """Rejects icon longer than 256 chars."""
        with pytest.raises(ValidationError) as exc:
            UpdateUserRequest(icon="x" * 300)
        assert "256 characters" in str(exc.value).lower()

    def test_update_password(self):
        """Can update password."""
        req = UpdateUserRequest(password="newpassword123")
        assert req.password == "newpassword123"

    def test_password_min_length(self):
        """Rejects password shorter than 8 chars."""
        with pytest.raises(ValidationError) as exc:
            UpdateUserRequest(password="short")
        assert "8 characters" in str(exc.value).lower()

    def test_password_max_length(self):
        """Rejects password longer than 128 chars."""
        with pytest.raises(ValidationError) as exc:
            UpdateUserRequest(password="x" * 129)
        assert "128 characters" in str(exc.value).lower()

    def test_password_complexity(self):
        """Rejects password with less than 3 different characters."""
        with pytest.raises(ValidationError) as exc:
            UpdateUserRequest(password="bbbbbbbb")
        assert "3 different characters" in str(exc.value).lower()

    def test_password_none_is_valid(self):
        """None password is valid (no update)."""
        req = UpdateUserRequest(password=None)
        assert req.password is None
