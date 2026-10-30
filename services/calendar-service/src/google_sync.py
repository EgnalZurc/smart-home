"""Google Calendar API client for syncing events.

This module wraps the Google Calendar API with OAuth2 authentication, providing
incremental sync via sync tokens to minimize API quota usage and network traffic.

The client handles:
- OAuth2 token loading, refresh, and persistence
- Incremental sync using sync tokens (falls back to full sync on InvalidSyncToken)
- Calendar listing for configuration UI
- Proper error handling for quota exhaustion and auth failures

Design notes (from calendar-service-design.md Â§2):
- Read-only scope (calendar.readonly) for least-privilege access
- Service stores the OAuth refresh token at TOKEN_PATH (secret, mode 600)
- Credentials come from env vars (GOOGLE_OAUTH_CLIENT_ID/SECRET), not a file

Usage::

    client = GoogleCalendarClient(
        client_id="...",
        client_secret="...",
        token_path="/app/data/token.json",
    )
    if await client.authenticate():
        calendars = await client.list_calendars()
        events, new_token = await client.sync_events("primary", sync_token=None)
"""

from __future__ import annotations

import json
import logging
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from config import CALENDAR_TOKEN_SECRET, HTTP_TIMEOUT_S
from cryptography.fernet import Fernet, InvalidToken
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from httplib2 import Http, HttpLib2Error

__all__ = [
    "GoogleCalendarClient",
    "GoogleAuthError",
    "InvalidSyncToken",
    "CalendarInfo",
    "AttendeeInfo",
    "NormalizedEvent",
    "MIN_OAUTH_TOKEN_LENGTH",
]

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
MIN_OAUTH_TOKEN_LENGTH = 20


def _redact_secret(value: str | None) -> str:
    """Redact a secret value for safe logging.

    Returns:
        Redacted string showing only last 4 chars, or "(empty)" if blank.
    """
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "****"
    return f"****{value[-4:]}"


class TimeoutHttp(Http):
    """Http wrapper that enforces connection and read timeouts.

    The Google API client uses httplib2 by default which has no timeout,
    allowing sync operations to hang indefinitely on network issues.
    This wrapper sets socket-level timeouts for each request, restoring
    the previous timeout after completion to avoid affecting other code.
    """

    def __init__(self, timeout: float = HTTP_TIMEOUT_S, **kwargs):
        """Initialize with specified timeout.

        Args:
            timeout: Timeout in seconds for connect and read operations.
            **kwargs: Additional arguments passed to httplib2.Http.
        """
        super().__init__(**kwargs)
        self._timeout = timeout

    def request(self, *args, **kwargs):
        """Make HTTP request with enforced timeout, restoring previous value after."""
        old_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(self._timeout)
            return super().request(*args, **kwargs)
        finally:
            socket.setdefaulttimeout(old_timeout)


class CalendarInfo(TypedDict):
    """Calendar metadata from Google Calendar API."""

    id: str | None
    summary: str
    description: str | None
    primary: bool
    access_role: str | None
    time_zone: str | None
    background_color: str | None
    foreground_color: str | None


class AttendeeInfo(TypedDict):
    """Attendee information from an event."""

    email: str | None
    display_name: str | None
    response_status: str | None
    self: bool


class NormalizedEvent(TypedDict):
    """Normalized event structure returned by sync_events."""

    event_id: str | None
    calendar_id: str
    summary: str
    description: str | None
    location: str | None
    start: str | None
    end: str | None
    start_timezone: str | None
    end_timezone: str | None
    is_all_day: bool
    status: str | None
    deleted: bool
    html_link: str | None
    organizer: str | None
    created: str | None
    updated: str | None
    recurrence_id: str | None
    attendees: list[AttendeeInfo]


# Read-only scope for least-privilege access (design Â§2.1).
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


class InvalidSyncToken(Exception):
    """Raised when the sync token is stale/invalid and a full sync is required."""


class GoogleAuthError(Exception):
    """Raised when OAuth2 authentication fails (missing/invalid credentials)."""


def _get_fernet() -> Fernet | None:
    """Return Fernet instance if CALENDAR_TOKEN_SECRET is configured."""
    if not CALENDAR_TOKEN_SECRET:
        return None
    try:
        return Fernet(CALENDAR_TOKEN_SECRET.encode())
    except (ValueError, TypeError) as exc:
        logger.warning("Invalid CALENDAR_TOKEN_SECRET: %s", exc)
        return None


