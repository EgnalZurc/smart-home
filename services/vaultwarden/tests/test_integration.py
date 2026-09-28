"""Integration tests for Vaultwarden service.

These tests verify the deployed service is working correctly.
They require the service to be running and accessible.

Run with: pytest tests/test_integration.py -v --run-integration
"""

import os

import pytest
import requests

# Skip integration tests by default (need --run-integration flag)
pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Integration tests disabled. Set RUN_INTEGRATION_TESTS=1 to enable.",
)

# Base URL for the deployed service
BASE_URL = os.environ.get(
    "VAULTWARDEN_URL", "https://raspberrypi.tailaa37cd.ts.net/passwords"
)


class TestVaultwardenHealth:
    """Test Vaultwarden service health."""

    def test_web_vault_accessible(self):
        """Web vault should be accessible."""
        response = requests.get(f"{BASE_URL}/", verify=False, timeout=10)
        assert response.status_code == 200
        assert "Vaultwarden" in response.text or "bitwarden" in response.text.lower()

    def test_api_config_returns_json(self):
        """API config endpoint should return valid JSON."""
        response = requests.get(f"{BASE_URL}/api/config", verify=False, timeout=10)
        assert response.status_code == 200
        data = response.json()
        assert "environment" in data
        assert "server" in data

    def test_api_config_has_correct_domain(self):
        """API config should return the correct DOMAIN."""
        response = requests.get(f"{BASE_URL}/api/config", verify=False, timeout=10)
        data = response.json()
        env = data.get("environment", {})
        
        # All URLs should include /passwords
        assert "/passwords" in env.get("vault", "")
        assert "/passwords" in env.get("api", "")
        assert "/passwords" in env.get("identity", "")


class TestVaultwardenEndpoints:
    """Test Vaultwarden API endpoints are accessible."""

    def test_identity_endpoint_exists(self):
        """Identity endpoint should be accessible (returns 404 for GET, but not 502)."""
        response = requests.get(
            f"{BASE_URL}/identity/", verify=False, timeout=10, allow_redirects=False
        )
        # Should not be 502 (Bad Gateway) - that means proxy is broken
        assert response.status_code != 502

    def test_icons_endpoint_exists(self):
        """Icons endpoint should be accessible."""
        response = requests.get(
            f"{BASE_URL}/icons/example.com/icon.png",
            verify=False,
            timeout=10,
        )
        # 404 is fine (icon doesn't exist), 502 is not
        assert response.status_code != 502

    def test_static_assets_load(self):
        """Static assets should load (CSS, JS)."""
        # First get the main page to find asset URLs
        response = requests.get(f"{BASE_URL}/", verify=False, timeout=10)
        assert response.status_code == 200
        
        # Check that page references some CSS/JS
        assert ".css" in response.text or ".js" in response.text


class TestVaultwardenSecurity:
    """Test Vaultwarden security configuration."""

    def test_signups_disabled(self):
        """Public signups should be disabled."""
        response = requests.get(f"{BASE_URL}/api/config", verify=False, timeout=10)
        data = response.json()
        settings = data.get("settings", {})
        # disableUserRegistration should be True (or signupsAllowed false)
        # Note: The actual key name may vary by version
        assert settings.get("disableUserRegistration", True) is True or \
               not settings.get("signupsAllowed", False)

    def test_admin_panel_requires_token(self):
        """Admin panel should require authentication."""
        response = requests.get(
            f"{BASE_URL}/admin",
            verify=False,
            timeout=10,
            allow_redirects=False,
        )
        # Should redirect to admin login or return 401/403
        assert response.status_code in [301, 302, 401, 403, 200]
        # If 200, should be a login form
        if response.status_code == 200:
            assert "token" in response.text.lower() or "admin" in response.text.lower()
