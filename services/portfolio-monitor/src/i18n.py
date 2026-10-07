"""
Portfolio Monitor — Internationalisation (es / en).

Loads translations from JSON files in the locales/ directory.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
_SUPPORTED = {"es", "en"}
_DEFAULT = "es"
_LOCALES_DIR = Path(__file__).parent.parent / "locales"

# ─────────────────────────────────────────────────────────────────────────────
# Translation loading
# ─────────────────────────────────────────────────────────────────────────────
_CATALOGUE: dict[str, dict[str, str]] = {}


def _load_translations() -> None:
    """Load translations from JSON files in locales/ directory."""
    global _CATALOGUE

    for lang in _SUPPORTED:
        locale_file = _LOCALES_DIR / f"{lang}.json"
        if locale_file.exists():
            try:
                with locale_file.open("r", encoding="utf-8") as f:
                    translations = json.load(f)
                    for key, value in translations.items():
                        if key not in _CATALOGUE:
                            _CATALOGUE[key] = {}
                        _CATALOGUE[key][lang] = value
                logger.debug("[i18n] Loaded %d keys for '%s'", len(translations), lang)
            except json.JSONDecodeError as e:
                logger.error("[i18n] Failed to parse %s: %s", locale_file, e)
        else:
            logger.warning("[i18n] Locale file not found: %s", locale_file)


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
    """
    lang = _resolve_lang()
    entry = _CATALOGUE.get(key, {})
    text = entry.get(lang) or entry.get(_DEFAULT) or key
    return text.format_map(kwargs) if kwargs else text


def reload_translations() -> None:
    """Reload translations from disk. Useful for testing or hot-reload."""
    global _CATALOGUE
    _CATALOGUE = {}
    _load_translations()
