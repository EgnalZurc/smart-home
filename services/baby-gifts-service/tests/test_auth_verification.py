"""Tests for X-Auth-User header verification on admin endpoints.

Defense-in-depth: admin endpoints should verify X-Auth-User header in code,
not just rely on nginx auth_request protection.
"""


class TestAdminEndpointsRequireAuthHeader:
    """Verify all admin endpoints return 401 when X-Auth-User header is missing."""

    def test_get_all_gifts_requires_auth(self, client):
        """GET /api/baby-gifts should return 401 without X-Auth-User header."""
        response = client.get("/api/baby-gifts")
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_get_all_gifts_with_auth(self, client):
        """GET /api/baby-gifts should work with X-Auth-User header."""
        response = client.get("/api/baby-gifts", headers={"X-Auth-User": "testuser"})
        assert response.status_code == 200
        assert "gifts" in response.json()

    def test_create_gift_requires_auth(self, client, sample_gift):
        """POST /api/baby-gifts should return 401 without X-Auth-User header."""
        response = client.post("/api/baby-gifts", json=sample_gift)
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_create_gift_with_auth(self, client, sample_gift):
        """POST /api/baby-gifts should work with X-Auth-User header."""
        response = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_update_gift_requires_auth(self, client, sample_gift):
        """PUT /api/baby-gifts/{id} should return 401 without X-Auth-User header."""
        # First create a gift with auth
        create_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = create_resp.json()["gift"]["id"]

        # Try to update without auth
        response = client.put(
            f"/api/baby-gifts/{gift_id}", json={"name": "Updated Name"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_update_gift_with_auth(self, client, sample_gift):
        """PUT /api/baby-gifts/{id} should work with X-Auth-User header."""
        # Create a gift
        create_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = create_resp.json()["gift"]["id"]

        # Update with auth
        response = client.put(
            f"/api/baby-gifts/{gift_id}",
            json={"name": "Updated Name"},
            headers={"X-Auth-User": "admin"},
        )
        assert response.status_code == 200
        assert response.json()["gift"]["name"] == "Updated Name"

    def test_delete_gift_requires_auth(self, client, sample_gift):
        """DELETE /api/baby-gifts/{id} should return 401 without X-Auth-User header."""
        # First create a gift with auth
        create_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = create_resp.json()["gift"]["id"]

        # Try to delete without auth
        response = client.delete(f"/api/baby-gifts/{gift_id}")
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_delete_gift_with_auth(self, client, sample_gift):
        """DELETE /api/baby-gifts/{id} should work with X-Auth-User header."""
        # Create a gift
        create_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = create_resp.json()["gift"]["id"]

        # Delete with auth
        response = client.delete(
            f"/api/baby-gifts/{gift_id}", headers={"X-Auth-User": "admin"}
        )
        assert response.status_code == 200

    def test_admin_unreserve_requires_auth(self, client, sample_gift):
        """POST /api/baby-gifts/{id}/unreserve should return 401 without header."""
        # Create and reserve a gift
        create_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = create_resp.json()["gift"]["id"]

        # Create invitation and reserve
        inv_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "Guest"},
            headers={"X-Auth-User": "admin"},
        )
        token = inv_resp.json()["token"]
        client.post(f"/api/baby-gifts/guest/{token}/reserve/{gift_id}")

        # Try admin unreserve without auth
        response = client.post(f"/api/baby-gifts/{gift_id}/unreserve")
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_admin_unreserve_with_auth(self, client, sample_gift):
        """POST /api/baby-gifts/{id}/unreserve should work with X-Auth-User header."""
        # Create and reserve a gift
        create_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = create_resp.json()["gift"]["id"]

        # Create invitation and reserve
        inv_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "Guest"},
            headers={"X-Auth-User": "admin"},
        )
        token = inv_resp.json()["token"]
        client.post(f"/api/baby-gifts/guest/{token}/reserve/{gift_id}")

        # Admin unreserve with auth
        response = client.post(
            f"/api/baby-gifts/{gift_id}/unreserve", headers={"X-Auth-User": "admin"}
        )
        assert response.status_code == 200


