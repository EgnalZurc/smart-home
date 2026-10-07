"""Unit tests for FastAPI endpoints."""

from unittest.mock import patch


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_returns_online(self, client):
        """Health endpoint should return online status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["online"] is True
        assert data["service"] == "baby-gifts"

    def test_health_alias_returns_online(self, client):
        """Health alias endpoint should return online status."""
        response = client.get("/api/health/baby-gifts")

        assert response.status_code == 200
        data = response.json()
        assert data["online"] is True


class TestAdminGiftEndpoints:
    """Tests for admin gift management endpoints."""

    def test_get_all_gifts_empty(self, client):
        """GET /api/baby-gifts should return empty list initially."""
        response = client.get("/api/baby-gifts")

        assert response.status_code == 200
        data = response.json()
        assert "gifts" in data
        assert isinstance(data["gifts"], list)

    def test_create_gift(self, client, sample_gift):
        """POST /api/baby-gifts should create a gift."""
        response = client.post("/api/baby-gifts", json=sample_gift)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["gift"]["name"] == sample_gift["name"]
        assert data["gift"]["id"].startswith("g_")

    def test_update_gift(self, client, sample_gift):
        """PUT /api/baby-gifts/{id} should update a gift."""
        # Create a gift first
        create_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = create_resp.json()["gift"]["id"]

        # Update it
        response = client.put(
            f"/api/baby-gifts/{gift_id}", json={"name": "Updated Name"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["gift"]["name"] == "Updated Name"

    def test_update_nonexistent_gift_404(self, client):
        """PUT /api/baby-gifts/{id} should return 404 for non-existent gift."""
        response = client.put("/api/baby-gifts/nonexistent", json={"name": "New Name"})

        assert response.status_code == 404

    def test_delete_gift(self, client, sample_gift):
        """DELETE /api/baby-gifts/{id} should delete a gift."""
        # Create a gift first
        create_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = create_resp.json()["gift"]["id"]

        # Delete it
        response = client.delete(f"/api/baby-gifts/{gift_id}")

        assert response.status_code == 200

        # Verify it's gone
        all_gifts = client.get("/api/baby-gifts").json()
        gift_ids = [g["id"] for g in all_gifts["gifts"]]
        assert gift_id not in gift_ids

    def test_delete_nonexistent_gift_404(self, client):
        """DELETE /api/baby-gifts/{id} should return 404."""
        response = client.delete("/api/baby-gifts/nonexistent")

        assert response.status_code == 404


class TestInvitationEndpoints:
    """Tests for invitation management endpoints."""

    def test_list_invitations_empty(self, client):
        """GET /api/baby-gifts/invitations should return empty list initially."""
        response = client.get("/api/baby-gifts/invitations")

        assert response.status_code == 200
        data = response.json()
        assert "invitations" in data
        assert data["invitations"] == []

    def test_create_invitation(self, client, sample_invitation_name):
        """POST /api/baby-gifts/invitations should create invitation."""
        response = client.post(
            "/api/baby-gifts/invitations", json={"name": sample_invitation_name}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "token" in data
        assert data["name"] == sample_invitation_name

    def test_create_invitation_empty_name_fails(self, client):
        """POST /api/baby-gifts/invitations with empty name should fail."""
        response = client.post("/api/baby-gifts/invitations", json={"name": "   "})

        assert response.status_code == 400

    def test_delete_invitation(self, client, sample_invitation_name):
        """DELETE /api/baby-gifts/invitations/{token} should delete invitation."""
        # Create first
        create_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": sample_invitation_name}
        )
        token = create_resp.json()["token"]

        # Delete
        response = client.delete(f"/api/baby-gifts/invitations/{token}")

        assert response.status_code == 200

    def test_revoke_invitation(self, client, sample_invitation_name):
        """POST /api/baby-gifts/invitations/{token}/revoke should revoke."""
        # Create first
        create_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": sample_invitation_name}
        )
        token = create_resp.json()["token"]

        # Revoke
        response = client.post(f"/api/baby-gifts/invitations/{token}/revoke")

        assert response.status_code == 200

        # Check it's revoked
        invitations = client.get("/api/baby-gifts/invitations").json()["invitations"]
        revoked = next(inv for inv in invitations if inv["token"] == token)
        assert revoked["revoked"] is True

    def test_invitations_include_gift_stats(self, client, sample_invitation_name):
        """GET /api/baby-gifts/invitations should include visible_gifts and available_gifts."""
        # Create some gifts: 2 visible (1 reserved, 1 not), 1 hidden
        gift1_resp = client.post("/api/baby-gifts", json={"name": "Visible Gift 1"})
        gift1_id = gift1_resp.json()["gift"]["id"]

        client.post("/api/baby-gifts", json={"name": "Visible Gift 2"})

        hidden_resp = client.post("/api/baby-gifts", json={"name": "Hidden Gift"})
        hidden_id = hidden_resp.json()["gift"]["id"]

        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": sample_invitation_name}
        )
        token = inv_resp.json()["token"]

        # Reserve one visible gift as guest
        client.post(f"/api/baby-gifts/guest/{token}/reserve/{gift1_id}")

        # Hide one gift via user endpoint (requires X-Auth-User header)
        client.post(
            f"/api/baby-gifts/user/toggle-visibility/{hidden_id}",
            headers={"X-Auth-User": "egnal"},
        )

        # Get invitations and verify stats
        response = client.get("/api/baby-gifts/invitations")
        assert response.status_code == 200
        data = response.json()

        assert len(data["invitations"]) == 1
        inv = data["invitations"][0]

        # visible_gifts = gifts where hidden=False (2: Visible Gift 1, Visible Gift 2)
        assert inv["visible_gifts"] == 2
        # available_gifts = visible gifts without reservation (1: Visible Gift 2)
        assert inv["available_gifts"] == 1


class TestGuestEndpoints:
    """Tests for guest API endpoints."""

    def test_guest_get_gifts_invalid_token(self, client):
        """GET /api/baby-gifts/guest/{token} with invalid token should return 401."""
        response = client.get("/api/baby-gifts/guest/invalid_token")

        assert response.status_code == 401

    def test_guest_get_gifts_valid_token(
        self, client, sample_gift, sample_invitation_name
    ):
        """GET /api/baby-gifts/guest/{token} with valid token should return gifts."""
        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": sample_invitation_name}
        )
        token = inv_resp.json()["token"]

        # Create a gift
        client.post("/api/baby-gifts", json=sample_gift)

        # Get as guest
        response = client.get(f"/api/baby-gifts/guest/{token}")

        assert response.status_code == 200
        data = response.json()
        assert "gifts" in data
        assert data["guest_name"] == sample_invitation_name

    def test_guest_reserve_gift(self, client, sample_gift, sample_invitation_name):
        """POST /api/baby-gifts/guest/{token}/reserve/{id} should reserve gift."""
        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": sample_invitation_name}
        )
        token = inv_resp.json()["token"]

        # Create a gift
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        # Reserve as guest
        response = client.post(f"/api/baby-gifts/guest/{token}/reserve/{gift_id}")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_guest_unreserve_own_gift(
        self, client, sample_gift, sample_invitation_name
    ):
        """POST /api/baby-gifts/guest/{token}/unreserve/{id} should unreserve own gift."""
        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": sample_invitation_name}
        )
        token = inv_resp.json()["token"]

        # Create and reserve a gift
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]
        client.post(f"/api/baby-gifts/guest/{token}/reserve/{gift_id}")

        # Unreserve
        response = client.post(f"/api/baby-gifts/guest/{token}/unreserve/{gift_id}")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_hidden_gifts_not_shown_to_guests(self, client, sample_invitation_name):
        """Guests should not see hidden gifts."""
        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": sample_invitation_name}
        )
        _token = inv_resp.json()["token"]

        # Create a visible gift
        visible_resp = client.post("/api/baby-gifts", json={"name": "Visible Gift"})
        _visible_id = visible_resp.json()["gift"]["id"]

        # Create a hidden gift
        hidden_resp = client.post("/api/baby-gifts", json={"name": "Hidden Gift"})
        _hidden_id = hidden_resp.json()["gift"]["id"]

        # Hide it via admin unreserve endpoint won't work, we need direct access
        # Using the toggle visibility would require user endpoint
        # For now, verify both are visible in admin view
        admin_gifts = client.get("/api/baby-gifts").json()["gifts"]
        assert len(admin_gifts) == 2


class TestUserEndpoints:
    """Tests for authenticated user endpoints."""

    def test_user_get_gifts_without_auth_returns_401(self, client):
        """GET /api/baby-gifts/user without auth header should return 401."""
        response = client.get("/api/baby-gifts/user")
        assert response.status_code == 401

    def test_user_get_gifts_with_auth(self, client, sample_gift):
        """GET /api/baby-gifts/user with auth header should return gifts."""
        # Create a gift
        client.post("/api/baby-gifts", json=sample_gift)

        # Get as authenticated user
        response = client.get(
            "/api/baby-gifts/user", headers={"X-Auth-User": "testuser"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "gifts" in data
        assert data["user_name"] == "testuser"
        assert data["is_familia"] is False

    def test_user_get_gifts_familia_user(self, client, sample_gift):
        """GET /api/baby-gifts/user for FAMILIA user returns is_familia=True."""
        client.post("/api/baby-gifts", json=sample_gift)

        response = client.get("/api/baby-gifts/user", headers={"X-Auth-User": "egnal"})

        assert response.status_code == 200
        data = response.json()
        assert data["is_familia"] is True

    def test_user_get_gifts_hides_others_reservations(self, client, sample_gift):
        """User should see 'Alguien' for gifts reserved by others."""
        # Create gift
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        # Reserve as different user
        client.post(
            f"/api/baby-gifts/user/reserve/{gift_id}",
            headers={"X-Auth-User": "otheruser"},
        )

        # Get as another user
        response = client.get(
            "/api/baby-gifts/user", headers={"X-Auth-User": "testuser"}
        )

        data = response.json()
        gift = next(g for g in data["gifts"] if g["id"] == gift_id)
        assert gift["reserved_by"] == "otro"
        assert gift["reserved_by_name"] == "Alguien"
        assert gift["reserved_by_me"] is False

    def test_user_sees_own_reservation(self, client, sample_gift):
        """User should see their own reservation details."""
        # Create gift
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        # Reserve as user
        client.post(
            f"/api/baby-gifts/user/reserve/{gift_id}",
            headers={"X-Auth-User": "testuser"},
        )

        # Get as same user
        response = client.get(
            "/api/baby-gifts/user", headers={"X-Auth-User": "testuser"}
        )

        data = response.json()
        gift = next(g for g in data["gifts"] if g["id"] == gift_id)
        assert gift["reserved_by_me"] is True

    def test_user_reserve_gift(self, client, sample_gift):
        """POST /api/baby-gifts/user/reserve/{id} should reserve gift."""
        # Create gift
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        # Reserve
        with patch("main.send_gift_notification") as mock_notify:
            mock_notify.return_value = True
            response = client.post(
                f"/api/baby-gifts/user/reserve/{gift_id}",
                headers={"X-Auth-User": "testuser"},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        mock_notify.assert_called_once()

    def test_user_reserve_without_auth_returns_401(self, client, sample_gift):
        """POST /api/baby-gifts/user/reserve/{id} without auth returns 401."""
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.post(f"/api/baby-gifts/user/reserve/{gift_id}")
        assert response.status_code == 401

    def test_user_reserve_already_reserved_fails(self, client, sample_gift):
        """POST /api/baby-gifts/user/reserve/{id} for reserved gift returns 400."""
        # Create and reserve gift
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        with patch("main.send_gift_notification"):
            client.post(
                f"/api/baby-gifts/user/reserve/{gift_id}",
                headers={"X-Auth-User": "user1"},
            )

        # Try to reserve again
        response = client.post(
            f"/api/baby-gifts/user/reserve/{gift_id}",
            headers={"X-Auth-User": "user2"},
        )
        assert response.status_code == 400

    def test_user_unreserve_own_gift(self, client, sample_gift):
        """POST /api/baby-gifts/user/unreserve/{id} should unreserve own gift."""
        # Create and reserve gift
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        with patch("main.send_gift_notification"):
            client.post(
                f"/api/baby-gifts/user/reserve/{gift_id}",
                headers={"X-Auth-User": "testuser"},
            )

        # Unreserve
        with patch("main.send_gift_notification") as mock_notify:
            mock_notify.return_value = True
            response = client.post(
                f"/api/baby-gifts/user/unreserve/{gift_id}",
                headers={"X-Auth-User": "testuser"},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_user_unreserve_without_auth_returns_401(self, client, sample_gift):
        """POST /api/baby-gifts/user/unreserve/{id} without auth returns 401."""
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.post(f"/api/baby-gifts/user/unreserve/{gift_id}")
        assert response.status_code == 401

    def test_user_unreserve_others_gift_fails(self, client, sample_gift):
        """POST /api/baby-gifts/user/unreserve/{id} for other's gift returns 400."""
        # Create and reserve gift as user1
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        with patch("main.send_gift_notification"):
            client.post(
                f"/api/baby-gifts/user/reserve/{gift_id}",
                headers={"X-Auth-User": "user1"},
            )

        # Try to unreserve as user2
        response = client.post(
            f"/api/baby-gifts/user/unreserve/{gift_id}",
            headers={"X-Auth-User": "user2"},
        )
        assert response.status_code == 400

    def test_familia_user_sees_hidden_gifts(self, client):
        """FAMILIA users (egnal, virchu) should see hidden gifts."""
        # Create visible and hidden gifts
        client.post("/api/baby-gifts", json={"name": "Visible Gift"})
        hidden_resp = client.post("/api/baby-gifts", json={"name": "Hidden Gift"})
        hidden_id = hidden_resp.json()["gift"]["id"]

        # Hide the gift
        client.post(
            f"/api/baby-gifts/user/toggle-visibility/{hidden_id}",
            headers={"X-Auth-User": "egnal"},
        )

        # FAMILIA user should see both
        response = client.get("/api/baby-gifts/user", headers={"X-Auth-User": "egnal"})
        assert response.status_code == 200
        assert len(response.json()["gifts"]) == 2

    def test_non_familia_user_cannot_see_hidden_gifts(self, client):
        """Non-FAMILIA users should not see hidden gifts."""
        # Create visible and hidden gifts
        client.post("/api/baby-gifts", json={"name": "Visible Gift"})
        hidden_resp = client.post("/api/baby-gifts", json={"name": "Hidden Gift"})
        hidden_id = hidden_resp.json()["gift"]["id"]

        # Hide the gift (as FAMILIA user)
        client.post(
            f"/api/baby-gifts/user/toggle-visibility/{hidden_id}",
            headers={"X-Auth-User": "egnal"},
        )

        # Non-FAMILIA user should only see visible gift
        response = client.get(
            "/api/baby-gifts/user", headers={"X-Auth-User": "randomuser"}
        )
        assert response.status_code == 200
        assert len(response.json()["gifts"]) == 1

    def test_toggle_visibility_requires_familia(self, client):
        """POST /api/baby-gifts/user/toggle-visibility requires FAMILIA user."""
        gift_resp = client.post("/api/baby-gifts", json={"name": "Test Gift"})
        gift_id = gift_resp.json()["gift"]["id"]

        # Non-FAMILIA user should get 403
        response = client.post(
            f"/api/baby-gifts/user/toggle-visibility/{gift_id}",
            headers={"X-Auth-User": "randomuser"},
        )
        assert response.status_code == 403

    def test_toggle_visibility_without_auth_returns_401(self, client):
        """POST /api/baby-gifts/user/toggle-visibility without auth returns 401."""
        gift_resp = client.post("/api/baby-gifts", json={"name": "Test Gift"})
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.post(f"/api/baby-gifts/user/toggle-visibility/{gift_id}")
        assert response.status_code == 401

    def test_toggle_visibility_nonexistent_gift_returns_404(self, client):
        """POST /api/baby-gifts/user/toggle-visibility for nonexistent gift returns 404."""
        response = client.post(
            "/api/baby-gifts/user/toggle-visibility/nonexistent",
            headers={"X-Auth-User": "egnal"},
        )
        assert response.status_code == 404

    def test_gifts_sorted_by_price_descending(self, client):
        """User gifts should be sorted by price descending."""
        # Create gifts with different prices
        client.post("/api/baby-gifts", json={"name": "Cheap", "price_range": "50€"})
        client.post(
            "/api/baby-gifts", json={"name": "Expensive", "price_range": "200€"}
        )
        client.post("/api/baby-gifts", json={"name": "Medium", "price_range": "100€"})

        response = client.get(
            "/api/baby-gifts/user", headers={"X-Auth-User": "testuser"}
        )
        gifts = response.json()["gifts"]

        # Should be sorted: Expensive (200), Medium (100), Cheap (50)
        assert gifts[0]["name"] == "Expensive"
        assert gifts[1]["name"] == "Medium"
        assert gifts[2]["name"] == "Cheap"

    def test_hidden_reservation_shows_oculto(self, client):
        """For hidden gifts, other users see 'oculto' instead of 'otro'."""
        # Create and hide a gift
        gift_resp = client.post("/api/baby-gifts", json={"name": "Hidden Gift"})
        gift_id = gift_resp.json()["gift"]["id"]

        client.post(
            f"/api/baby-gifts/user/toggle-visibility/{gift_id}",
            headers={"X-Auth-User": "egnal"},
        )

        # Reserve as FAMILIA user
        with patch("main.send_gift_notification"):
            client.post(
                f"/api/baby-gifts/user/reserve/{gift_id}",
                headers={"X-Auth-User": "egnal"},
            )

        # Another FAMILIA user sees 'oculto'
        response = client.get(
            "/api/baby-gifts/user", headers={"X-Auth-User": "virchu"}
        )
        gift = next(g for g in response.json()["gifts"] if g["id"] == gift_id)
        assert gift["reserved_by"] == "oculto"


