"""Unit tests for migrate_profiles.py - one-time profile migration."""

import sys
from io import StringIO
from unittest.mock import patch

from migrate_profiles import INITIAL_PROFILES, main


class TestMigrateProfiles:
    def test_initial_profiles_defined(self):
        """Verify the initial profile assignments are configured."""
        assert "egnal" in INITIAL_PROFILES
        assert "virchi" in INITIAL_PROFILES
        assert INITIAL_PROFILES["egnal"] == "SUPER"
        assert INITIAL_PROFILES["virchi"] == "FAMILIA_PRINCIPAL"

    @patch("migrate_profiles.user_profiles")
    def test_main_calls_set_profile_for_each_user(self, mock_user_profiles):
        """Test that main() assigns profiles to all defined users."""
        mock_user_profiles.set_profile.return_value = None

        # Capture stdout
        captured = StringIO()
        with patch.object(sys, "stdout", captured):
            main()

        # Verify set_profile was called for each user
        assert mock_user_profiles.set_profile.call_count == len(INITIAL_PROFILES)
        mock_user_profiles.set_profile.assert_any_call("egnal", "SUPER")
        mock_user_profiles.set_profile.assert_any_call("virchi", "FAMILIA_PRINCIPAL")

    @patch("migrate_profiles.user_profiles")
    def test_main_prints_success_messages(self, mock_user_profiles):
        """Test that success messages are printed."""
        mock_user_profiles.set_profile.return_value = None

        captured = StringIO()
        with patch.object(sys, "stdout", captured):
            main()

        output = captured.getvalue()
        assert "egnal → SUPER" in output
        assert "virchi → FAMILIA_PRINCIPAL" in output
        assert "Done." in output

    @patch("migrate_profiles.user_profiles")
    def test_main_handles_errors_gracefully(self, mock_user_profiles):
        """Test that errors don't crash the migration."""
        mock_user_profiles.set_profile.side_effect = Exception("Database error")

        captured_out = StringIO()
        captured_err = StringIO()
        with (
            patch.object(sys, "stdout", captured_out),
            patch.object(sys, "stderr", captured_err),
        ):
            main()

        # Should print error messages but still complete
        assert "Done." in captured_out.getvalue()
        assert "Database error" in captured_err.getvalue()

    @patch("migrate_profiles.user_profiles")
    def test_main_prints_db_path(self, mock_user_profiles):
        """Test that migration target is logged."""
        mock_user_profiles.set_profile.return_value = None

        captured = StringIO()
        with patch.object(sys, "stdout", captured):
            main()

        assert "Migration target:" in captured.getvalue()
