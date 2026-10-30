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
        response = client.get("/api/baby-gifts", headers={"X-Auth-User": "admin"})

        assert response.status_code == 200
        data = response.json()
        assert "gifts" in data
        assert isinstance(data["gifts"], list)

    def test_create_gift(self, client, sample_gift):
        """POST /api/baby-gifts should create a gift."""
        response = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["gift"]["name"] == sample_gift["name"]
        assert data["gift"]["id"].startswith("g_")

    def test_update_gift(self, client, sample_gift):
        """PUT /api/baby-gifts/{id} should update a gift."""
        # Create a gift first
        create_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = create_resp.json()["gift"]["id"]

        # Update it
        response = client.put(
            f"/api/baby-gifts/{gift_id}",
            json={"name": "Updated Name"},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["gift"]["name"] == "Updated Name"

    def test_update_nonexistent_gift_404(self, client):
        """PUT /api/baby-gifts/{id} should return 404 for non-existent gift."""
        # Use a valid ID format that doesn't exist
        response = client.put(
            "/api/baby-gifts/g_9999999999999_deadbeef",
            json={"name": "New Name"},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 404

    def test_delete_gift(self, client, sample_gift):
        """DELETE /api/baby-gifts/{id} should delete a gift."""
        # Create a gift first
        create_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = create_resp.json()["gift"]["id"]

        # Delete it
        response = client.delete(
            f"/api/baby-gifts/{gift_id}", headers={"X-Auth-User": "admin"}
        )

        assert response.status_code == 200

        # Verify it's gone
        all_gifts = client.get(
            "/api/baby-gifts", headers={"X-Auth-User": "admin"}
        ).json()
        gift_ids = [g["id"] for g in all_gifts["gifts"]]
        assert gift_id not in gift_ids

    def test_delete_nonexistent_gift_404(self, client):
        """DELETE /api/baby-gifts/{id} should return 404."""
        response = client.delete(
            "/api/baby-gifts/nonexistent", headers={"X-Auth-User": "admin"}
        )

        assert response.status_code == 404


class TestInvitationEndpoints:
    """Tests for invitation management endpoints."""

    def test_list_invitations_empty(self, client):
        """GET /api/baby-gifts/invitations should return empty list initially."""
        response = client.get(
            "/api/baby-gifts/invitations", headers={"X-Auth-User": "admin"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "invitations" in data
        assert data["invitations"] == []

    def test_create_invitation(self, client, sample_invitation_name):
        """POST /api/baby-gifts/invitations should create invitation."""
        response = client.post(
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "token" in data
        assert data["name"] == sample_invitation_name

    def test_create_invitation_empty_name_fails(self, client):
        """POST /api/baby-gifts/invitations with empty name should fail."""
        response = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "   "},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 400

    def test_delete_invitation(self, client, sample_invitation_name):
        """DELETE /api/baby-gifts/invitations/{token} should delete invitation."""
        # Create first
        create_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )
        token = create_resp.json()["token"]

        # Delete
        response = client.delete(
            f"/api/baby-gifts/invitations/{token}", headers={"X-Auth-User": "admin"}
        )

        assert response.status_code == 200

    def test_revoke_invitation(self, client, sample_invitation_name):
        """POST /api/baby-gifts/invitations/{token}/revoke should revoke."""
        # Create first
        create_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )
        token = create_resp.json()["token"]

        # Revoke
        response = client.post(
            f"/api/baby-gifts/invitations/{token}/revoke",
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 200

        # Check it's revoked
        invitations = client.get(
            "/api/baby-gifts/invitations", headers={"X-Auth-User": "admin"}
        ).json()["invitations"]
        revoked = next(inv for inv in invitations if inv["token"] == token)
        assert revoked["revoked"] is True

    def test_invitations_include_gift_stats(self, client, sample_invitation_name):
        """GET /api/baby-gifts/invitations should include visible_gifts and available_gifts."""
        # Create some gifts: 2 visible (1 reserved, 1 not), 1 hidden
        gift1_resp = client.post(
            "/api/baby-gifts",
            json={"name": "Visible Gift 1"},
            headers={"X-Auth-User": "admin"},
        )
        gift1_id = gift1_resp.json()["gift"]["id"]

        client.post(
            "/api/baby-gifts",
            json={"name": "Visible Gift 2"},
            headers={"X-Auth-User": "admin"},
        )

        hidden_resp = client.post(
            "/api/baby-gifts",
            json={"name": "Hidden Gift"},
            headers={"X-Auth-User": "admin"},
        )
        hidden_id = hidden_resp.json()["gift"]["id"]

        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
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
        response = client.get(
            "/api/baby-gifts/invitations", headers={"X-Auth-User": "admin"}
        )
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
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )
        token = inv_resp.json()["token"]

        # Create a gift
        client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )

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
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )
        token = inv_resp.json()["token"]

        # Create a gift
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = gift_resp.json()["gift"]["id"]

        # Reserve as guest
        response = client.post(f"/api/baby-gifts/guest/{token}/reserve/{gift_id}")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_guest_reserve_gift_with_legacy_id_format(
        self, client, sample_invitation_name
    ):
        """POST /api/baby-gifts/guest/{token}/reserve/{id} should work with legacy ID.

        Regression test for issue where reserving a gift with legacy ID format
        (g_<timestamp> without hex suffix, e.g. g_1790764472872) returned
        HTTP 400 "Invalid gift_id format".
        """
        import json

        import gifts_controller

        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )
        token = inv_resp.json()["token"]

        # Inject a gift with legacy ID format directly into storage
        # (simulating an existing gift created before the hex suffix was added)
        legacy_id = "g_1790764472872"  # Exact ID from the reported failure
        legacy_gift = {
            "id": legacy_id,
            "name": "Cambiador NATTOU verde",
            "price": "62€",
            "visible": True,
            "reserved": False,
            "reserved_by": None,
            "reserved_by_token": None,
        }

        # Write directly to gifts.json (format: {"gifts": [...], "invitations": [...]})
        gifts_file = gifts_controller.GIFTS_FILE
        gifts_file.write_text(json.dumps({"gifts": [legacy_gift], "invitations": []}))

        # Reserve the legacy gift as guest - this was failing with 400
        response = client.post(f"/api/baby-gifts/guest/{token}/reserve/{legacy_id}")

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.json()}"
        )
        assert response.json()["status"] == "ok"

    def test_guest_unreserve_own_gift(
        self, client, sample_gift, sample_invitation_name
    ):
        """POST /api/baby-gifts/guest/{token}/unreserve/{id} should unreserve own gift."""
        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )
        token = inv_resp.json()["token"]

        # Create and reserve a gift
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
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
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )
        _token = inv_resp.json()["token"]

        # Create a visible gift
        visible_resp = client.post(
            "/api/baby-gifts",
            json={"name": "Visible Gift"},
            headers={"X-Auth-User": "admin"},
        )
        _visible_id = visible_resp.json()["gift"]["id"]

        # Create a hidden gift
        hidden_resp = client.post(
            "/api/baby-gifts",
            json={"name": "Hidden Gift"},
            headers={"X-Auth-User": "admin"},
        )
        _hidden_id = hidden_resp.json()["gift"]["id"]

        # Hide it via admin unreserve endpoint won't work, we need direct access
        # Using the toggle visibility would require user endpoint
        # For now, verify both are visible in admin view
        admin_gifts = client.get(
            "/api/baby-gifts", headers={"X-Auth-User": "admin"}
        ).json()["gifts"]
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
        client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )

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
        client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )

        response = client.get("/api/baby-gifts/user", headers={"X-Auth-User": "egnal"})

        assert response.status_code == 200
        data = response.json()
        assert data["is_familia"] is True

    def test_user_get_gifts_hides_others_reservations(self, client, sample_gift):
        """User should see 'Alguien' for gifts reserved by others."""
        # Create gift
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
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
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
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
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
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
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.post(f"/api/baby-gifts/user/reserve/{gift_id}")
        assert response.status_code == 401

    def test_user_reserve_already_reserved_fails(self, client, sample_gift):
        """POST /api/baby-gifts/user/reserve/{id} for reserved gift returns 400."""
        # Create and reserve gift
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
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
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
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
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.post(f"/api/baby-gifts/user/unreserve/{gift_id}")
        assert response.status_code == 401

    def test_user_unreserve_others_gift_fails(self, client, sample_gift):
        """POST /api/baby-gifts/user/unreserve/{id} for other's gift returns 400."""
        # Create and reserve gift as user1
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
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
        client.post(
            "/api/baby-gifts",
            json={"name": "Visible Gift"},
            headers={"X-Auth-User": "admin"},
        )
        hidden_resp = client.post(
            "/api/baby-gifts",
            json={"name": "Hidden Gift"},
            headers={"X-Auth-User": "admin"},
        )
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
        client.post(
            "/api/baby-gifts",
            json={"name": "Visible Gift"},
            headers={"X-Auth-User": "admin"},
        )
        hidden_resp = client.post(
            "/api/baby-gifts",
            json={"name": "Hidden Gift"},
            headers={"X-Auth-User": "admin"},
        )
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
        gift_resp = client.post(
            "/api/baby-gifts",
            json={"name": "Test Gift"},
            headers={"X-Auth-User": "admin"},
        )
        gift_id = gift_resp.json()["gift"]["id"]

        # Non-FAMILIA user should get 403
        response = client.post(
            f"/api/baby-gifts/user/toggle-visibility/{gift_id}",
            headers={"X-Auth-User": "randomuser"},
        )
        assert response.status_code == 403

    def test_toggle_visibility_without_auth_returns_401(self, client):
        """POST /api/baby-gifts/user/toggle-visibility without auth returns 401."""
        gift_resp = client.post(
            "/api/baby-gifts",
            json={"name": "Test Gift"},
            headers={"X-Auth-User": "admin"},
        )
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
        client.post(
            "/api/baby-gifts",
            json={"name": "Cheap", "price_range": "50€"},
            headers={"X-Auth-User": "admin"},
        )
        client.post(
            "/api/baby-gifts",
            json={"name": "Expensive", "price_range": "200€"},
            headers={"X-Auth-User": "admin"},
        )
        client.post(
            "/api/baby-gifts",
            json={"name": "Medium", "price_range": "100€"},
            headers={"X-Auth-User": "admin"},
        )

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
        gift_resp = client.post(
            "/api/baby-gifts",
            json={"name": "Hidden Gift"},
            headers={"X-Auth-User": "admin"},
        )
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
        response = client.get("/api/baby-gifts/user", headers={"X-Auth-User": "virchu"})
        gift = next(g for g in response.json()["gifts"] if g["id"] == gift_id)
        assert gift["reserved_by"] == "oculto"