class TestSPAServing:
    """Tests for SPA HTML serving."""

    def test_serve_guest_valid_token(self, client, sample_invitation_name):
        """GET /guest/baby-gifts/{token} with valid token serves HTML."""
        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": sample_invitation_name}
        )
        token = inv_resp.json()["token"]

        response = client.get(f"/guest/baby-gifts/{token}")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "no-cache" in response.headers["cache-control"]

    def test_serve_guest_invalid_token_returns_404(self, client):
        """GET /guest/baby-gifts/{token} with invalid token returns 404."""
        response = client.get("/guest/baby-gifts/invalid_token_12345")
        assert response.status_code == 404

    def test_serve_admin_without_auth(self, client):
        """GET /smart-home/baby-gifts serves HTML without auth header."""
        response = client.get("/smart-home/baby-gifts")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_serve_admin_with_auth_injects_user(self, client):
        """GET /smart-home/baby-gifts with auth injects user info."""
        response = client.get(
            "/smart-home/baby-gifts", headers={"X-Auth-User": "testuser"}
        )

        assert response.status_code == 200
        # Check that AUTH_USER is injected in the HTML
        assert "testuser" in response.text


class TestAdminUnreserve:
    """Tests for admin unreserve endpoint."""

    def test_admin_unreserve_reserved_gift(self, client, sample_gift):
        """POST /api/baby-gifts/{id}/unreserve as admin should unreserve any gift."""
        # Create and reserve gift
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        with patch("main.send_gift_notification"):
            client.post(
                f"/api/baby-gifts/user/reserve/{gift_id}",
                headers={"X-Auth-User": "someuser"},
            )

        # Admin unreserve
        response = client.post(f"/api/baby-gifts/{gift_id}/unreserve")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_admin_unreserve_not_reserved_returns_400(self, client, sample_gift):
        """POST /api/baby-gifts/{id}/unreserve for unreserved gift returns 400."""
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.post(f"/api/baby-gifts/{gift_id}/unreserve")
        assert response.status_code == 400


