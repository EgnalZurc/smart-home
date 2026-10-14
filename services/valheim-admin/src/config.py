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
# Power Profiles
# ══════════════════════════════════════════════════════════════════════════════

VALID_POWER_MODES = frozenset({"gaming", "servidor", "balanced"})
"""Valid power profile modes for pc-agent."""

# ══════════════════════════════════════════════════════════════════════════════
# Service Metadata
# ══════════════════════════════════════════════════════════════════════════════

SERVICE_NAME = "valheim-admin"
"""Service identifier used in health checks and logging."""

SERVICE_VERSION = "2.1.0"
"""Current service version."""

SERVICE_TITLE = "Valheim Admin"
"""Human-readable service title for API docs."""
