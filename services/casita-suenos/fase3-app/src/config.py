"""
Configuration module for casita-suenos scrapers.

Centralizes portal base URLs and scraping parameters to avoid hardcoded
values scattered across scraper modules. Change URLs here when portals
update their domain or URL structure.

Also provides credential sanitization utilities to prevent secrets from
leaking into log messages or error responses.

Example:
    from config import BASE_URLS, SCRAPER_CONFIG, sanitize_credential_error

    url = BASE_URLS["habitaclia"] + "/comprar/viviendas/..."
    delay = SCRAPER_CONFIG["request_delay"]
    safe_msg = sanitize_credential_error(str(exception), ["my_secret"])
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Portal Base URLs
# ---------------------------------------------------------------------------
# Central registry of portal domains. Update here if a portal changes domain.

BASE_URLS: dict[str, str] = {
    "habitaclia": "https://www.habitaclia.com",
    "pisos": "https://www.pisos.com",
    "fotocasa": "https://www.fotocasa.es",
    "idealista": "https://www.idealista.com",
}

# ---------------------------------------------------------------------------
# Scraper Configuration
# ---------------------------------------------------------------------------
# Tunable parameters for scraping behavior.

SCRAPER_CONFIG: dict[str, int | float] = {
    # Delay between HTTP requests (seconds) to avoid rate limiting
    "request_delay": 2.5,
    # Maximum pages to scrape per search URL
    "max_pages": 3,
    # HTTP timeout for requests (seconds)
    "http_timeout": 15,
}

# ---------------------------------------------------------------------------
# HTTP Headers
# ---------------------------------------------------------------------------
# Default headers to mimic a real browser and reduce blocking.

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ---------------------------------------------------------------------------
# Credential Sanitization
# ---------------------------------------------------------------------------
# Functions to strip sensitive values from error messages before logging.
# Prevents tokens, passwords, and API keys from leaking into logs or responses.

# Telegram bot tokens look like: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
_TELEGRAM_TOKEN_PATTERN = re.compile(r"\b[0-9]+:[A-Za-z0-9_-]{20,}\b")
_TELEGRAM_URL_PATTERN = re.compile(r"/bot[0-9]+:[A-Za-z0-9_-]+/")


def sanitize_telegram_error(msg: str) -> str:
    """Strip Telegram bot token from error messages to prevent leaks in logs.

    Args:
        msg: The error message to sanitize.

    Returns:
        A sanitized string with any bot token replaced by <REDACTED>.

    Example:
        >>> sanitize_telegram_error("Error: /bot123456:ABCdef/sendMessage failed")
        'Error: /bot<REDACTED>/sendMessage failed'
    """
    sanitized = _TELEGRAM_URL_PATTERN.sub("/bot<REDACTED>/", msg)
    sanitized = _TELEGRAM_TOKEN_PATTERN.sub("<REDACTED>", sanitized)
    return sanitized


def sanitize_imap_error(msg: str, app_password: str | None = None) -> str:
    """Strip sensitive data from IMAP error messages to prevent leaks in logs.

    IMAP authentication errors may include the password in the exception message.
    This function removes any occurrence of the password and common patterns
    that could reveal credentials.

    Args:
        msg: The error message to sanitize.
        app_password: The Gmail App Password to redact. If provided, all
            occurrences will be replaced with <REDACTED>.

    Returns:
        A sanitized string with sensitive values removed.

    Example:
        >>> sanitize_imap_error("LOGIN failed with 'mypassword123'", "mypassword123")
        "LOGIN failed with '<REDACTED>'"
    """
    sanitized = msg

    # Remove explicit password if provided
    if app_password and len(app_password) >= 4:
        # Escape for regex in case password has special chars
        escaped = re.escape(app_password)
        sanitized = re.sub(escaped, "<REDACTED>", sanitized, flags=re.IGNORECASE)

    # Common IMAP auth error patterns that might reveal credentials
    # Pattern: b'password123' or 'password123' in error strings
    sanitized = re.sub(
        r"b?['\"][\w!@#$%^&*()_+=\-]{8,}['\"]",
        "'<REDACTED>'",
        sanitized,
    )

    return sanitized


def sanitize_credential_error(
    msg: str,
    credentials: list[str] | None = None,
) -> str:
    """Generic credential sanitization for any error message.

    Use this when logging errors from code that handles multiple types of
    credentials (API keys, tokens, passwords).

    Args:
        msg: The error message to sanitize.
        credentials: List of credential values to redact. Each will be
            replaced with <REDACTED> if found in the message.

    Returns:
        A sanitized string with all credential values removed.

    Example:
        >>> sanitize_credential_error("API call failed: key=abc123", ["abc123"])
        'API call failed: key=<REDACTED>'
    """
    sanitized = msg

    if credentials:
        for cred in credentials:
            if cred and len(cred) >= 4:
                escaped = re.escape(cred)
                sanitized = re.sub(
                    escaped, "<REDACTED>", sanitized, flags=re.IGNORECASE
                )

    return sanitized
