"""Unit tests for invitation management."""

from datetime import datetime, timedelta

import pytest


class TestInvitationCreation:
    """Tests for invitation creation."""

    def test_create_invitation_generates_token(self, tmp_data_dir):
        """create_invitation should generate a unique token."""
        from gifts_controller import create_invitation
        
        result = create_invitation("Test Guest")
        
        assert result["status"] == "ok"
        assert "token" in result
        assert len(result["token"]) >= 24  # secure token length
        assert result["name"] == "Test Guest"

    def test_create_invitation_sets_expiry(self, tmp_data_dir):
        """create_invitation should set expiry to 6 months."""
        from gifts_controller import create_invitation, INVITATION_EXPIRY_DAYS
        
        result = create_invitation("Expiring Guest")
        
        assert "expires_at" in result
        created = datetime.fromisoformat(result["created_at"])
        expires = datetime.fromisoformat(result["expires_at"])
        
        # Should be approximately 6 months
        diff_days = (expires - created).days
        assert abs(diff_days - INVITATION_EXPIRY_DAYS) <= 1

    def test_create_multiple_unique_tokens(self, tmp_data_dir):
        """Multiple invitations should have unique tokens."""
        from gifts_controller import create_invitation
        
        tokens = set()
        for i in range(10):
            result = create_invitation(f"Guest {i}")
            tokens.add(result["token"])
        
        assert len(tokens) == 10


class TestInvitationValidation:
    """Tests for invitation validation."""

    def test_validate_valid_invitation(self, tmp_data_dir):
        """validate_invitation should return guest info for valid token."""
        from gifts_controller import create_invitation, validate_invitation
        
        created = create_invitation("Valid Guest")
        result = validate_invitation(created["token"])
        
        assert result is not None
        assert result["name"] == "Valid Guest"
        assert result["token"] == created["token"]

    def test_validate_invalid_token(self, tmp_data_dir):
        """validate_invitation should return None for invalid token."""
        from gifts_controller import validate_invitation
        
        result = validate_invitation("invalid_token_12345")
        assert result is None

    def test_validate_updates_last_access(self, tmp_data_dir):
        """validate_invitation should update last_access timestamp."""
        from gifts_controller import create_invitation, validate_invitation
        import time
        
        created = create_invitation("Access Guest")
        first_access = validate_invitation(created["token"])
        time.sleep(0.1)
        second_access = validate_invitation(created["token"])
        
        assert first_access["last_access"] != second_access["last_access"]

    def test_validate_revoked_invitation_fails(self, tmp_data_dir):
        """validate_invitation should return None for revoked invitation."""
        from gifts_controller import create_invitation, revoke_invitation, validate_invitation
        
        created = create_invitation("Revoked Guest")
        revoke_invitation(created["token"])
        result = validate_invitation(created["token"])
        
        assert result is None


class TestInvitationListing:
    """Tests for listing invitations."""

    def test_list_invitations_returns_all(self, tmp_data_dir):
        """list_invitations should return all created invitations."""
        from gifts_controller import create_invitation, list_invitations
        
        create_invitation("Guest A")
        create_invitation("Guest B")
        create_invitation("Guest C")
        
        invitations = list_invitations()
        
        assert len(invitations) == 3
        names = [inv["name"] for inv in invitations]
        assert "Guest A" in names
        assert "Guest B" in names
        assert "Guest C" in names

    def test_list_invitations_ordered_by_date(self, tmp_data_dir):
        """list_invitations should be ordered by created_at desc."""
        from gifts_controller import create_invitation, list_invitations
        import time
        
        create_invitation("First")
        time.sleep(0.05)
        create_invitation("Second")
        time.sleep(0.05)
        create_invitation("Third")
        
        invitations = list_invitations()
        
        # Most recent first
        assert invitations[0]["name"] == "Third"
        assert invitations[2]["name"] == "First"

    def test_list_shows_revoked_status(self, tmp_data_dir):
        """list_invitations should show revoked status."""
        from gifts_controller import create_invitation, list_invitations, revoke_invitation
        
        created = create_invitation("To Revoke")
        revoke_invitation(created["token"])
        
        invitations = list_invitations()
        
        revoked_inv = next(inv for inv in invitations if inv["token"] == created["token"])
        assert revoked_inv["revoked"] is True


class TestInvitationDeletion:
    """Tests for invitation deletion."""

    def test_delete_invitation_removes_it(self, tmp_data_dir):
        """delete_invitation should remove the invitation."""
        from gifts_controller import create_invitation, delete_invitation, list_invitations
        
        created = create_invitation("To Delete")
        result = delete_invitation(created["token"])
        
        assert result["status"] == "ok"
        invitations = list_invitations()
        tokens = [inv["token"] for inv in invitations]
        assert created["token"] not in tokens

    def test_delete_nonexistent_fails(self, tmp_data_dir):
        """delete_invitation should fail for non-existent token."""
        from gifts_controller import delete_invitation
        
        result = delete_invitation("nonexistent_token")
        
        assert result["status"] == "error"


class TestInvitationRevocation:
    """Tests for invitation revocation."""

    def test_revoke_marks_revoked(self, tmp_data_dir):
        """revoke_invitation should mark invitation as revoked."""
        from gifts_controller import create_invitation, list_invitations, revoke_invitation
        
        created = create_invitation("To Revoke")
        result = revoke_invitation(created["token"])
        
        assert result["status"] == "ok"
        
        invitations = list_invitations()
        revoked = next(inv for inv in invitations if inv["token"] == created["token"])
        assert revoked["revoked"] is True

    def test_revoke_nonexistent_fails(self, tmp_data_dir):
        """revoke_invitation should fail for non-existent token."""
        from gifts_controller import revoke_invitation
        
        result = revoke_invitation("nonexistent_token")
        
        assert result["status"] == "error"


class TestReservationCounting:
    """Tests for counting reservations per invitation."""

    def test_get_invitation_reservations_counts(self, tmp_data_dir):
        """get_invitation_reservations should count reserved gifts."""
        from gifts_controller import (
            add_gift,
            create_invitation,
            get_invitation_reservations,
            reserve_gift,
        )
        
        inv = create_invitation("Counting Guest")
        token = inv["token"]
        
        # Reserve 3 gifts and verify each reservation succeeds
        for i in range(3):
            gift = add_gift({"name": f"Gift {i}"})
            result = reserve_gift(gift["id"], token, "Guest")
            assert result["status"] == "ok", f"Failed to reserve gift {i}: {result}"
        
        count = get_invitation_reservations(token)
        assert count == 3

    def test_get_invitation_reservations_zero_for_none(self, tmp_data_dir):
        """get_invitation_reservations should return 0 for no reservations."""
        from gifts_controller import create_invitation, get_invitation_reservations
        
        inv = create_invitation("No Reservations")
        count = get_invitation_reservations(inv["token"])
        
        assert count == 0