def _encrypt_token_data(data: dict) -> str:
    """Encrypt token data to base64 string, or return JSON if no secret."""
    fernet = _get_fernet()
    json_str = json.dumps(data)
    if fernet is None:
        return json_str
    return fernet.encrypt(json_str.encode()).decode()


def _decrypt_token_data(data: str) -> dict | None:
    """Decrypt token data, supporting both encrypted and legacy plaintext.

    Returns:
        Decrypted token dict, or None if decryption fails.
    """
    # Try JSON first (legacy plaintext or no encryption configured)
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        pass

    # Try Fernet decryption
    fernet = _get_fernet()
    if fernet is None:
        logger.warning("Encrypted token found but CALENDAR_TOKEN_SECRET not configured")
        return None
    try:
        decrypted = fernet.decrypt(data.encode()).decode()
        return json.loads(decrypted)
    except (InvalidToken, json.JSONDecodeError) as exc:
        logger.warning("Failed to decrypt token: %s", exc)
        return None


class GoogleCalendarClient:
    """Client for Google Calendar API with OAuth2 and incremental sync.

    The client manages OAuth2 credentials (refresh token persistence) and
    provides methods to list calendars and sync events incrementally.

    Attributes:
        client_id: OAuth2 client ID from Google Cloud Console.
        token_path: Path to the token.json file storing the refresh token.
        credentials: Loaded OAuth2 credentials (after authenticate()).
        service: Google Calendar API service object (after authenticate()).

    Note:
        client_secret is stored internally but NEVER logged or exposed in
        error messages to prevent credential leakage.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_path: str | Path,
        scopes: list[str] | None = None,
        timeout: float = HTTP_TIMEOUT_S,
    ) -> None:
        """Initialize the client.

        Args:
            client_id: OAuth2 client ID from Google Cloud Console.
            client_secret: OAuth2 client secret from Google Cloud Console.
            token_path: Path to the token.json file for persisting refresh token.
            scopes: OAuth2 scopes to request. Defaults to calendar.readonly.
            timeout: HTTP timeout in seconds for API calls.
        """
        self.client_id = client_id
        # Store secret in private attribute to discourage accidental logging
        self._client_secret = client_secret
        self.token_path = Path(token_path)
        self.scopes = scopes or [CALENDAR_SCOPE]
        self._timeout = timeout
        self._credentials: Credentials | None = None
        self._service: Any = None

    def __repr__(self) -> str:
        """Return safe representation without exposing secrets."""
        return (
            f"GoogleCalendarClient(client_id={self.client_id!r}, "
            f"token_path={self.token_path!r})"
        )

    @property
    def credentials(self) -> Credentials | None:
        """Return the current OAuth2 credentials, if loaded."""
        return self._credentials

    @property
    def service(self) -> Any:
        """Return the Calendar API service, raising if not authenticated."""
        if self._service is None:
            raise GoogleAuthError("Not authenticated. Call authenticate() first.")
        return self._service

    @property
    def is_authenticated(self) -> bool:
        """Return True if credentials are loaded and valid (or refreshable)."""
        return self._credentials is not None and (
            self._credentials.valid or self._credentials.refresh_token is not None
        )

    def authenticate(self) -> bool:
        """Load credentials from token_path and refresh if expired.

        This method does NOT initiate the OAuth2 consent flow (that requires
        user interaction in a browser). It only loads and refreshes existing
        tokens. The initial token must be obtained externally (setup script or
        admin API) and written to token_path.

        Supports both encrypted tokens (when CALENDAR_TOKEN_SECRET is set) and
        legacy plaintext tokens for migration.

        Returns:
            True if credentials are valid and the API service is ready.
            False if no valid credentials exist (token_path missing or invalid).
        """
        # Attempt to load existing token
        if self.token_path.exists():
            try:
                raw_data = self.token_path.read_text()
                token_data = _decrypt_token_data(raw_data)

                if token_data is None:
                    logger.warning(
                        "Failed to decrypt/parse token at %s",
                        self.token_path,
                    )
                    self._credentials = None
                    return False

                # Validate token data structure and format
                refresh_token = token_data.get("refresh_token")
                access_token = token_data.get("token")

                # Refresh token is required and must be non-empty string
                if not refresh_token or not isinstance(refresh_token, str):
                    logger.warning(
                        "Invalid token file at %s: missing or malformed refresh_token",
                        self.token_path,
                    )
                    self._credentials = None
                    return False

                # Access token is optional but if present must be string
                if access_token is not None and not isinstance(access_token, str):
                    logger.warning(
                        "Invalid token file at %s: malformed access token",
                        self.token_path,
                    )
                    self._credentials = None
                    return False

                # Tokens should look like OAuth tokens (min length, no whitespace)
                if len(refresh_token) < MIN_OAUTH_TOKEN_LENGTH or " " in refresh_token:
                    logger.warning(
                        "Invalid token file at %s: refresh_token format invalid",
                        self.token_path,
                    )
                    self._credentials = None
                    return False

                self._credentials = Credentials(
                    token=access_token,
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=self.client_id,
                    client_secret=self._client_secret,
                    scopes=self.scopes,
                )
                logger.debug("Loaded credentials from %s", self.token_path)
            except (KeyError, TypeError) as exc:
                logger.warning("Failed to load token from %s: %s", self.token_path, exc)
                self._credentials = None

        if self._credentials is None:
            logger.warning(
                "No valid token at %s. Run the setup flow to obtain credentials.",
                self.token_path,
            )
            return False

        # Refresh expired credentials
        if self._credentials.expired and self._credentials.refresh_token:
            try:
                self._credentials.refresh(Request())
                self._save_token()
                logger.info("Refreshed expired OAuth2 token")
            except RefreshError as exc:
                # Sanitize error to avoid leaking secrets
                error_msg = str(exc)
                if self._client_secret and self._client_secret in error_msg:
                    error_msg = error_msg.replace(
                        self._client_secret, _redact_secret(self._client_secret)
                    )
                logger.error("Failed to refresh OAuth2 token: %s", error_msg)
                self._credentials = None
                return False

        # Build the API service with timeout-enabled HTTP transport
        try:
            http = TimeoutHttp(timeout=self._timeout)
            self._service = build(
                "calendar",
                "v3",
                credentials=self._credentials,
                cache_discovery=False,
                http=http,
            )
            logger.info(
                "Google Calendar API service initialized (timeout=%.1fs)",
                self._timeout,
            )
            return True
        except (HttpLib2Error, TransportError, OSError, ValueError) as exc:
            # Network/transport errors during service build, or API validation errors
            # Sanitize error to avoid leaking secrets
            error_msg = str(exc)
            if self._client_secret and self._client_secret in error_msg:
                error_msg = error_msg.replace(
                    self._client_secret, _redact_secret(self._client_secret)
                )
            logger.error("Failed to build Calendar API service: %s", error_msg)
            self._service = None
            return False

    def _save_token(self) -> None:
        """Persist credentials to token_path atomically (mode 600 for security).

        Only saves token data; client_id/client_secret come from environment.
        Uses atomic write (temp file + os.replace) to prevent corruption.
        Encrypts token data if CALENDAR_TOKEN_SECRET is configured.
        """
        if self._credentials is None:
            return
        token_data = {
            "token": self._credentials.token,
            "refresh_token": self._credentials.refresh_token,
            "token_uri": self._credentials.token_uri,
            "scopes": list(self._credentials.scopes or []),
        }
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.token_path.with_suffix(".json.tmp")
        encrypted_data = _encrypt_token_data(token_data)
        tmp_path.write_text(encrypted_data)
        # Set restrictive permissions before moving to final location
        try:
            os.chmod(tmp_path, 0o600)
        except OSError as exc:
            # M5: Log warning when chmod fails (Windows doesn't support Unix-style chmod).
            logger.warning(
                "Could not set restrictive permissions on token file (expected on Windows): %s",
                exc,
            )
        os.replace(tmp_path, self.token_path)
        logger.debug(
            "Saved token to %s (encrypted=%s)", self.token_path, bool(_get_fernet())
        )

    def list_calendars(self) -> list[CalendarInfo]:
        """List all calendars accessible by the authenticated account.

        Returns:
            List of calendar dicts with keys: id, summary, description, primary,
            accessRole, timeZone, backgroundColor, foregroundColor.
        """
        calendars: list[CalendarInfo] = []
        page_token: str | None = None

        while True:
            response = (
                self.service.calendarList()
                .list(pageToken=page_token, showHidden=False)
                .execute()
            )
            for item in response.get("items", []):
                calendars.append(
                    {
                        "id": item.get("id"),
                        "summary": item.get("summary", "(no name)"),
                        "description": item.get("description"),
                        "primary": item.get("primary", False),
                        "access_role": item.get("accessRole"),
                        "time_zone": item.get("timeZone"),
                        "background_color": item.get("backgroundColor"),
                        "foreground_color": item.get("foregroundColor"),
                    }
                )
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info("Listed %d calendars", len(calendars))
        return calendars

    def sync_events(
        self,
        calendar_id: str,
        sync_token: str | None = None,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
    ) -> tuple[list[NormalizedEvent], str | None]:
        """Sync events from a calendar, using incremental sync when possible.

        When a sync_token is provided, the API returns only events that changed
        since that token was issued. If the token is stale (410 Gone), raises
        InvalidSyncToken so the caller can retry with sync_token=None for a
        full sync.

        Args:
            calendar_id: Calendar ID (e.g., "primary" or email address).
            sync_token: Token from a previous sync (enables incremental sync).
            time_min: Only return events starting after this time (full sync only).
            time_max: Only return events starting before this time (full sync only).

        Returns:
            Tuple of (events, new_sync_token):
            - events: List of event dicts with normalized fields.
            - new_sync_token: Token for the next incremental sync.

        Raises:
            InvalidSyncToken: If the sync_token is stale and a full sync is needed.
            HttpError: For other API errors (quota, auth, network).
        """
        events: list[NormalizedEvent] = []
        page_token: str | None = None
        new_sync_token: str | None = None

        # Build request parameters
        params: dict[str, Any] = {
            "calendarId": calendar_id,
            "singleEvents": True,  # Expand recurring events
            "orderBy": "startTime",
        }

        if sync_token:
            # Incremental sync â€” timeMin/timeMax are ignored per API docs
            params["syncToken"] = sync_token
        else:
            # Full sync â€” apply time bounds
            if time_min:
                params["timeMin"] = time_min.astimezone(timezone.utc).isoformat()
            if time_max:
                params["timeMax"] = time_max.astimezone(timezone.utc).isoformat()

        try:
            while True:
                if page_token:
                    params["pageToken"] = page_token

                response = self.service.events().list(**params).execute()

                for item in response.get("items", []):
                    events.append(self._normalize_event(item, calendar_id))

                page_token = response.get("nextPageToken")
                if not page_token:
                    new_sync_token = response.get("nextSyncToken")
                    break

        except HttpError as exc:
            if exc.resp.status == 410:
                # Sync token is stale â€” caller should retry with full sync
                logger.warning(
                    "Sync token for calendar %s is stale (410 Gone)", calendar_id
                )
                raise InvalidSyncToken(
                    f"Sync token for {calendar_id} is invalid; full sync required"
                ) from exc
            # Re-raise other HTTP errors (quota, auth, etc.)
            raise

        logger.info(
            "Synced %d events from %s (incremental=%s)",
            len(events),
            calendar_id,
            sync_token is not None,
        )
        return events, new_sync_token

    def _normalize_event(
        self, item: dict[str, Any], calendar_id: str
    ) -> NormalizedEvent:
        """Convert a raw API event to our internal format.

        Handles both timed events (dateTime) and all-day events (date).
        Deleted events (status=cancelled) are marked with deleted=True so the
        sync loop can remove them from the local store.
        """
        # Start/end can be date (all-day) or dateTime (timed)
        start = item.get("start", {})
        end = item.get("end", {})

        start_dt = start.get("dateTime") or start.get("date")
        end_dt = end.get("dateTime") or end.get("date")
        is_all_day = "date" in start and "dateTime" not in start

        return {
            "event_id": item.get("id"),
            "calendar_id": calendar_id,
            "summary": item.get("summary", "(no title)"),
            "description": item.get("description"),
            "location": item.get("location"),
            "start": start_dt,
            "end": end_dt,
            "start_timezone": start.get("timeZone"),
            "end_timezone": end.get("timeZone"),
            "is_all_day": is_all_day,
            "status": item.get("status"),  # confirmed, tentative, cancelled
            "deleted": item.get("status") == "cancelled",
            "html_link": item.get("htmlLink"),
            "organizer": item.get("organizer", {}).get("email"),
            "created": item.get("created"),
            "updated": item.get("updated"),
            "recurrence_id": item.get("recurringEventId"),
            "attendees": [
                {
                    "email": a.get("email"),
                    "display_name": a.get("displayName"),
                    "response_status": a.get("responseStatus"),
                    "self": a.get("self", False),
                }
                for a in item.get("attendees", [])
            ],
        }