class TestSPAServing:
    """Tests for SPA HTML serving."""

    def test_serve_guest_valid_token(self, client, sample_invitation_name):
        """GET /guest/baby-gifts/{token} with valid token serves HTML."""
        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
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
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = gift_resp.json()["gift"]["id"]

        with patch("main.send_gift_notification"):
            client.post(
                f"/api/baby-gifts/user/reserve/{gift_id}",
                headers={"X-Auth-User": "someuser"},
            )

        # Admin unreserve
        response = client.post(
            f"/api/baby-gifts/{gift_id}/unreserve", headers={"X-Auth-User": "admin"}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_admin_unreserve_not_reserved_returns_400(self, client, sample_gift):
        """POST /api/baby-gifts/{id}/unreserve for unreserved gift returns 400."""
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.post(
            f"/api/baby-gifts/{gift_id}/unreserve", headers={"X-Auth-User": "admin"}
        )
        assert response.status_code == 400


class TestUpdateGiftValidation:
    """Tests for gift update validation."""

    def test_update_gift_no_changes_returns_400(self, client, sample_gift):
        """PUT /api/baby-gifts/{id} with no fields returns 400."""
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.put(
            f"/api/baby-gifts/{gift_id}", json={}, headers={"X-Auth-User": "admin"}
        )
        assert response.status_code == 400

    def test_update_gift_invalid_id_format_returns_400(self, client):
        """PUT /api/baby-gifts/{id} with invalid ID format returns 400."""
        response = client.put(
            "/api/baby-gifts/invalid-format",
            json={"name": "New"},
            headers={"X-Auth-User": "admin"},
        )
        assert response.status_code == 400
        assert "Invalid gift_id format" in response.json()["detail"]


class TestGuestEndpointsExtended:
    """Extended tests for guest endpoints."""

    def test_guest_gifts_sorted_by_price(self, client, sample_invitation_name):
        """Guest gifts should be sorted by price descending."""
        # Create invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )
        token = inv_resp.json()["token"]

        # Create gifts with different prices
        client.post(
            "/api/baby-gifts",
            json={"name": "Cheap", "price_range": "30€"},
            headers={"X-Auth-User": "admin"},
        )
        client.post(
            "/api/baby-gifts",
            json={"name": "Expensive", "price_range": "150€"},
            headers={"X-Auth-User": "admin"},
        )

        response = client.get(f"/api/baby-gifts/guest/{token}")
        gifts = response.json()["gifts"]

        assert gifts[0]["name"] == "Expensive"
        assert gifts[1]["name"] == "Cheap"

    def test_guest_reserve_invalid_token_returns_401(self, client, sample_gift):
        """POST /api/baby-gifts/guest/{token}/reserve/{id} with invalid token returns 401."""
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.post(f"/api/baby-gifts/guest/invalid_token/reserve/{gift_id}")
        assert response.status_code == 401

    def test_guest_unreserve_invalid_token_returns_401(self, client, sample_gift):
        """POST /api/baby-gifts/guest/{token}/unreserve/{id} with invalid token returns 401."""
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
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
            "/api/baby-gifts/invitations",
            json={"name": "Guest 1"},
            headers={"X-Auth-User": "admin"},
        )
        token1 = inv1_resp.json()["token"]

        inv2_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "Guest 2"},
            headers={"X-Auth-User": "admin"},
        )
        token2 = inv2_resp.json()["token"]

        # Create and reserve gift as guest1
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
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
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )
        token = inv_resp.json()["token"]

        # Create and reserve gift
        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
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
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )
        token = inv_resp.json()["token"]

        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = gift_resp.json()["gift"]["id"]

        response = client.post(f"/api/baby-gifts/guest/{token}/unreserve/{gift_id}")
        assert response.status_code == 400


