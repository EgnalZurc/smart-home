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
"""

import os
import re
from urllib.parse import urlparse

# ══════════════════════════════════════════════════════════════════════════════
# SSRF Mitigation - Internal URL Validation
# ══════════════════════════════════════════════════════════════════════════════

_INTERNAL_PATTERNS = [
    re.compile(r"^localhost$", re.IGNORECASE),
    re.compile(r"^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
    re.compile(r"^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
    re.compile(r"^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$"),
    re.compile(r"^192\.168\.\d{1,3}\.\d{1,3}$"),
]
"""Regex patterns matching internal/private network addresses."""


def is_internal_url(url: str) -> bool:
    """Check if a URL points to an internal network address.

    Validates that the hostname in the URL matches one of:
    - localhost
    - 127.x.x.x (loopback)
    - 10.x.x.x (Class A private)
    - 172.16-31.x.x (Class B private)
    - 192.168.x.x (Class C private)

    This prevents SSRF attacks by ensuring PC_AGENT_URL cannot be
    configured to point to external services.

    Args:
        url: The URL to validate.

    Returns:
        True if the URL hostname is an internal address, False otherwise.

    Example:
        >>> is_internal_url("http://192.168.1.164:8090")
        True
        >>> is_internal_url("http://evil.com:8090")
        False
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    return any(p.match(hostname) for p in _INTERNAL_PATTERNS)


# ══════════════════════════════════════════════════════════════════════════════
# PC-Agent Connection Settings
# ══════════════════════════════════════════════════════════════════════════════

PC_AGENT_DEFAULT_URL = "http://192.168.1.164:8090"
"""Default URL for pc-agent on the Windows PC (EgnalPC)."""

PC_AGENT_DEFAULT_TIMEOUT = 30.0
"""Default HTTP timeout in seconds for pc-agent requests."""

# Load from environment with defaults
PC_AGENT_URL: str = os.environ.get("PC_AGENT_URL", PC_AGENT_DEFAULT_URL)
"""Configured pc-agent URL (from env or default)."""

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

RATE_LIMIT_MAX_ENTRIES = 10000
"""Maximum number of entries to track in the rate limiter's internal storage.

This limits memory usage by capping how many distinct IP addresses are tracked.
When the limit is reached, oldest entries are evicted (LRU behavior in the
InMemoryRateLimiter implementation).
"""

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
# Upload Limits
# ══════════════════════════════════════════════════════════════════════════════

UPLOAD_MAX_SIZE_BYTES = 600 * 1024 * 1024
"""Maximum upload size: 600 MB.

Valheim world files can be quite large, especially for mature worlds with
extensive exploration and building. The 600 MB limit accommodates:
- Valheim 1.0 world folders (zipped): typically 10-50 MB, up to 200 MB for
  very large worlds with extensive terrain modifications.
- Legacy format (.db + .fwl files): similar sizes.

The limit is enforced both client-side (in JavaScript) and server-side to
prevent abuse and protect against memory exhaustion during upload processing.
"""

# ══════════════════════════════════════════════════════════════════════════════
# Service Metadata
# ══════════════════════════════════════════════════════════════════════════════

SERVICE_NAME = "valheim-admin"
"""Service identifier used in health checks and logging."""

SERVICE_VERSION = "2.1.0"
"""Current service version."""

SERVICE_TITLE = "Valheim Admin"
"""Human-readable service title for API docs."""
