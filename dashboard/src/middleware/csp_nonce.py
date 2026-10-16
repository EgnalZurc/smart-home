"""CSP nonce generation middleware.

Generates a unique nonce per request for Content-Security-Policy headers,
allowing inline scripts/styles with nonce= attribute while blocking others.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp


def generate_nonce() -> str:
    """Generate a cryptographically secure nonce (22 chars, URL-safe base64)."""
    return secrets.token_urlsafe(16)


def get_csp_nonce(request: Request) -> str:
    """Retrieve the CSP nonce for the current request.

    Use this in Jinja2 templates or route handlers to get the nonce
    for inline script/style tags.

    Args:
        request: The current FastAPI/Starlette request object.

    Returns:
        The nonce string for this request, or empty string if middleware
        is not installed.
    """
    return getattr(request.state, "csp_nonce", "")


class CSPNonceMiddleware(BaseHTTPMiddleware):
    """Middleware that generates a CSP nonce for each request.

    The nonce is:
    1. Generated fresh for every request
    2. Stored in request.state.csp_nonce for use in templates
    3. Added to the Content-Security-Policy response header

    Usage in templates:
        <script nonce="{{ request.state.csp_nonce }}">...</script>

    Usage in route handlers:
        from middleware import get_csp_nonce
        nonce = get_csp_nonce(request)
    """

    def __init__(
        self, app: ASGIApp, csp_directives: dict[str, str] | None = None
    ) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application.
            csp_directives: Optional dict of CSP directives to override defaults.
                Keys are directive names (e.g., 'default-src', 'script-src').
                Values are the directive values (e.g., "'self'", "'none'").
                The {nonce} placeholder will be replaced with the actual nonce.
        """
        super().__init__(app)
        self.csp_directives: dict[str, str] = (
            csp_directives or self._default_directives()
        )

    @staticmethod
    def _default_directives() -> dict[str, str]:
        """Default CSP directives with nonce placeholder.

        All inline scripts use nonce, and all event handlers use addEventListener,
        so 'unsafe-inline' is not needed. The nonce provides secure allowlisting.
        """
        return {
            "default-src": "'self'",
            "script-src": "'self' 'nonce-{nonce}'",
            "style-src": "'self' 'nonce-{nonce}'",
            "img-src": "'self' data: https:",
            "font-src": "'self' data:",
            "connect-src": "'self' wss: https:",
            "frame-ancestors": "'self'",
            "base-uri": "'self'",
            "form-action": "'self'",
        }

    def _build_csp_header(self, nonce: str) -> str:
        """Build the CSP header value with the given nonce."""
        parts: list[str] = []
        for directive, value in self.csp_directives.items():
            # Replace {nonce} placeholder with actual nonce
            resolved_value: str = value.format(nonce=nonce)
            parts.append(f"{directive} {resolved_value}")
        return "; ".join(parts)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Generate nonce, store in request, add CSP header to response."""
        # Generate unique nonce for this request
        nonce: str = generate_nonce()

        # Store in request.state for template/handler access
        request.state.csp_nonce = nonce

        # Process the request
        response: Response = await call_next(request)

        # Add CSP header to response
        csp_header: str = self._build_csp_header(nonce)
        response.headers["Content-Security-Policy"] = csp_header

        return response
