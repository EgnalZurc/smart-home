"""Unit tests for translations.py - i18n support."""

from translations import TRANSLATIONS, detect_locale, get_translation


class TestGetTranslation:
    def test_returns_english_by_default(self):
        result = get_translation("error.invalid_mode")
        assert result == "Invalid mode. Must be one of: auto, manual, off"

    def test_returns_spanish_when_requested(self):
        result = get_translation("error.invalid_mode", "es")
        assert result == "Modo inválido. Debe ser: auto, manual, off"

    def test_falls_back_to_english_for_unknown_locale(self):
        result = get_translation("error.invalid_mode", "fr")
        assert result == "Invalid mode. Must be one of: auto, manual, off"

    def test_returns_key_when_not_found(self):
        result = get_translation("nonexistent.key", "en")
        assert result == "nonexistent.key"

    def test_all_english_keys_exist(self):
        for key in TRANSLATIONS["en"]:
            result = get_translation(key, "en")
            assert result != key

    def test_all_spanish_keys_exist(self):
        for key in TRANSLATIONS["es"]:
            result = get_translation(key, "es")
            assert result != key

    def test_both_locales_have_same_keys(self):
        en_keys = set(TRANSLATIONS["en"].keys())
        es_keys = set(TRANSLATIONS["es"].keys())
        assert en_keys == es_keys


class TestDetectLocale:
    def test_returns_english_for_none(self):
        assert detect_locale(None) == "en"

    def test_returns_english_for_empty_string(self):
        assert detect_locale("") == "en"

    def test_returns_spanish_when_es_present(self):
        assert detect_locale("es") == "es"
        assert detect_locale("es-ES") == "es"
        assert detect_locale("ES") == "es"

    def test_returns_spanish_for_accept_language_header(self):
        assert detect_locale("es-ES,es;q=0.9,en;q=0.8") == "es"

    def test_returns_english_for_english_header(self):
        assert detect_locale("en-US,en;q=0.9") == "en"

    def test_returns_english_for_unknown_locale(self):
        assert detect_locale("fr-FR") == "en"
        assert detect_locale("de-DE") == "en"
