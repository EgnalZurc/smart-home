"""Translation module for API responses and error messages."""

TRANSLATIONS = {
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
    }
}

def get_translation(key: str, locale: str = "en") -> str:
    if locale not in TRANSLATIONS:
        locale = "en"
    return TRANSLATIONS[locale].get(key, key)

def detect_locale(accept_language: str | None) -> str:
    if not accept_language:
        return "en"
    if "es" in accept_language.lower():
        return "es"
    return "en"
