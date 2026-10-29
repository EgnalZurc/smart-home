"""
Portfolio Monitor — Internationalisation (es / en).

Loads translations from JSON files in the locales/ directory.

Thread-safety: The _CATALOGUE dict is protected by a lock for concurrent access
during reload operations. Single-threaded usage (typical in this service) works
without contention, but the lock ensures correctness if translations are reloaded
while requests are being served.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger: logging.Logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
_SUPPORTED: set[str] = {"es", "en"}
_DEFAULT: str = "es"
# Try multiple locations: Docker (/app/locales) and development (../locales)
_LOCALES_DIR_CANDIDATES: list[Path] = [
    Path(__file__).parent / "locales",  # Docker: /app/locales
    Path(__file__).parent.parent / "locales",  # Dev: services/portfolio-monitor/locales
]
_LOCALES_DIR: Path = next(
    (p for p in _LOCALES_DIR_CANDIDATES if p.exists()), _LOCALES_DIR_CANDIDATES[0]
)

# ─────────────────────────────────────────────────────────────────────────────
# Translation loading
# ─────────────────────────────────────────────────────────────────────────────
_CATALOGUE: dict[str, dict[str, str]] = {}
_CATALOGUE_LOCK: threading.Lock = threading.Lock()


def _load_translations() -> None:
    """Load translations from JSON files in locales/ directory."""
    global _CATALOGUE

    new_catalogue: dict[str, dict[str, str]] = {}

    for lang in _SUPPORTED:
        locale_file = _LOCALES_DIR / f"{lang}.json"
        if locale_file.exists():
            try:
                with locale_file.open("r", encoding="utf-8") as f:
                    translations: dict[str, str] = json.load(f)
                    for key, value in translations.items():
                        if key not in new_catalogue:
                            new_catalogue[key] = {}
                        new_catalogue[key][lang] = value
                logger.debug("[i18n] Loaded %d keys for '%s'", len(translations), lang)
            except json.JSONDecodeError as e:
                logger.error("[i18n] Failed to parse %s: %s", locale_file, e)
        else:
            logger.warning("[i18n] Locale file not found: %s", locale_file)

    with _CATALOGUE_LOCK:
        _CATALOGUE = new_catalogue


# Load translations on module import
_load_translations()


# ─────────────────────────────────────────────────────────────────────────────
# Language resolution
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_lang() -> str:
    """Resolve active language: env var > default."""
    lang = os.environ.get("MONITOR_LANG", _DEFAULT).lower()
    return lang if lang in _SUPPORTED else _DEFAULT


def t(key: str, **kwargs: Any) -> str:
    """
    Return the translated string for *key* in the active language.
    Keyword arguments are interpolated via str.format_map.
    Falls back to the key itself if not found.

    Thread-safe: acquires lock to read from _CATALOGUE.
    """
    lang = _resolve_lang()
    with _CATALOGUE_LOCK:
        entry = _CATALOGUE.get(key, {})
        text = entry.get(lang) or entry.get(_DEFAULT) or key
    return text.format_map(kwargs) if kwargs else text


def reload_translations() -> None:
    """Reload translations from disk. Useful for testing or hot-reload.

    Thread-safe: _load_translations handles locking internally.
    """
    _load_translations()
