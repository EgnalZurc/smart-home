"""Translation module for API responses and error messages."""

from __future__ import annotations

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "error.invalid_mode": "Invalid mode. Must be one of: auto, manual, off",
        "error.invalid_temperature": "Invalid temperature value",
        "error.invalid_param": "Invalid parameter",
        "success.mode_changed": "Control mode changed successfully",
        "success.params_updated": "Parameters updated successfully",
    },
    "es": {
        "error.invalid_mode": "Modo inválido. Debe ser: auto, manual, off",
        "error.invalid_temperature": "Valor de temperatura inválido",
        "error.invalid_param": "Parámetro inválido",
        "success.mode_changed": "Modo de control cambiado exitosamente",
        "success.params_updated": "Parámetros actualizados exitosamente",
    },
}


def get_translation(key: str, locale: str = "en") -> str:
    """Get a translation for the given key and locale.

    Args:
        key: The translation key to look up.
        locale: The locale code (defaults to 'en').

    Returns:
        The translated string, or the key itself if not found.
    """
    if locale not in TRANSLATIONS:
        locale = "en"
    return TRANSLATIONS[locale].get(key, key)


def detect_locale(accept_language: str | None) -> str:
    """Detect the preferred locale from Accept-Language header.

    Args:
        accept_language: The Accept-Language header value.

    Returns:
        The detected locale code ('en' or 'es').
    """
    if not accept_language:
        return "en"
    if "es" in accept_language.lower():
        return "es"
    return "en"