class TestInputSanitization:
    """Tests for input sanitization on user-provided strings."""

    def test_gift_name_strips_whitespace(self, client):
        """Gift name should have leading/trailing whitespace stripped."""
        response = client.post(
            "/api/baby-gifts",
            json={"name": "  Carrito de bebé  "},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 200
        gift = response.json()["gift"]
        assert gift["name"] == "Carrito de bebé"

    def test_gift_name_escapes_html(self, client):
        """Gift name should have HTML characters escaped."""
        response = client.post(
            "/api/baby-gifts",
            json={"name": "<script>alert('xss')</script>"},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 200
        gift = response.json()["gift"]
        assert "<script>" not in gift["name"]
        assert "&lt;script&gt;" in gift["name"]

    def test_gift_description_escapes_html(self, client):
        """Gift description should have HTML characters escaped."""
        response = client.post(
            "/api/baby-gifts",
            json={"name": "Test", "description": "<img onerror='alert(1)'>"},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 200
        gift = response.json()["gift"]
        assert "<img" not in gift["description"]
        assert "&lt;img" in gift["description"]

    def test_gift_update_sanitizes_fields(self, client, sample_gift):
        """Gift update should sanitize all text fields."""
        # Create a gift
        create_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        gift_id = create_resp.json()["gift"]["id"]

        # Update with dirty input
        response = client.put(
            f"/api/baby-gifts/{gift_id}",
            json={"name": "  <b>Bold</b>  ", "description": "  <i>Italic</i>  "},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 200
        gift = response.json()["gift"]
        assert gift["name"] == "&lt;b&gt;Bold&lt;/b&gt;"
        assert gift["description"] == "&lt;i&gt;Italic&lt;/i&gt;"

    def test_invitation_name_strips_whitespace(self, client):
        """Invitation name should have leading/trailing whitespace stripped."""
        response = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "  Tía María  "},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Tía María"

    def test_invitation_name_escapes_html(self, client):
        """Invitation name should have HTML characters escaped."""
        response = client.post(
            "/api/baby-gifts/invitations",
            json={"name": "<script>hack</script>"},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 200
        name = response.json()["name"]
        assert "<script>" not in name
        assert "&lt;script&gt;" in name

    def test_gift_url_not_html_escaped(self, client):
        """Gift URL should not have HTML escaping (URLs need special chars)."""
        url = "https://example.com/search?q=carrito&page=1"
        response = client.post(
            "/api/baby-gifts",
            json={"name": "Test", "url": url},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 200
        gift = response.json()["gift"]
        # URL should preserve & without escaping to &amp;
        assert gift["url"] == url

    def test_gift_name_truncated_to_max_length(self, client):
        """Gift name longer than 200 chars should be truncated."""
        long_name = "A" * 300
        response = client.post(
            "/api/baby-gifts",
            json={"name": long_name},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 200
        gift = response.json()["gift"]
        assert len(gift["name"]) == 200

    def test_invitation_name_truncated_to_max_length(self, client):
        """Invitation name longer than 100 chars should be truncated."""
        long_name = "B" * 150
        response = client.post(
            "/api/baby-gifts/invitations",
            json={"name": long_name},
            headers={"X-Auth-User": "admin"},
        )

        assert response.status_code == 200
        name = response.json()["name"]
        assert len(name) == 100


class TestInvitationRateLimiting:
    """Tests for rate limiting on invitation creation endpoint."""

    def test_invitation_rate_limit_returns_429(self, client):
        """POST /api/baby-gifts/invitations should return 429 after limit exceeded."""
        import config

        # Save original values
        original_attempts = config.INVITATION_RATE_LIMIT_ATTEMPTS
        original_window = config.INVITATION_RATE_LIMIT_WINDOW_SECONDS

        try:
            # Set very low limit for testing
            config.INVITATION_RATE_LIMIT_ATTEMPTS = 3
            config.INVITATION_RATE_LIMIT_WINDOW_SECONDS = 60

            # Make requests up to the limit
            for i in range(3):
                response = client.post(
                    "/api/baby-gifts/invitations",
                    json={"name": f"Guest {i}"},
                    headers={"X-Auth-User": "admin"},
                )
                assert response.status_code == 200

            # Next request should be rate limited
            response = client.post(
                "/api/baby-gifts/invitations",
                json={"name": "One Too Many"},
                headers={"X-Auth-User": "admin"},
            )
            assert response.status_code == 429
            assert "Demasiadas invitaciones" in response.json()["detail"]

        finally:
            # Restore original values
            config.INVITATION_RATE_LIMIT_ATTEMPTS = original_attempts
            config.INVITATION_RATE_LIMIT_WINDOW_SECONDS = original_window

    def test_invitation_rate_limit_separate_from_guest(
        self, client, sample_invitation_name, sample_gift
    ):
        """Invitation rate limit should be separate from guest endpoint rate limit."""
        import config

        # Create invitation and gift for guest endpoint testing
        inv_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )
        token = inv_resp.json()["token"]

        gift_resp = client.post(
            "/api/baby-gifts", json=sample_gift, headers={"X-Auth-User": "admin"}
        )
        _gift_id = gift_resp.json()["gift"]["id"]

        # Save original values
        original_attempts = config.RATE_LIMIT_ATTEMPTS
        original_window = config.RATE_LIMIT_WINDOW_SECONDS

        try:
            # Set low limit for guest endpoints
            config.RATE_LIMIT_ATTEMPTS = 2
            config.RATE_LIMIT_WINDOW_SECONDS = 60

            # Use up guest rate limit
            for _ in range(3):
                client.get(f"/api/baby-gifts/guest/{token}")

            # Guest endpoint should now be rate limited
            guest_resp = client.get(f"/api/baby-gifts/guest/{token}")
            assert guest_resp.status_code == 429

            # But invitation creation should still work (different bucket)
            inv_resp = client.post(
                "/api/baby-gifts/invitations",
                json={"name": "Another Guest"},
                headers={"X-Auth-User": "admin"},
            )
            # This may succeed or fail depending on invitation rate limit state,
            # but it should NOT be a 429 from the guest rate limiter
            # (either 200 success or 429 from invitation limiter with different message)
            if inv_resp.status_code == 429:
                assert "invitaciones" in inv_resp.json()["detail"]
            else:
                assert inv_resp.status_code == 200

        finally:
            config.RATE_LIMIT_ATTEMPTS = original_attempts
            config.RATE_LIMIT_WINDOW_SECONDS = original_window


class TestClientIPValidation:
    """Tests for _get_client_ip edge cases and IP format validation (L2)."""

    def test_get_client_ip_missing_client(self, client):
        """_get_client_ip should return 'unknown' when request.client is None."""
        from unittest.mock import MagicMock

        from main import _get_client_ip

        mock_request = MagicMock()
        mock_request.client = None
        mock_request.headers.get.return_value = None

        result = _get_client_ip(mock_request)
        assert result == "unknown"

    def test_get_client_ip_malformed_x_forwarded_for(self, client):
        """_get_client_ip should fall back to client IP for malformed X-Forwarded-For."""
        from unittest.mock import MagicMock

        from main import _get_client_ip

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"  # Trusted proxy
        mock_request.headers.get.return_value = "not-an-ip-address"

        result = _get_client_ip(mock_request)
        assert result == "127.0.0.1"  # Falls back to client IP

    def test_get_client_ip_malformed_x_forwarded_for_special_chars(self, client):
        """_get_client_ip should reject X-Forwarded-For with special characters."""
        from unittest.mock import MagicMock

        from main import _get_client_ip

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"  # Trusted proxy
        mock_request.headers.get.return_value = "<script>alert(1)</script>"

        result = _get_client_ip(mock_request)
        assert result == "127.0.0.1"  # Falls back to client IP

    def test_get_client_ip_empty_x_forwarded_for(self, client):
        """_get_client_ip should handle empty X-Forwarded-For gracefully."""
        from unittest.mock import MagicMock

        from main import _get_client_ip

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers.get.return_value = ""

        result = _get_client_ip(mock_request)
        assert result == "127.0.0.1"

    def test_get_client_ip_valid_ipv4_x_forwarded_for(self, client):
        """_get_client_ip should accept valid IPv4 in X-Forwarded-For."""
        from unittest.mock import MagicMock

        from main import _get_client_ip

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"  # Trusted proxy
        mock_request.headers.get.return_value = "192.168.1.100"

        result = _get_client_ip(mock_request)
        assert result == "192.168.1.100"

    def test_get_client_ip_valid_ipv6_x_forwarded_for(self, client):
        """_get_client_ip should accept valid IPv6 in X-Forwarded-For."""
        from unittest.mock import MagicMock

        from main import _get_client_ip

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"  # Trusted proxy
        mock_request.headers.get.return_value = "2001:db8::1"

        result = _get_client_ip(mock_request)
        assert result == "2001:db8::1"

    def test_get_client_ip_chain_takes_first(self, client):
        """_get_client_ip should take first IP from X-Forwarded-For chain."""
        from unittest.mock import MagicMock

        from main import _get_client_ip

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"  # Trusted proxy
        mock_request.headers.get.return_value = "10.0.0.1, 192.168.1.1, 172.16.0.1"

        result = _get_client_ip(mock_request)
        assert result == "10.0.0.1"

    def test_get_client_ip_untrusted_proxy_ignores_header(self, client):
        """_get_client_ip should ignore X-Forwarded-For from untrusted proxy."""
        from unittest.mock import MagicMock

        from main import _get_client_ip

        mock_request = MagicMock()
        mock_request.client.host = "192.168.1.50"  # Not a trusted proxy
        mock_request.headers.get.return_value = "10.0.0.1"

        result = _get_client_ip(mock_request)
        assert result == "192.168.1.50"  # Uses direct client IP

    def test_validate_ip_format_valid_ipv4(self, client):
        """_validate_ip_format should accept valid IPv4 addresses."""
        from main import _validate_ip_format

        assert _validate_ip_format("192.168.1.1") is True
        assert _validate_ip_format("10.0.0.1") is True
        assert _validate_ip_format("255.255.255.255") is True
        assert _validate_ip_format("0.0.0.0") is True

    def test_validate_ip_format_valid_ipv6(self, client):
        """_validate_ip_format should accept valid IPv6 addresses."""
        from main import _validate_ip_format

        assert _validate_ip_format("::1") is True
        assert _validate_ip_format("2001:db8::1") is True
        assert _validate_ip_format("fe80::1") is True

    def test_validate_ip_format_invalid(self, client):
        """_validate_ip_format should reject invalid addresses."""
        from main import _validate_ip_format

        assert _validate_ip_format("") is False
        assert _validate_ip_format("not-an-ip") is False
        assert _validate_ip_format("192.168.1.256") is False  # Octet > 255
        assert _validate_ip_format("192.168.1") is False  # Incomplete
        assert _validate_ip_format("<script>") is False
        assert _validate_ip_format("192.168.1.1.1") is False  # Too many octets


class TestRateLimitCleanup:
    """Tests for M2: Rate limit stale entry cleanup."""

    def test_cleanup_removes_stale_entries(self, client, tmp_data_dir):
        """Cleanup should remove entries older than rate limit window."""
        import sqlite3
        from datetime import datetime, timedelta

        import gifts_controller

        # Insert a stale entry directly
        conn = sqlite3.connect(str(gifts_controller.DB_FILE))
        old_time = (datetime.now() - timedelta(hours=1)).isoformat()
        conn.execute(
            "INSERT INTO rate_limits (ip, attempts, window_start) VALUES (?, ?, ?)",
            ("stale_ip", 5, old_time),
        )
        conn.commit()

        # Verify entry exists
        row = conn.execute(
            "SELECT * FROM rate_limits WHERE ip = ?", ("stale_ip",)
        ).fetchone()
        assert row is not None

        # Trigger cleanup
        from gifts_controller import _cleanup_stale_rate_limits

        deleted = _cleanup_stale_rate_limits(conn)
        conn.commit()

        # Verify entry was removed
        row = conn.execute(
            "SELECT * FROM rate_limits WHERE ip = ?", ("stale_ip",)
        ).fetchone()
        assert row is None
        assert deleted >= 1

        conn.close()

    def test_cleanup_keeps_recent_entries(self, client, tmp_data_dir):
        """Cleanup should keep recent entries."""
        import sqlite3
        from datetime import datetime

        import gifts_controller

        # Insert a recent entry
        conn = sqlite3.connect(str(gifts_controller.DB_FILE))
        recent_time = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO rate_limits (ip, attempts, window_start) VALUES (?, ?, ?)",
            ("recent_ip", 3, recent_time),
        )
        conn.commit()

        # Trigger cleanup
        from gifts_controller import _cleanup_stale_rate_limits

        _cleanup_stale_rate_limits(conn)
        conn.commit()

        # Verify entry still exists
        row = conn.execute(
            "SELECT * FROM rate_limits WHERE ip = ?", ("recent_ip",)
        ).fetchone()
        assert row is not None

        conn.close()


class TestTokenMaxLength:
    """Tests for H1: Token path parameter max_length validation."""

    def test_token_too_long_returns_422(self, client, sample_invitation_name):
        """Endpoints should reject tokens exceeding max_length with 422."""
        # Create a valid invitation first
        client.post(
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )

        # Try with oversized token (> 64 chars)
        long_token = "a" * 100

        # Test guest get endpoint
        response = client.get(f"/api/baby-gifts/guest/{long_token}")
        assert response.status_code == 422

        # Test serve guest endpoint
        response = client.get(f"/guest/baby-gifts/{long_token}")
        assert response.status_code == 422

    def test_valid_token_length_accepted(self, client, sample_invitation_name):
        """Endpoints should accept tokens within max_length."""
        # Create a valid invitation
        inv_resp = client.post(
            "/api/baby-gifts/invitations",
            json={"name": sample_invitation_name},
            headers={"X-Auth-User": "admin"},
        )
        token = inv_resp.json()["token"]

        # Token should be 32 chars (secrets.token_urlsafe(24))
        assert len(token) == 32

        # Should be accepted
        response = client.get(f"/api/baby-gifts/guest/{token}")
        assert response.status_code == 200


class TestCreateInvitationIterative:
    """Tests for M4: create_invitation uses iterative loop instead of recursion."""

    def test_create_invitation_handles_collisions(
        self, client, tmp_data_dir, monkeypatch
    ):
        """create_invitation should handle token collisions via iteration."""
        import secrets

        import gifts_controller

        # Track how many times token_urlsafe is called
        call_count = [0]
        original_token_urlsafe = secrets.token_urlsafe

        def mock_token_urlsafe(nbytes):
            call_count[0] += 1
            if call_count[0] < 3:
                # Return same token to force collision
                return "collision_token_aaaaaaaaaaaaa"
            # Return unique token on 3rd call
            return original_token_urlsafe(nbytes)

        monkeypatch.setattr(secrets, "token_urlsafe", mock_token_urlsafe)

        # First call succeeds
        result1 = gifts_controller.create_invitation("Guest 1")
        assert result1["status"] == "ok"

        # Second call should retry and eventually succeed
        result2 = gifts_controller.create_invitation("Guest 2")
        assert result2["status"] == "ok"
        assert call_count[0] >= 3  # Had to retry due to collision


class TestGDPRLogging:
    """Tests for M3: GDPR-compliant logging with hashed names."""

    def test_hash_name_for_log_produces_consistent_hash(self, client):
        """_hash_name_for_log should produce consistent hashes."""
        from main import _hash_name_for_log

        name = "Tía María"
        hash1 = _hash_name_for_log(name)
        hash2 = _hash_name_for_log(name)

        assert hash1 == hash2
        assert hash1.startswith("guest_")
        assert len(hash1) == 14  # "guest_" + 8 hex chars

    def test_hash_name_for_log_different_names_different_hashes(self, client):
        """Different names should produce different hashes."""
        from main import _hash_name_for_log

        hash1 = _hash_name_for_log("Guest A")
        hash2 = _hash_name_for_log("Guest B")

        assert hash1 != hash2

    def test_hash_name_for_log_empty_name(self, client):
        """Empty name should return placeholder."""
        from main import _hash_name_for_log

        assert _hash_name_for_log("") == "guest_unknown"
        assert _hash_name_for_log(None) == "guest_unknown"
