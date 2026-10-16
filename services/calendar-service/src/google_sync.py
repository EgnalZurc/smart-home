"""Google Calendar API client for syncing events.

This module wraps the Google Calendar API with OAuth2 authentication, providing
incremental sync via sync tokens to minimize API quota usage and network traffic.

The client handles:
- OAuth2 token loading, refresh, and persistence
- Incremental sync using sync tokens (falls back to full sync on InvalidSyncToken)
- Calendar listing for configuration UI
- Proper error handling for quota exhaustion and auth failures

Design notes (from calendar-service-design.md §2):
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Read-only scope for least-privilege access (design §2.1).
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


class InvalidSyncToken(Exception):
    """Raised when the sync token is stale/invalid and a full sync is required."""


class GoogleAuthError(Exception):
    """Raised when OAuth2 authentication fails (missing/invalid credentials)."""


class GoogleCalendarClient:
    """Client for Google Calendar API with OAuth2 and incremental sync.

    The client manages OAuth2 credentials (refresh token persistence) and
    provides methods to list calendars and sync events incrementally.

    Attributes:
        client_id: OAuth2 client ID from Google Cloud Console.
        client_secret: OAuth2 client secret from Google Cloud Console.
        token_path: Path to the token.json file storing the refresh token.
        credentials: Loaded OAuth2 credentials (after authenticate()).
        service: Google Calendar API service object (after authenticate()).
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_path: str | Path,
        scopes: list[str] | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            client_id: OAuth2 client ID from Google Cloud Console.
            client_secret: OAuth2 client secret from Google Cloud Console.
            token_path: Path to the token.json file for persisting refresh token.
            scopes: OAuth2 scopes to request. Defaults to calendar.readonly.
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_path = Path(token_path)
        self.scopes = scopes or [CALENDAR_SCOPE]
        self._credentials: Credentials | None = None
        self._service: Any = None

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

        Returns:
            True if credentials are valid and the API service is ready.
            False if no valid credentials exist (token_path missing or invalid).
        """
        # Attempt to load existing token
        if self.token_path.exists():
            try:
                token_data = json.loads(self.token_path.read_text())
                self._credentials = Credentials(
                    token=token_data.get("token"),
                    refresh_token=token_data.get("refresh_token"),
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    scopes=self.scopes,
                )
                logger.debug("Loaded credentials from %s", self.token_path)
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
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
                logger.error("Failed to refresh OAuth2 token: %s", exc)
                self._credentials = None
                return False

        # Build the API service
        try:
            self._service = build(
                "calendar",
                "v3",
                credentials=self._credentials,
                cache_discovery=False,
            )
            logger.info("Google Calendar API service initialized")
            return True
        except Exception as exc:
            logger.error("Failed to build Calendar API service: %s", exc)
            self._service = None
            return False

    def _save_token(self) -> None:
        """Persist credentials to token_path atomically (mode 600 for security).

        Only saves token data; client_id/client_secret come from environment.
        Uses atomic write (temp file + os.replace) to prevent corruption.
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
        tmp_path.write_text(json.dumps(token_data, indent=2))
        # Set restrictive permissions before moving to final location
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass  # Windows doesn't support chmod the same way
        os.replace(tmp_path, self.token_path)
        logger.debug("Saved token to %s", self.token_path)

    def list_calendars(self) -> list[dict[str, Any]]:
        """List all calendars accessible by the authenticated account.

        Returns:
            List of calendar dicts with keys: id, summary, description, primary,
            accessRole, timeZone, backgroundColor, foregroundColor.
        """
        calendars: list[dict[str, Any]] = []
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
    ) -> tuple[list[dict[str, Any]], str | None]:
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
        events: list[dict[str, Any]] = []
        page_token: str | None = None
        new_sync_token: str | None = None

        # Build request parameters
        params: dict[str, Any] = {
            "calendarId": calendar_id,
            "singleEvents": True,  # Expand recurring events
            "orderBy": "startTime",
        }

        if sync_token:
            # Incremental sync — timeMin/timeMax are ignored per API docs
            params["syncToken"] = sync_token
        else:
            # Full sync — apply time bounds
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
                # Sync token is stale — caller should retry with full sync
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
    ) -> dict[str, Any]:
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
