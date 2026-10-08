"""Unit tests for api/auth/admin.py — Admin endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.auth.admin import router


# ---------------------------------------------------------------------------
# TestRouterRegistration
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    """Tests for router configuration."""

    def test_router_has_correct_prefix(self):
        """Router has /api/auth/admin prefix."""
        assert router.prefix == "/api/auth/admin"

    def test_router_has_admin_tag(self):
        """Router is tagged as Admin."""
        assert "Admin" in router.tags

    def test_all_endpoints_registered(self):
        """All expected endpoints are registered."""
        routes = [r.path for r in router.routes]
        expected = [
            "/api/auth/admin/users",
            "/api/auth/admin/users/{user_id}",
            "/api/auth/admin/users/{username}/profiles",
            "/api/auth/admin/users/{username}/profiles/{profile_id}",
            "/api/auth/admin/profiles",
            "/api/auth/admin/profiles/{profile_id}",
            "/api/auth/admin/users/{username}/profile",  # Legacy
        ]
        for route in expected:
            assert route in routes, f"Missing route: {route}"


# ---------------------------------------------------------------------------
# TestListUsers
# ---------------------------------------------------------------------------


class TestListUsers:
    """Tests for GET /admin/users."""

    @pytest.mark.asyncio
    async def test_returns_users_with_profiles(self):
        """Returns users list with profile details."""
        from api.auth.admin import list_users
        
        mock_request = MagicMock()
        
        with patch("api.auth.admin.require_super") as mock_require, \
             patch("api.auth.admin.auth_users") as mock_users, \
             patch("api.auth.admin.user_profiles") as mock_profiles:
            
            mock_require.return_value = "admin"
            mock_users.get_all_users.return_value = [
                {"id": "u1", "username": "alice", "display_name": "Alice", "icon": None}
            ]
            mock_profiles.get_user_profiles_detailed.return_value = [
                {"id": "p1", "name": "SUPER", "level": 0}
            ]
            mock_profiles.get_effective_level.return_value = 0

            result = await list_users(mock_request)

            assert len(result) == 1
            assert result[0]["username"] == "alice"
            assert result[0]["effective_level"] == 0

    @pytest.mark.asyncio
    async def test_requires_super_access(self):
        """Raises 403 if not SUPER."""
        from api.auth.admin import list_users
        
        mock_request = MagicMock()
        
        with patch("api.auth.admin.require_super") as mock:
            mock.side_effect = HTTPException(status_code=403, detail="Admin required")
            
            with pytest.raises(HTTPException) as exc:
                await list_users(mock_request)
            
            assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# TestCreateUser
# ---------------------------------------------------------------------------


class TestCreateUser:
    """Tests for POST /admin/users."""

    @pytest.mark.asyncio
    async def test_creates_user_with_valid_data(self):
        """Creates user with username, password, display_name."""
        from api.auth.admin import create_user_endpoint
        
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "username": "newuser",
            "password": "secret123",
            "display_name": "New User"
        })
        
        with patch("api.auth.admin.require_super") as mock_require, \
             patch("api.auth.admin.auth_users") as mock_users, \
             patch("api.auth.admin.user_profiles") as mock_profiles:
            
            mock_require.return_value = "admin"
            mock_users.create_user.return_value = "new-uuid"
            mock_users.get_user_by_id.return_value = {
                "id": "new-uuid", "username": "newuser", "display_name": "New User"
            }
            mock_profiles.DEFAULT_PROFILE_ID = "default-profile"

            result = await create_user_endpoint(mock_request)

            assert result["id"] == "new-uuid"
            mock_users.create_user.assert_called_once_with(
                "newuser", "secret123", "New User"
            )
            mock_profiles.add_user_profile.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_empty_username(self):
        """Raises 400 for empty username."""
        from api.auth.admin import create_user_endpoint
        
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "username": "",
            "password": "secret"
        })
        
        with patch("api.auth.admin.require_super"):
            with pytest.raises(HTTPException) as exc:
                await create_user_endpoint(mock_request)
            
            assert exc.value.status_code == 400
            assert "Username required" in exc.value.detail

    @pytest.mark.asyncio
    async def test_rejects_short_password(self):
        """Raises 400 for password shorter than 4 chars."""
        from api.auth.admin import create_user_endpoint
        
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "username": "newuser",
            "password": "abc"
        })
        
        with patch("api.auth.admin.require_super"):
            with pytest.raises(HTTPException) as exc:
                await create_user_endpoint(mock_request)
            
            assert exc.value.status_code == 400
            assert "Password too short" in exc.value.detail


# ---------------------------------------------------------------------------
# TestUpdateUser
# ---------------------------------------------------------------------------


class TestUpdateUser:
    """Tests for PUT /admin/users/{user_id}."""

    @pytest.mark.asyncio
    async def test_updates_display_name(self):
        """Updates user display name."""
        from api.auth.admin import update_user_endpoint
        
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"display_name": "Alice Smith"})
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.auth_users") as mock_users:
            
            mock_users.get_user_by_id.return_value = {
                "id": "u1", "username": "alice", "display_name": "Alice"
            }

            result = await update_user_endpoint("u1", mock_request)

            mock_users.update_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_user(self):
        """Raises 404 if user not found."""
        from api.auth.admin import update_user_endpoint
        
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={})
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.auth_users") as mock_users:
            
            mock_users.get_user_by_id.return_value = None

            with pytest.raises(HTTPException) as exc:
                await update_user_endpoint("unknown-id", mock_request)
            
            assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# TestDeleteUser
# ---------------------------------------------------------------------------


class TestDeleteUser:
    """Tests for DELETE /admin/users/{user_id}."""

    @pytest.mark.asyncio
    async def test_deletes_user(self):
        """Deletes user and removes profile assignments."""
        from api.auth.admin import delete_user_endpoint
        
        mock_request = MagicMock()
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.auth_core") as mock_core, \
             patch("api.auth.admin.auth_users") as mock_users, \
             patch("api.auth.admin.user_profiles") as mock_profiles:
            
            mock_core.get_current_user.return_value = "admin_user"
            mock_users.get_user_by_id.return_value = {
                "id": "u1", "username": "alice"
            }

            result = await delete_user_endpoint("u1", mock_request)

            mock_profiles.set_user_profiles.assert_called_once_with("alice", [])
            mock_users.delete_user.assert_called_once_with("u1")
            assert result["deleted"] is True

    @pytest.mark.asyncio
    async def test_cannot_delete_self(self):
        """Raises 400 when trying to delete yourself."""
        from api.auth.admin import delete_user_endpoint
        
        mock_request = MagicMock()
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.auth_core") as mock_core, \
             patch("api.auth.admin.auth_users") as mock_users:
            
            mock_core.get_current_user.return_value = "admin_user"
            mock_users.get_user_by_id.return_value = {
                "id": "u1", "username": "admin_user"
            }

            with pytest.raises(HTTPException) as exc:
                await delete_user_endpoint("u1", mock_request)
            
            assert exc.value.status_code == 400
            assert "Cannot delete yourself" in exc.value.detail


# ---------------------------------------------------------------------------
# TestProfileAssignment
# ---------------------------------------------------------------------------


class TestSetUserProfiles:
    """Tests for PUT /admin/users/{username}/profiles."""

    @pytest.mark.asyncio
    async def test_sets_user_profiles(self):
        """Replaces all user profiles."""
        from api.auth.admin import set_user_profiles_endpoint
        
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"profile_ids": ["p1", "p2"]})
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.auth_users") as mock_users, \
             patch("api.auth.admin.user_profiles") as mock_profiles:
            
            mock_users.user_exists.return_value = True
            mock_profiles.get_all_profiles.return_value = {"p1": {}, "p2": {}}
            mock_profiles.get_user_profiles_detailed.return_value = []
            mock_profiles.get_effective_level.return_value = 0

            result = await set_user_profiles_endpoint("alice", mock_request)

            mock_profiles.set_user_profiles.assert_called_once_with(
                "alice", ["p1", "p2"]
            )

    @pytest.mark.asyncio
    async def test_rejects_unknown_profile_id(self):
        """Raises 400 for unknown profile ID."""
        from api.auth.admin import set_user_profiles_endpoint
        
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"profile_ids": ["unknown"]})
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.auth_users") as mock_users, \
             patch("api.auth.admin.user_profiles") as mock_profiles:
            
            mock_users.user_exists.return_value = True
            mock_profiles.get_all_profiles.return_value = {"p1": {}}

            with pytest.raises(HTTPException) as exc:
                await set_user_profiles_endpoint("alice", mock_request)
            
            assert exc.value.status_code == 400
            assert "Unknown profile ID" in exc.value.detail


class TestAddRemoveUserProfile:
    """Tests for POST/DELETE /admin/users/{username}/profiles/{profile_id}."""

    @pytest.mark.asyncio
    async def test_add_profile_to_user(self):
        """Adds a profile to existing user profiles."""
        from api.auth.admin import add_user_profile_endpoint
        
        mock_request = MagicMock()
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.auth_users") as mock_users, \
             patch("api.auth.admin.user_profiles") as mock_profiles:
            
            mock_users.user_exists.return_value = True
            mock_profiles.get_all_profiles.return_value = {"p1": {}}
            mock_profiles.get_user_profiles_detailed.return_value = []
            mock_profiles.get_effective_level.return_value = 1

            result = await add_user_profile_endpoint("alice", "p1", mock_request)

            mock_profiles.add_user_profile.assert_called_once_with("alice", "p1")

    @pytest.mark.asyncio
    async def test_cannot_remove_last_profile(self):
        """Raises 400 when removing last profile."""
        from api.auth.admin import remove_user_profile_endpoint
        
        mock_request = MagicMock()
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.auth_users") as mock_users, \
             patch("api.auth.admin.user_profiles") as mock_profiles:
            
            mock_users.user_exists.return_value = True
            mock_profiles.get_user_profiles.return_value = ["p1"]  # Only one

            with pytest.raises(HTTPException) as exc:
                await remove_user_profile_endpoint("alice", "p1", mock_request)
            
            assert exc.value.status_code == 400
            assert "Cannot remove last profile" in exc.value.detail


# ---------------------------------------------------------------------------
# TestProfileManagement
# ---------------------------------------------------------------------------


class TestListProfiles:
    """Tests for GET /admin/profiles."""

    @pytest.mark.asyncio
    async def test_returns_all_profiles(self):
        """Returns all available profiles."""
        from api.auth.admin import list_profiles
        
        mock_request = MagicMock()
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.user_profiles") as mock_profiles:
            
            mock_profiles.get_all_profiles.return_value = {
                "p1": {"name": "SUPER", "level": 0}
            }

            result = await list_profiles(mock_request)

            assert "p1" in result


class TestCreateProfile:
    """Tests for POST /admin/profiles."""

    @pytest.mark.asyncio
    async def test_creates_profile(self):
        """Creates a new custom profile."""
        from api.auth.admin import create_profile_endpoint
        
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "name": "custom",
            "level": 2,
            "description": "Custom profile"
        })
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.user_profiles") as mock_profiles:
            
            mock_profiles.create_profile.return_value = "new-uuid"

            result = await create_profile_endpoint(mock_request)

            assert result["name"] == "CUSTOM"  # Uppercased
            assert result["level"] == 2
            assert result["protected"] is False

    @pytest.mark.asyncio
    async def test_rejects_invalid_level(self):
        """Raises 400 for level outside 0-3."""
        from api.auth.admin import create_profile_endpoint
        
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "name": "invalid",
            "level": 5
        })
        
        with patch("api.auth.admin.require_super"):
            with pytest.raises(HTTPException) as exc:
                await create_profile_endpoint(mock_request)
            
            assert exc.value.status_code == 400
            assert "Level must be 0-3" in exc.value.detail


class TestUpdateProfile:
    """Tests for PUT /admin/profiles/{profile_id}."""

    @pytest.mark.asyncio
    async def test_updates_profile(self):
        """Updates profile attributes."""
        from api.auth.admin import update_profile_endpoint
        
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"level": 1})
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.user_profiles") as mock_profiles:
            
            mock_profiles.get_profile_by_id.return_value = {
                "id": "p1", "name": "CUSTOM", "level": 1
            }

            result = await update_profile_endpoint("p1", mock_request)

            mock_profiles.update_profile.assert_called_once()


class TestDeleteProfile:
    """Tests for DELETE /admin/profiles/{profile_id}."""

    @pytest.mark.asyncio
    async def test_deletes_profile(self):
        """Deletes a custom profile."""
        from api.auth.admin import delete_profile_endpoint
        
        mock_request = MagicMock()
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.user_profiles") as mock_profiles:
            
            result = await delete_profile_endpoint("p1", mock_request)

            mock_profiles.delete_profile.assert_called_once_with("p1")
            assert result["deleted"] == "p1"


# ---------------------------------------------------------------------------
# TestLegacyEndpoint
# ---------------------------------------------------------------------------


class TestSetUserProfileLegacy:
    """Tests for PUT /admin/users/{username}/profile (legacy)."""

    @pytest.mark.asyncio
    async def test_sets_single_profile(self):
        """Legacy endpoint sets a single profile."""
        from api.auth.admin import set_user_profile_legacy
        
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"profile": "p1"})
        
        with patch("api.auth.admin.require_super"), \
             patch("api.auth.admin.auth_users") as mock_users, \
             patch("api.auth.admin.user_profiles") as mock_profiles:
            
            mock_users.user_exists.return_value = True
            mock_profiles.get_all_profiles.return_value = {"p1": {"name": "SUPER"}}

            result = await set_user_profile_legacy("alice", mock_request)

            mock_profiles.set_user_profiles.assert_called_once_with("alice", ["p1"])
            assert result["username"] == "alice"
