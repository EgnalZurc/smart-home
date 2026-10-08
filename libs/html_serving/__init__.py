"""Shared HTML-serving library for Smart Home services.

Provides :func:`serve_html`, a single implementation of the static-SPA
serving helper that was previously duplicated across services.
"""

from .serve import NO_CACHE_HEADERS, serve_html

__all__ = ["serve_html", "NO_CACHE_HEADERS"]