class TestInvitationEndpointsRequireAuthHeader:
    """Verify invitation management endpoints return 401 without X-Auth-User header."""

    def test_list_invitations_requires_auth(self, client):
        """GET /api/baby-gifts/invitations should return 401 without header."""
        response = client.get("/api/baby-gifts/invitations")
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_list_invitations_with_auth(self, client):
        """GET /api/baby-gifts/invitations should work with X-Auth-User header."""
        response = client.get(
            "/api/baby-gifts/invitations", headers={"X-Auth-User": "admin"}
        )
        assert response.status_code == 200
        assert "invitations" in response.json()

    def test_create_invitation_requires_auth(self, client):
        """POST /api/baby-gifts/invitations should return 401 without header."""
        response = client.post(
            "/api/baby-gifts/invitations", json={"name": "Test Guest"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_create_invitation_with_auth(self, client):
        """POST /api/baby-gifts/invitations should work with X-Auth-User header."""
        response = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "Test Guest"},
            headers={"X-Auth-User": "admin"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_delete_invitation_requires_auth(self, client):
        """DELETE /api/baby-gifts/invitations/{token} should return 401 without header."""
        # Create invitation first
        create_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "Test Guest"},
            headers={"X-Auth-User": "admin"},
        )
        token = create_resp.json()["token"]

        # Try delete without auth
        response = client.delete(f"/api/baby-gifts/invitations/{token}")
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_delete_invitation_with_auth(self, client):
        """DELETE /api/baby-gifts/invitations/{token} should work with header."""
        # Create invitation
        create_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "Test Guest"},
            headers={"X-Auth-User": "admin"},
        )
        token = create_resp.json()["token"]

        # Delete with auth
        response = client.delete(
            f"/api/baby-gifts/invitations/{token}", headers={"X-Auth-User": "admin"}
        )
        assert response.status_code == 200

    def test_revoke_invitation_requires_auth(self, client):
        """POST /api/baby-gifts/invitations/{token}/revoke should return 401."""
        # Create invitation first
        create_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "Test Guest"},
            headers={"X-Auth-User": "admin"},
        )
        token = create_resp.json()["token"]

        # Try revoke without auth
        response = client.post(f"/api/baby-gifts/invitations/{token}/revoke")
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"

    def test_revoke_invitation_with_auth(self, client):
        """POST /api/baby-gifts/invitations/{token}/revoke should work with header."""
        # Create invitation
        create_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "Test Guest"},
            headers={"X-Auth-User": "admin"},
        )
        token = create_resp.json()["token"]

        # Revoke with auth
        response = client.post(
            f"/api/baby-gifts/invitations/{token}/revoke",
            headers={"X-Auth-User": "admin"},
        )
        assert response.status_code == 200


class TestUserEndpointsStillRequireAuth:
    """Verify user endpoints still use their existing auth mechanism (unchanged)."""

    def test_user_get_gifts_requires_auth(self, client):
        """GET /api/baby-gifts/user should return 401 without X-Auth-User header."""
        response = client.get("/api/baby-gifts/user")
        assert response.status_code == 401
        assert response.json()["detail"] == "Usuario no autenticado"

    def test_user_reserve_requires_auth(self, client, sample_gift):
        """POST /api/baby-gifts/user/reserve/{id} should return 401 without header."""
        # Create a gift with auth
        create_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = create_resp.json()["gift"]["id"]

        response = client.post(f"/api/baby-gifts/user/reserve/{gift_id}")
        assert response.status_code == 401
        assert response.json()["detail"] == "Usuario no autenticado"

    def test_user_unreserve_requires_auth(self, client, sample_gift):
        """POST /api/baby-gifts/user/unreserve/{id} should return 401 without header."""
        # Create a gift with auth
        create_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = create_resp.json()["gift"]["id"]

        response = client.post(f"/api/baby-gifts/user/unreserve/{gift_id}")
        assert response.status_code == 401
        assert response.json()["detail"] == "Usuario no autenticado"


class TestGuestEndpointsNoAuthRequired:
    """Verify guest endpoints don't require X-Auth-User (they use invitation tokens)."""

    def test_guest_get_gifts_no_auth_header_needed(self, client, sample_gift):
        """GET /api/baby-gifts/guest/{token} uses token auth, not X-Auth-User."""
        # Create gift with admin auth
        client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )

        # Create invitation with admin auth
        inv_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "Guest"},
            headers={"X-Auth-User": "admin"},
        )
        token = inv_resp.json()["token"]

        # Guest access without X-Auth-User header (uses token instead)
        response = client.get(f"/api/baby-gifts/guest/{token}")
        assert response.status_code == 200
        assert response.json()["guest_name"] == "Guest"


class TestHealthEndpointsNoAuthRequired:
    """Verify health endpoints don't require authentication."""

    def test_health_no_auth_required(self, client):
        """GET /health should not require X-Auth-User header."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["online"] is True

    def test_health_alias_no_auth_required(self, client):
        """GET /api/health/baby-gifts should not require X-Auth-User header."""
        response = client.get("/api/health/baby-gifts")
        assert response.status_code == 200
        assert response.json()["online"] is True
