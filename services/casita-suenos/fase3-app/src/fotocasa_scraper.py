"""
Scraper for fotocasa.es — DISABLED (August 2026).

This module is a placeholder for the Fotocasa portal scraper. The scraper
is currently disabled because Fotocasa is a Single Page Application (SPA)
built with React/Next.js that loads all listing data via JavaScript.

Technical Details:
    - The server returns only the app shell HTML without listing data
    - No __NEXT_DATA__ or embedded JSON with listings is present
    - Search URLs (/es/comprar/casas/*/todas-las-zonas/l) return 404
    - The only working URL (/casas-rurales/) doesn't include data in static HTML

Requirements to Re-enable:
    - Playwright + stealth mode on a server with browser (not on Pi)
    - Or ScrapFly account with paid plan (asp=True, country="ES")
    - Or Spanish residential proxy + curl_cffi

Decision: Disabled until adequate infrastructure is available.

Example:
    >>> from fotocasa_scraper import scrape_zone
    >>> from zones import Zone
    >>> zone = Zone(id="test", name="Test Zone")
    >>> results = scrape_zone(zone)  # Returns empty list
    []
"""

from __future__ import annotations

import logging

import httpx
from config import BASE_URLS
from models import Property
from zones import Zone

logger = logging.getLogger(__name__)

# Base URL for Fotocasa (unused while disabled, kept for future reference)
_BASE_URL = BASE_URLS["fotocasa"]


def scrape_zone(zone: Zone, client: httpx.Client | None = None) -> list[Property]:
    """
    Scrape Fotocasa listings for a zone — DISABLED.

    This function is a no-op placeholder. Fotocasa requires JavaScript
    execution to render listings, which is not available in the current
    scraping infrastructure.

    Args:
        zone: Zone configuration object with search parameters.
        client: Optional httpx.Client instance (unused).

    Returns:
        Empty list. Always returns [] while disabled.

    Note:
        When re-enabling, implement using Playwright or a JS-capable
        scraping service. See module docstring for requirements.
    """
    logger.debug(
        "[fotocasa] Disabled for zone %s — SPA portal, data not available in "
        "static HTML. Requires Playwright or residential proxy to function.",
        zone.id,
    )
    return []
