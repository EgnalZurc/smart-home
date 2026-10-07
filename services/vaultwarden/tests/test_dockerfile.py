"""Tests for Vaultwarden Dockerfile configuration.

These tests verify that the Dockerfile is correctly configured
without needing to build or run the container.
"""

import re
from pathlib import Path

import pytest

DOCKERFILE_PATH = Path(__file__).parent.parent / "Dockerfile"


@pytest.fixture
def dockerfile_content():
    """Read the Dockerfile content."""
    return DOCKERFILE_PATH.read_text()


class TestDockerfileStructure:
    """Test Dockerfile structure and configuration."""

    def test_dockerfile_exists(self):
        """Dockerfile should exist."""
        assert DOCKERFILE_PATH.exists(), "Dockerfile not found"

    def test_base_image_is_vaultwarden(self, dockerfile_content):
        """Should use official vaultwarden image."""
        assert "FROM vaultwarden/server" in dockerfile_content

    def test_domain_is_configured(self, dockerfile_content):
        """DOMAIN environment variable should be set correctly."""
        # Should contain the subpath /passwords
        assert "DOMAIN=" in dockerfile_content
        assert "/passwords" in dockerfile_content

    def test_domain_uses_https(self, dockerfile_content):
        """DOMAIN should use HTTPS for security."""
        match = re.search(r"DOMAIN=(\S+)", dockerfile_content)
        assert match, "DOMAIN not found"
        assert match.group(1).startswith("https://"), "DOMAIN must use HTTPS"

    def test_websocket_enabled(self, dockerfile_content):
        """WebSocket should be enabled for push notifications."""
        assert "WEBSOCKET_ENABLED=true" in dockerfile_content

    def test_signups_disabled(self, dockerfile_content):
        """Public signups should be disabled for security."""
        assert "SIGNUPS_ALLOWED=false" in dockerfile_content

    def test_healthcheck_defined(self, dockerfile_content):
        """Healthcheck should be defined."""
        assert "HEALTHCHECK" in dockerfile_content

    def test_healthcheck_uses_curl(self, dockerfile_content):
        """Healthcheck should use curl to verify the service."""
        # Extract HEALTHCHECK CMD (may span multiple lines with \)
        match = re.search(r"HEALTHCHECK.*CMD\s+(.+)", dockerfile_content, re.DOTALL)
        assert match, "HEALTHCHECK CMD not found"
        assert "curl" in match.group(1), "Healthcheck should use curl"

    def test_ports_exposed(self, dockerfile_content):
        """Required ports should be exposed."""
        assert "EXPOSE" in dockerfile_content
        assert "80" in dockerfile_content

    def test_admin_token_not_hardcoded(self, dockerfile_content):
        """ADMIN_TOKEN should NOT be in the Dockerfile (security)."""
        # ADMIN_TOKEN should be passed at runtime via environment
        assert "ADMIN_TOKEN=" not in dockerfile_content

    def test_no_sensitive_env_vars(self, dockerfile_content):
        """No sensitive environment variables should be hardcoded."""
        sensitive_patterns = [
            r"SMTP_PASSWORD=",
            r"YUBICO_SECRET_KEY=",
            r"DUO_SKEY=",
        ]
        for pattern in sensitive_patterns:
            assert not re.search(pattern, dockerfile_content), (
                f"Sensitive var {pattern} should not be in Dockerfile"
            )


class TestDockerfileEnvironment:
    """Test environment variable configuration."""

    def test_timezone_configured(self, dockerfile_content):
        """Timezone should be set."""
        assert "TZ=" in dockerfile_content

    def test_timezone_is_europe_madrid(self, dockerfile_content):
        """Timezone should be Europe/Madrid."""
        assert "TZ=Europe/Madrid" in dockerfile_content

    def test_rocket_address_configured(self, dockerfile_content):
        """Rocket should listen on all interfaces."""
        assert "ROCKET_ADDRESS=0.0.0.0" in dockerfile_content

    def test_rocket_port_configured(self, dockerfile_content):
        """Rocket should use port 80."""
        assert "ROCKET_PORT=80" in dockerfile_content

    def test_rocket_profile_is_release(self, dockerfile_content):
        """Rocket should use release profile for production."""
        assert "ROCKET_PROFILE=release" in dockerfile_content

    def test_log_level_configured(self, dockerfile_content):
        """Log level should be configured."""
        assert "LOG_LEVEL=" in dockerfile_content

    def test_log_level_not_debug(self, dockerfile_content):
        """Log level should not be debug in production."""
        assert "LOG_LEVEL=debug" not in dockerfile_content.lower()
