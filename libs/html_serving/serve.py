"""Shared HTML-serving helper for Smart Home FastAPI services.

Every service that serves a static SPA page used to carry a near-identical
``_serve_html()`` helper: read a file from the service's ``static/`` directory,
inject a cache-buster comment before ``</head>``, and return an
:class:`~fastapi.responses.HTMLResponse` with aggressive no-cache headers.

This module centralises that logic. Two optional extensions seen across the
services are supported here so a single implementation covers all callers:

* ``not_found_html`` — return a 404 ``HTMLResponse`` when the file is missing
  (portfolio-monitor's behaviour) instead of raising ``FileNotFoundError``.
* ``guest_token`` / ``auth_user`` — inject values into the page's
  ``window.GUEST_TOKEN`` / ``window.AUTH_USER`` placeholders
  (baby-gifts-service's behaviour).

Callers pass their own ``static_dir`` (typically
``Path(__file__).parent / "static"``) so the helper stays stateless.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.responses import HTMLResponse

# Headers that defeat every layer of caching (browser + proxies). Shared so the
# behaviour is identical across services.
NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def serve_html(
    static_dir: Path,
    filename: str,
    *,
    guest_token: str | None = None,
    auth_user: dict | None = None,
    not_found_html: str | None = None,
) -> HTMLResponse:
    """Serve a static HTML file with no-cache headers and optional injection.

    Args:
        static_dir: Directory holding the static files (e.g.
            ``Path(__file__).parent / "static"``).
        filename: Name of the HTML file to serve, relative to ``static_dir``.
        guest_token: If given, replaces ``window.GUEST_TOKEN = null;`` in the
            page with the JSON-encoded token (guest view).
        auth_user: If given, replaces ``window.AUTH_USER = null;`` in the page
            with the JSON-encoded user dict (authenticated view).
        not_found_html: If given and the file does not exist, return this HTML
            with status 404 instead of raising ``FileNotFoundError``.

    Returns:
        An :class:`~fastapi.responses.HTMLResponse` with no-cache headers (or a
        404 response when the file is missing and ``not_found_html`` is set).
    """
    path = static_dir / filename

    if not_found_html is not None and not path.exists():
        return HTMLResponse(content=not_found_html, status_code=404)

    content = path.read_text(encoding="utf-8")

    # Cache buster: a changing comment forces revalidation of the HTML shell.
    content = content.replace("</head>", f"<!-- v:{int(time.time())} -->\n</head>")

    if guest_token:
        content = content.replace(
            "window.GUEST_TOKEN = null;",
            f"window.GUEST_TOKEN = {json.dumps(guest_token)};",
        )

    if auth_user:
        content = content.replace(
            "window.AUTH_USER = null;",
            f"window.AUTH_USER = {json.dumps(auth_user)};",
        )

    return HTMLResponse(content=content, headers=dict(NO_CACHE_HEADERS))
