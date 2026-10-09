"""Unit tests for api/proxy/baby_gifts.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import Response

from api.proxy.baby_gifts import (
    router,
    get_all_baby_gifts,
    create_baby_gift,
    update_baby_gift,
    delete_baby_gift,
    admin_unreserve_baby_gift,
    update_baby_gifts_categories,
    get_baby_gifts_invitations,
    create_baby_gifts_invitation,
    delete_baby_gifts_invitation,
    revoke_baby_gifts_invitation,
    get_baby_gifts_for_user,
    user_reserve_baby_gift,
    user_unreserve_baby_gift,
    get_baby_gifts_for_guest,
    guest_reserve_baby_gift,
    guest_unreserve_baby_gift,
)


def make_mock_response(data, status_code=200):
    """Create a mock HTTP response."""
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


def make_mock_request(headers=None, json_data=None):
    """Create a mock FastAPI request."""
    mock_req = MagicMock()
    mock_req.headers = headers or {}
    if json_data is not None:
        mock_req.json = AsyncMock(return_value=json_data)
    return mock_req


@pytest.fixture
def mock_require_super():
    """Mock require_app_write to allow admin endpoints in tests."""
    with patch("api.proxy.baby_gifts.require_app_write") as mock:
        mock.return_value = "testadmin"
        yield mock


class TestAdminEndpoints:
    """Tests for admin-only endpoints."""

    @pytest.mark.asyncio
    async def test_get_all_baby_gifts_success(self, mock_require_super):
        """Returns gifts list on success."""
        gifts = [{"id": "1", "name": "Gift 1"}]
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(gifts)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_all_baby_gifts(request)
            assert result == gifts
            mock_require_super.assert_called_once_with(request, "babygifts")

    @pytest.mark.asyncio
    async def test_get_all_baby_gifts_service_error(self, mock_require_super):
        """Raises 503 when service is unavailable."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Connection refused")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_all_baby_gifts(request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_create_baby_gift_success(self, mock_require_super):
        """Creates gift successfully."""
        new_gift = {"id": "1", "name": "New Gift"}
        request = make_mock_request(json_data={"name": "New Gift"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(new_gift, 201)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await create_baby_gift(request)
            assert result == new_gift
            mock_require_super.assert_called_once_with(request, "babygifts")

    @pytest.mark.asyncio
    async def test_create_baby_gift_validation_error(self, mock_require_super):
        """Raises HTTPException on validation error."""
        request = make_mock_request(json_data={"invalid": "data"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Name required"}, 400
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await create_baby_gift(request)
            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_update_baby_gift_success(self, mock_require_super):
        """Updates gift successfully."""
        updated = {"id": "1", "name": "Updated"}
        request = make_mock_request(json_data={"name": "Updated"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.put.return_value = make_mock_response(updated)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await update_baby_gift("1", request)
            assert result == updated
            mock_require_super.assert_called_once_with(request, "babygifts")

    @pytest.mark.asyncio
    async def test_update_baby_gift_not_found(self, mock_require_super):
        """Raises 404 when gift not found."""
        request = make_mock_request(json_data={"name": "Updated"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.put.return_value = make_mock_response(
                {"detail": "Not found"}, 404
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await update_baby_gift("999", request)
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_baby_gift_success(self, mock_require_super):
        """Deletes gift successfully."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.return_value = make_mock_response({"status": "deleted"})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await delete_baby_gift("1", request)
            assert result["status"] == "deleted"
            mock_require_super.assert_called_once_with(request, "babygifts")

    @pytest.mark.asyncio
    async def test_delete_baby_gift_not_found(self, mock_require_super):
        """Raises 404 when gift not found."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.return_value = make_mock_response(
                {"detail": "Not found"}, 404
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await delete_baby_gift("999", request)
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_unreserve_success(self, mock_require_super):
        """Admin unreserves gift successfully."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"reserved": False})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await admin_unreserve_baby_gift("1", request)
            assert result["reserved"] is False
            mock_require_super.assert_called_once_with(request, "babygifts")

    @pytest.mark.asyncio
    async def test_update_categories_success(self, mock_require_super):
        """Updates categories successfully."""
        categories = ["Ropa", "Juguetes"]
        request = make_mock_request(json_data={"categories": categories})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.put.return_value = make_mock_response(
                {"categories": categories}
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await update_baby_gifts_categories(request)
            assert result["categories"] == categories
            mock_require_super.assert_called_once_with(request, "babygifts")


class TestInvitationEndpoints:
    """Tests for invitation management endpoints."""

    @pytest.mark.asyncio
    async def test_get_invitations_success(self, mock_require_super):
        """Returns invitations list."""
        invitations = [{"token": "abc123", "name": "Guest 1"}]
        request = make_mock_request()

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(invitations)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_baby_gifts_invitations(request)
            assert result == invitations
            mock_require_super.assert_called_once_with(request, "babygifts")

    @pytest.mark.asyncio
    async def test_create_invitation_success(self, mock_require_super):
        """Creates invitation successfully."""
        invitation = {"token": "abc123", "name": "Guest 1"}
        request = make_mock_request(json_data={"name": "Guest 1"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(invitation, 201)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await create_baby_gifts_invitation(request)
            assert result == invitation
            mock_require_super.assert_called_once_with(request, "babygifts")

    @pytest.mark.asyncio
    async def test_delete_invitation_success(self, mock_require_super):
        """Deletes invitation successfully."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.return_value = make_mock_response({"status": "deleted"})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await delete_baby_gifts_invitation("abc123", request)
            assert result["status"] == "deleted"
            mock_require_super.assert_called_once_with(request, "babygifts")

    @pytest.mark.asyncio
    async def test_revoke_invitation_success(self, mock_require_super):
        """Revokes invitation successfully."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"revoked": True})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await revoke_baby_gifts_invitation("abc123", request)
            assert result["revoked"] is True
            mock_require_super.assert_called_once_with(request, "babygifts")


class TestUserEndpoints:
    """Tests for authenticated user endpoints."""

    @pytest.mark.asyncio
    async def test_get_gifts_for_user_success(self):
        """Returns gifts for authenticated user."""
        gifts = [{"id": "1", "name": "Gift", "available": True}]
        request = make_mock_request(headers={"X-Auth-User": "testuser"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(gifts)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_baby_gifts_for_user(request)
            assert result == gifts

    @pytest.mark.asyncio
    async def test_get_gifts_forwards_auth_header(self):
        """Forwards X-Auth-User header to backend."""
        request = make_mock_request(headers={"X-Auth-User": "testuser"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response([])
            mock_client.return_value.__aenter__.return_value = mock_instance

            await get_baby_gifts_for_user(request)

            # Verify the header was forwarded
            call_args = mock_instance.get.call_args
            assert "headers" in call_args.kwargs
            assert call_args.kwargs["headers"]["X-Auth-User"] == "testuser"

    @pytest.mark.asyncio
    async def test_user_reserve_success(self):
        """User reserves gift successfully."""
        request = make_mock_request(headers={"X-Auth-User": "testuser"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"reserved": True})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await user_reserve_baby_gift("1", request)
            assert result["reserved"] == True

    @pytest.mark.asyncio
    async def test_user_unreserve_success(self):
        """User unreserves gift successfully."""
        request = make_mock_request(headers={"X-Auth-User": "testuser"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"reserved": False})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await user_unreserve_baby_gift("1", request)
            assert result["reserved"] == False


class TestGuestEndpoints:
    """Tests for guest (token-based) endpoints."""

    @pytest.mark.asyncio
    async def test_get_gifts_for_guest_success(self):
        """Returns gifts for guest with token."""
        gifts = [{"id": "1", "name": "Gift", "available": True}]
        request = make_mock_request(headers={"X-Forwarded-For": "1.2.3.4"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(gifts)
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_baby_gifts_for_guest("abc123", request)
            assert result == gifts

    @pytest.mark.asyncio
    async def test_get_gifts_invalid_token(self):
        """Raises 401 for invalid token."""
        request = make_mock_request()

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(
                {"detail": "Invalid token"}, 401
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_baby_gifts_for_guest("invalid", request)
            assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_guest_reserve_success(self):
        """Guest reserves gift successfully."""
        request = make_mock_request(headers={"X-Forwarded-For": "1.2.3.4"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"reserved": True})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await guest_reserve_baby_gift("abc123", "1", request)
            assert result["reserved"] == True

    @pytest.mark.asyncio
    async def test_guest_unreserve_success(self):
        """Guest unreserves gift successfully."""
        request = make_mock_request(headers={"X-Forwarded-For": "1.2.3.4"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response({"reserved": False})
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await guest_unreserve_baby_gift("abc123", "1", request)
            assert result["reserved"] == False

    @pytest.mark.asyncio
    async def test_guest_forwards_ip_header(self):
        """Forwards X-Forwarded-For header to backend."""
        request = make_mock_request(headers={"X-Forwarded-For": "1.2.3.4"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response([])
            mock_client.return_value.__aenter__.return_value = mock_instance

            await get_baby_gifts_for_guest("abc123", request)

            call_args = mock_instance.get.call_args
            assert "headers" in call_args.kwargs
            assert call_args.kwargs["headers"]["X-Forwarded-For"] == "1.2.3.4"


class TestRouterConfiguration:
    """Tests for router configuration."""

    def test_router_has_correct_prefix(self):
        """Router has /api/baby-gifts prefix."""
        assert router.prefix == "/api/baby-gifts"

    def test_router_has_baby_gifts_tag(self):
        """Router is tagged as Baby Gifts."""
        assert "Baby Gifts" in router.tags



class TestErrorHandlingPaths:
    """Tests for error handling paths to improve coverage."""

    @pytest.mark.asyncio
    async def test_create_gift_network_error(self, mock_require_super):
        """Raises 503 on network error during create."""
        request = make_mock_request(json_data={"name": "Gift"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await create_baby_gift(request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_update_gift_network_error(self, mock_require_super):
        """Raises 503 on network error during update."""
        request = make_mock_request(json_data={"name": "Updated"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.put.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await update_baby_gift("1", request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_delete_gift_network_error(self, mock_require_super):
        """Raises 503 on network error during delete."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await delete_baby_gift("1", request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_admin_unreserve_network_error(self, mock_require_super):
        """Raises 503 on network error during admin unreserve."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await admin_unreserve_baby_gift("1", request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_admin_unreserve_service_error(self, mock_require_super):
        """Raises HTTPException on 4xx during admin unreserve."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Not found"}, 404
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await admin_unreserve_baby_gift("999", request)
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_categories_network_error(self, mock_require_super):
        """Raises 503 on network error during update categories."""
        request = make_mock_request(json_data={"categories": []})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.put.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await update_baby_gifts_categories(request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_invitations_network_error(self, mock_require_super):
        """Raises 503 on network error getting invitations."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_baby_gifts_invitations(request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_create_invitation_network_error(self, mock_require_super):
        """Raises 503 on network error creating invitation."""
        request = make_mock_request(json_data={"name": "Guest"})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await create_baby_gifts_invitation(request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_create_invitation_service_error(self, mock_require_super):
        """Raises HTTPException on service error creating invitation."""
        request = make_mock_request(json_data={"name": ""})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Name required"}, 400
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await create_baby_gifts_invitation(request)
            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_invitation_network_error(self, mock_require_super):
        """Raises 503 on network error deleting invitation."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await delete_baby_gifts_invitation("abc123", request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_delete_invitation_service_error(self, mock_require_super):
        """Raises HTTPException on service error deleting invitation."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.delete.return_value = make_mock_response(
                {"detail": "Not found"}, 404
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await delete_baby_gifts_invitation("invalid", request)
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_invitation_network_error(self, mock_require_super):
        """Raises 503 on network error revoking invitation."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await revoke_baby_gifts_invitation("abc123", request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_revoke_invitation_service_error(self, mock_require_super):
        """Raises HTTPException on service error revoking invitation."""
        request = make_mock_request()
        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Already revoked"}, 400
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await revoke_baby_gifts_invitation("abc123", request)
            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_gifts_for_user_network_error(self):
        """Raises 503 on network error getting user gifts."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_baby_gifts_for_user(request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_gifts_for_user_service_error(self):
        """Raises HTTPException on service error getting user gifts."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response(
                {"detail": "Unauthorized"}, 401
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_baby_gifts_for_user(request)
            assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_user_reserve_network_error(self):
        """Raises 503 on network error during user reserve."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await user_reserve_baby_gift("1", request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_user_reserve_service_error(self):
        """Raises HTTPException on service error during user reserve."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Already reserved"}, 409
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await user_reserve_baby_gift("1", request)
            assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_user_unreserve_network_error(self):
        """Raises 503 on network error during user unreserve."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await user_unreserve_baby_gift("1", request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_user_unreserve_service_error(self):
        """Raises HTTPException on service error during user unreserve."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Not your reservation"}, 403
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await user_unreserve_baby_gift("1", request)
            assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_guest_get_gifts_network_error(self):
        """Raises 503 on network error getting guest gifts."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await get_baby_gifts_for_guest("abc123", request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_guest_reserve_network_error(self):
        """Raises 503 on network error during guest reserve."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await guest_reserve_baby_gift("abc123", "1", request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_guest_reserve_service_error(self):
        """Raises HTTPException on service error during guest reserve."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Already reserved"}, 409
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await guest_reserve_baby_gift("abc123", "1", request)
            assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_guest_unreserve_network_error(self):
        """Raises 503 on network error during guest unreserve."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await guest_unreserve_baby_gift("abc123", "1", request)
            assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_guest_unreserve_service_error(self):
        """Raises HTTPException on service error during guest unreserve."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = make_mock_response(
                {"detail": "Not your reservation"}, 403
            )
            mock_client.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(HTTPException) as exc:
                await guest_unreserve_baby_gift("abc123", "1", request)
            assert exc.value.status_code == 403


class TestRequestWithoutHeaders:
    """Tests for requests without optional headers."""

    @pytest.mark.asyncio
    async def test_get_user_gifts_without_auth_header(self):
        """Handles request without X-Auth-User header."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response([])
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_baby_gifts_for_user(request)
            assert result == []

            # Verify no auth header was forwarded (proxy receives headers=None)
            call_args = mock_instance.get.call_args
            assert call_args.kwargs["headers"] is None

    @pytest.mark.asyncio
    async def test_guest_gifts_without_xff_header(self):
        """Handles guest request without X-Forwarded-For header."""
        request = make_mock_request(headers={})

        with patch("libs.service_proxy.proxy.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = make_mock_response([])
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await get_baby_gifts_for_guest("abc123", request)
            assert result == []

            # Verify no xff header was forwarded (proxy receives headers=None)
            call_args = mock_instance.get.call_args
            assert call_args.kwargs["headers"] is None
