"""Configuration constants for Valheim Admin service.

This module centralizes all hardcoded values, magic numbers, and default
settings used throughout the valheim-admin service. Values can be overridden
via environment variables where noted.

Architecture:
    valheim-admin runs on the Raspberry Pi and proxies requests to pc-agent
    running on the Windows PC. This config covers the Pi-side proxy settings,
    not the actual Valheim server configuration (which lives on the PC).

Environment Variables:
    PC_AGENT_URL: Base URL for pc-agent (default: http://192.168.1.164:8090)
    PC_AGENT_TOKEN: Authentication token for pc-agent (required)
    PC_AGENT_TIMEOUT: HTTP timeout in seconds (default: 30.0)

Security:
    PC_AGENT_URL is validated to only allow connections to internal/private
    IP addresses to prevent SSRF attacks. Localhost and loopback addresses
    are blocked to prevent redirect-based attacks.
"""

import ipaddress
import os
from urllib.parse import urlparse

# ══════════════════════════════════════════════════════════════════════════════
# PC-Agent Connection Settings
# ══════════════════════════════════════════════════════════════════════════════

PC_AGENT_DEFAULT_URL = "http://192.168.1.164:8090"
"""Default URL for pc-agent on the Windows PC (EgnalPC)."""

PC_AGENT_DEFAULT_TIMEOUT = 30.0
"""Default HTTP timeout in seconds for pc-agent requests."""


# ══════════════════════════════════════════════════════════════════════════════
# SSRF Protection
# ══════════════════════════════════════════════════════════════════════════════

# Allowed private IP ranges for PC_AGENT_URL (RFC 1918 + Tailscale)
ALLOWED_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),  # Class A private
    ipaddress.ip_network("172.16.0.0/12"),  # Class B private
    ipaddress.ip_network("192.168.0.0/16"),  # Class C private
    ipaddress.ip_network("100.64.0.0/10"),  # Tailscale CGNAT range
]

# Blocked IP patterns (localhost/loopback) - SSRF targets
BLOCKED_IP_PATTERNS = [
    ipaddress.ip_network("127.0.0.0/8"),  # IPv4 loopback
    ipaddress.ip_address("0.0.0.0"),  # All interfaces
]

# Blocked hostnames (case-insensitive)
BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
}


def validate_pc_agent_url(url: str) -> str:
    """Validate that PC_AGENT_URL points to an allowed internal IP.

    This function prevents SSRF attacks by ensuring the URL:
    1. Has a valid scheme (http or https)
    2. Points to a private IP address (RFC 1918 or Tailscale range)
    3. Does NOT point to localhost/loopback addresses

    Args:
        url: The URL to validate.

    Returns:
        The validated URL (unchanged if valid).

    Raises:
        ValueError: If the URL is invalid or points to a disallowed address.
    """
    if not url:
        raise ValueError("PC_AGENT_URL cannot be empty")

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValueError(f"Invalid URL format: {e}") from e

    # Validate scheme
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"PC_AGENT_URL scheme must be http or https, got: {parsed.scheme}"
        )

    # Get hostname
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("PC_AGENT_URL must have a hostname")

    # Block known dangerous hostnames
    if hostname.lower() in BLOCKED_HOSTNAMES:
        raise ValueError(
            f"PC_AGENT_URL cannot use localhost/loopback hostname: {hostname}"
        )

    # Try to parse as IP address
    try:
        ip = ipaddress.ip_address(hostname)

        # Block loopback addresses
        for blocked in BLOCKED_IP_PATTERNS:
            if isinstance(blocked, ipaddress.IPv4Network):
                if ip in blocked:
                    raise ValueError(
                        f"PC_AGENT_URL cannot use loopback address: {hostname}"
                    )
            elif ip == blocked:
                raise ValueError(f"PC_AGENT_URL cannot use address: {hostname}")

        # Verify it's in an allowed private range
        is_private = any(ip in net for net in ALLOWED_PRIVATE_RANGES)
        if not is_private:
            raise ValueError(
                f"PC_AGENT_URL must point to a private IP address. "
                f"Got: {hostname}. Allowed ranges: 10.0.0.0/8, 172.16.0.0/12, "
                f"192.168.0.0/16, 100.64.0.0/10 (Tailscale)"
            )

    except ValueError as e:
        if "does not appear to be an IPv4 or IPv6 address" in str(e):
            # It's a hostname, not an IP - this could be a DNS rebinding attack
            # For safety, only allow IP addresses in PC_AGENT_URL
            raise ValueError(
                f"PC_AGENT_URL must use an IP address, not a hostname: {hostname}. "
                "This prevents DNS rebinding attacks."
            ) from e
        raise

    return url


