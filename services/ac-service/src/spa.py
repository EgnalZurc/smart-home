"""Static SPA serving helpers.

The AC control UI is a single-page app served from ``src/static``. Browsers
aggressively cache HTML, so after a deploy the user can keep seeing the old
shell. ``serve_html`` injects a timestamp comment and sends no-store cache
headers to force the browser to re-fetch on every load.

Extracted from ``main.py`` to keep the FastAPI module focused on routing.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.responses import HTMLResponse

STATIC_DIR = Path(__file__).parent / "static"


def serve_html(filename: str, static_dir: Path = STATIC_DIR) -> HTMLResponse:
    """Return a no-cache ``HTMLResponse`` for a file under ``static_dir``.

    Args:
        filename: File name inside ``static_dir`` (e.g. ``"index.html"``).
        static_dir: Directory holding the static assets. Defaults to the
            service's ``static`` folder.

    Returns:
        An ``HTMLResponse`` with a cache-busting comment appended before
        ``</head>`` and no-store cache headers.
    """
    path = static_dir / filename
    content = path.read_text(encoding="utf-8")
    content = content.replace("</head>", f"<!-- v:{int(time.time())} -->\n</head>")
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
