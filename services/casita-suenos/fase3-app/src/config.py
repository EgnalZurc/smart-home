"""
Configuration module for casita-suenos scrapers.

Centralizes portal base URLs and scraping parameters to avoid hardcoded
values scattered across scraper modules. Change URLs here when portals
update their domain or URL structure.

Example:
    from config import BASE_URLS, SCRAPER_CONFIG

    url = BASE_URLS["habitaclia"] + "/comprar/viviendas/..."
    delay = SCRAPER_CONFIG["request_delay"]
"""

from __future__ import annotations

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