# Load and validate PC_AGENT_URL
_raw_pc_agent_url = os.environ.get("PC_AGENT_URL", PC_AGENT_DEFAULT_URL)
try:
    PC_AGENT_URL: str = validate_pc_agent_url(_raw_pc_agent_url)
except ValueError as e:
    # Log error and use a safe default that will fail at runtime
    import logging

    logging.error("Invalid PC_AGENT_URL configuration: %s", e)
    # Re-raise to prevent service startup with invalid config
    raise RuntimeError(f"Invalid PC_AGENT_URL: {e}") from e

PC_AGENT_TOKEN: str = os.environ.get("PC_AGENT_TOKEN", "")
"""Authentication token for pc-agent. Required at runtime."""

PC_AGENT_TIMEOUT: float = float(
    os.environ.get("PC_AGENT_TIMEOUT", str(PC_AGENT_DEFAULT_TIMEOUT))
)
"""Configured HTTP timeout for pc-agent requests."""

# ══════════════════════════════════════════════════════════════════════════════
# Rate Limiting
# ══════════════════════════════════════════════════════════════════════════════

RATE_LIMIT_MAX_REQUESTS = 10
"""Maximum requests allowed per IP within the rate limit window."""

RATE_LIMIT_WINDOW_SECONDS = 60
"""Time window in seconds for rate limiting."""

# ══════════════════════════════════════════════════════════════════════════════
# Input Validation Limits
# ══════════════════════════════════════════════════════════════════════════════

WORLD_NAME_MAX_LENGTH = 64
"""Maximum length for world names."""

WORLD_NAME_PATTERN = r"^[A-Za-z0-9_-]+$"
"""Regex pattern for valid world names (alphanumeric, underscore, hyphen)."""

SERVER_NAME_MAX_LENGTH = 64
"""Maximum length for server names displayed in browser."""

SERVER_NAME_PATTERN = r"^[A-Za-z0-9 ]{1,64}$"
"""Regex pattern for valid server names (alphanumeric and spaces)."""

SERVER_PASS_MAX_LENGTH = 128
"""Maximum length for server passwords."""

# ══════════════════════════════════════════════════════════════════════════════
# Server Configuration Bounds
# ══════════════════════════════════════════════════════════════════════════════

SAVE_INTERVAL_MIN_SECONDS = 300
"""Minimum save interval: 5 minutes."""

SAVE_INTERVAL_MAX_SECONDS = 86400
"""Maximum save interval: 24 hours."""

SAVE_INTERVAL_DEFAULT_SECONDS = 1800
"""Default save interval: 30 minutes."""

BACKUPS_MIN = 1
"""Minimum number of backup copies to keep."""

BACKUPS_MAX = 100
"""Maximum number of backup copies to keep."""

BACKUPS_DEFAULT = 4
"""Default number of backup copies."""

# ══════════════════════════════════════════════════════════════════════════════
# Logs API
# ══════════════════════════════════════════════════════════════════════════════

LOGS_DEFAULT_LINES = 80
"""Default number of log lines to retrieve."""

LOGS_MIN_LINES = 1
"""Minimum number of log lines that can be requested."""

LOGS_MAX_LINES = 10000
"""Maximum number of log lines that can be requested."""

# ══════════════════════════════════════════════════════════════════════════════
# Service Metadata
# ══════════════════════════════════════════════════════════════════════════════

SERVICE_NAME = "valheim-admin"
"""Service identifier used in health checks and logging."""

SERVICE_VERSION = "2.1.0"
"""Current service version."""

SERVICE_TITLE = "Valheim Admin"
"""Human-readable service title for API docs."""