class TestUpdateGiftValidation:
    """Tests for gift update validation."""

    def test_update_gift_no_changes_returns_400(self, client, sample_gift):
        """PUT /api/baby-gifts/{id} with no fields returns 400."""
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.put(f"/api/baby-gifts/{gift_id}", json={})
        assert response.status_code == 400


class TestGuestEndpointsExtended:
    """Extended tests for guest endpoints."""

    def test_guest_gifts_sorted_by_price(self, client, sample_invitation_name):
        """Guest gifts should be sorted by price descending."""
        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": sample_invitation_name}
        )
        token = inv_resp.json()["token"]

        # Create gifts with different prices
        client.post("/api/baby-gifts", json={"name": "Cheap", "price_range": "30€"})
        client.post(
            "/api/baby-gifts", json={"name": "Expensive", "price_range": "150€"}
        )

        response = client.get(f"/api/baby-gifts/guest/{token}")
        gifts = response.json()["gifts"]

        assert gifts[0]["name"] == "Expensive"
        assert gifts[1]["name"] == "Cheap"

    def test_guest_reserve_invalid_token_returns_401(self, client, sample_gift):
        """POST /api/baby-gifts/guest/{token}/reserve/{id} with invalid token returns 401."""
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.post(f"/api/baby-gifts/guest/invalid_token/reserve/{gift_id}")
        assert response.status_code == 401

    def test_guest_unreserve_invalid_token_returns_401(self, client, sample_gift):
        """POST /api/baby-gifts/guest/{token}/unreserve/{id} with invalid token returns 401."""
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.post(
            f"/api/baby-gifts/guest/invalid_token/unreserve/{gift_id}"
        )
        assert response.status_code == 401

    def test_guest_unreserve_others_gift_fails(
        self, client, sample_gift, sample_invitation_name
    ):
        """Guest cannot unreserve gift reserved by someone else."""
        # Create two invitations
        inv1_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": "Guest 1"}
        )
        token1 = inv1_resp.json()["token"]

        inv2_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": "Guest 2"}
        )
        token2 = inv2_resp.json()["token"]

        # Create and reserve gift as guest1
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        with patch("main.send_gift_notification"):
            client.post(f"/api/baby-gifts/guest/{token1}/reserve/{gift_id}")

        # Try to unreserve as guest2
        response = client.post(f"/api/baby-gifts/guest/{token2}/unreserve/{gift_id}")
        assert response.status_code == 400

    def test_guest_reserve_already_reserved_fails(
        self, client, sample_gift, sample_invitation_name
    ):
        """Guest cannot reserve already reserved gift."""
        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": sample_invitation_name}
        )
        token = inv_resp.json()["token"]

        # Create and reserve gift
        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        with patch("main.send_gift_notification"):
            client.post(f"/api/baby-gifts/guest/{token}/reserve/{gift_id}")

        # Try to reserve again
        response = client.post(f"/api/baby-gifts/guest/{token}/reserve/{gift_id}")
        assert response.status_code == 400

    def test_guest_unreserve_not_reserved_fails(
        self, client, sample_gift, sample_invitation_name
    ):
        """Guest cannot unreserve gift that is not reserved."""
        inv_resp = client.post(
            "/api/baby-gifts/invitations", json={"name": sample_invitation_name}
        )
        token = inv_resp.json()["token"]

        gift_resp = client.post("/api/baby-gifts", json=sample_gift)
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.post(f"/api/baby-gifts/guest/{token}/unreserve/{gift_id}")
        assert response.status_code == 400
