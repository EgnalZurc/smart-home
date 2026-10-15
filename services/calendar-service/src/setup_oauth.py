#!/usr/bin/env python3
"""
OAuth2 setup script for Google Calendar API.

This script runs ONCE manually to generate token.json for the calendar-service.
It opens a browser for the user to authorize access, then saves the credentials.

Usage:
    python setup_oauth.py --credentials /path/to/client_secret.json --token-output /path/to/token.json

Requirements:
    - client_secret.json from Google Cloud Console (OAuth 2.0 Client ID, type "Desktop app")
    - Browser access on the machine running the script
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Read-only access to calendar events
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def run_oauth_flow(
    credentials_path: Path,
    token_output_path: Path,
    port: int = 8080,
) -> Credentials:
    """
    Run the OAuth2 installed-app flow and save the token.

    Args:
        credentials_path: Path to client_secret.json
        token_output_path: Path where token.json will be saved
        port: Local port for the OAuth callback server

    Returns:
        The authorized Credentials object
    """
    print(f"\n{'=' * 60}")
    print("Google Calendar OAuth2 Setup")
    print(f"{'=' * 60}\n")

    if not credentials_path.exists():
        print(f"ERROR: Credentials file not found: {credentials_path}")
        print("\nTo get client_secret.json:")
        print("  1. Go to https://console.cloud.google.com/apis/credentials")
        print("  2. Create OAuth 2.0 Client ID (type: Desktop app)")
        print("  3. Download the JSON and save as client_secret.json")
        sys.exit(1)

    print(f"Using credentials: {credentials_path}")
    print(f"Token will be saved to: {token_output_path}")
    print(f"OAuth callback port: {port}")
    print("\nOpening browser for authorization...")
    print("(If browser doesn't open, copy the URL from terminal)\n")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_path),
        scopes=SCOPES,
    )

    # run_local_server opens browser and waits for callback
    creds = flow.run_local_server(
        port=port,
        prompt="consent",  # Always show consent screen for clarity
        success_message="Authorization successful! You can close this tab.",
    )

    # Save the token
    token_output_path.parent.mkdir(parents=True, exist_ok=True)
    token_output_path.write_text(creds.to_json())

    print(f"\n✓ Token saved to: {token_output_path}")

    return creds


def list_calendars(creds: Credentials) -> None:
    """List available calendars to confirm authorization worked."""
    print(f"\n{'=' * 60}")
    print("Available Calendars")
    print(f"{'=' * 60}\n")

    try:
        service = build("calendar", "v3", credentials=creds)
        calendars_result = service.calendarList().list().execute()
        calendars = calendars_result.get("items", [])

        if not calendars:
            print("No calendars found.")
            return

        for cal in calendars:
            primary = " (primary)" if cal.get("primary") else ""
            access = cal.get("accessRole", "unknown")
            print(f"  • {cal['summary']}{primary}")
            print(f"    ID: {cal['id']}")
            print(f"    Access: {access}\n")

        print(f"Total: {len(calendars)} calendar(s)")

    except HttpError as e:
        print(f"ERROR listing calendars: {e}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Set up OAuth2 credentials for Google Calendar API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python setup_oauth.py
  python setup_oauth.py --credentials ./client_secret.json --token-output ./token.json
  python setup_oauth.py --port 9090

After running this script, copy token.json to the calendar-service data directory.
        """,
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path("client_secret.json"),
        help="Path to client_secret.json (default: ./client_secret.json)",
    )
    parser.add_argument(
        "--token-output",
        type=Path,
        default=Path("token.json"),
        help="Path where token.json will be saved (default: ./token.json)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Local port for OAuth callback (default: 8080)",
    )

    args = parser.parse_args()

    creds = run_oauth_flow(
        credentials_path=args.credentials,
        token_output_path=args.token_output,
        port=args.port,
    )

    list_calendars(creds)

    print(f"\n{'=' * 60}")
    print("Setup Complete!")
    print(f"{'=' * 60}")
    print(f"\nNext steps:")
    print(f"  1. Copy {args.token_output} to the calendar-service data directory")
    print(f"  2. Set GOOGLE_TOKEN_PATH in your .env or settings.toml")
    print(f"  3. Restart the calendar-service container")
    print()


if __name__ == "__main__":
    main()
