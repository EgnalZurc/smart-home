"""Unit tests for api/auth_helpers.py."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

# We need to patch at the module level where the imports happen
# Since auth_helpers imports inside the function, we patch the modules directly


class TestRequireSuper:
    """Tests for require_super helper."""

    def test_returns_username_for_super_user(self):
        """Returns username when user has level 0 (SUPER)."""
        from api import auth_helpers

        mock_request = MagicMock()

        # Patch the modules that will be imported inside the function
        with patch.dict(
            "sys.modules",
            {
                "auth": MagicMock(get_current_user=MagicMock(return_value="admin")),
                "user_profiles": MagicMock(is_super=MagicMock(return_value=True)),
            },
        ):
            # Re-import to get fresh module with patched imports
            import importlib

            importlib.reload(auth_helpers)
            
            result = auth_helpers.require_super(mock_request)
            assert result == "admin"

    def test_raises_401_when_not_authenticated(self):
        """Raises 401 when no user is authenticated."""
        from api import auth_helpers

        mock_request = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "auth": MagicMock(get_current_user=MagicMock(return_value=None)),
                "user_profiles": MagicMock(),
            },
        ):
            import importlib

            importlib.reload(auth_helpers)

            with pytest.raises(HTTPException) as exc:
                auth_helpers.require_super(mock_request)

            assert exc.value.status_code == 401
            assert "Not authenticated" in exc.value.detail

    def test_raises_403_when_not_super(self):
        """Raises 403 when user is authenticated but not SUPER."""
        from api import auth_helpers

        mock_request = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "auth": MagicMock(
                    get_current_user=MagicMock(return_value="regular_user")
                ),
                "user_profiles": MagicMock(is_super=MagicMock(return_value=False)),
            },
        ):
            import importlib

            importlib.reload(auth_helpers)

            with pytest.raises(HTTPException) as exc:
                auth_helpers.require_super(mock_request)

            assert exc.value.status_code == 403
            assert "Admin access required" in exc.value.detail

    def test_calls_auth_modules_correctly(self):
        """Verifies correct calls to auth modules."""
        from api import auth_helpers

        mock_request = MagicMock()
        mock_get_user = MagicMock(return_value="testuser")
        mock_is_super = MagicMock(return_value=True)

        with patch.dict(
            "sys.modules",
            {
                "auth": MagicMock(get_current_user=mock_get_user),
                "user_profiles": MagicMock(is_super=mock_is_super),
            },
        ):
            import importlib

            importlib.reload(auth_helpers)

            auth_helpers.require_super(mock_request)

            mock_get_user.assert_called_once_with(mock_request)
            mock_is_super.assert_called_once_with("testuser")



class TestRequireAppWrite:
    """Tests for require_app_write helper."""

    def test_super_user_can_write_any_app(self):
        """SUPER (level 0) can write to any app."""
        from api import auth_helpers

        mock_request = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "auth": MagicMock(get_current_user=MagicMock(return_value="admin")),
                "user_profiles": MagicMock(get_effective_level=MagicMock(return_value=0)),
            },
        ):
            import importlib

            importlib.reload(auth_helpers)

            # SUPER can write to any app
            result = auth_helpers.require_app_write(mock_request, "ac")
            assert result == "admin"

            result = auth_helpers.require_app_write(mock_request, "portfolio")
            assert result == "admin"

    def test_level1_can_write_to_matching_app(self):
        """Level 1 user can write to apps where min_level <= 1 <= max_level."""
        from api import auth_helpers

        mock_request = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "auth": MagicMock(get_current_user=MagicMock(return_value="familia")),
                "user_profiles": MagicMock(get_effective_level=MagicMock(return_value=1)),
            },
        ):
            import importlib

            importlib.reload(auth_helpers)

            # ac has min_level=0, max_level=1, so level 1 can write
            result = auth_helpers.require_app_write(mock_request, "ac")
            assert result == "familia"

    def test_level1_cannot_write_to_super_only_app(self):
        """Level 1 user cannot write to SUPER-only apps (max_level=0)."""
        from api import auth_helpers

        mock_request = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "auth": MagicMock(get_current_user=MagicMock(return_value="familia")),
                "user_profiles": MagicMock(get_effective_level=MagicMock(return_value=1)),
            },
        ):
            import importlib

            importlib.reload(auth_helpers)

            # portfolio has min_level=0, max_level=0 (SUPER only)
            with pytest.raises(HTTPException) as exc:
                auth_helpers.require_app_write(mock_request, "portfolio")

            assert exc.value.status_code == 403
            assert "No write permission" in exc.value.detail

    def test_raises_401_when_not_authenticated(self):
        """Raises 401 when no user is authenticated."""
        from api import auth_helpers

        mock_request = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "auth": MagicMock(get_current_user=MagicMock(return_value=None)),
                "user_profiles": MagicMock(),
            },
        ):
            import importlib

            importlib.reload(auth_helpers)

            with pytest.raises(HTTPException) as exc:
                auth_helpers.require_app_write(mock_request, "ac")

            assert exc.value.status_code == 401

    def test_raises_403_for_unknown_app(self):
        """Raises 403 for unknown app key (defaults to SUPER-only)."""
        from api import auth_helpers

        mock_request = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "auth": MagicMock(get_current_user=MagicMock(return_value="familia")),
                "user_profiles": MagicMock(get_effective_level=MagicMock(return_value=1)),
            },
        ):
            import importlib

            importlib.reload(auth_helpers)

            with pytest.raises(HTTPException) as exc:
                auth_helpers.require_app_write(mock_request, "nonexistent_app")

            assert exc.value.status_code == 403
            assert "Unknown app" in exc.value.detail