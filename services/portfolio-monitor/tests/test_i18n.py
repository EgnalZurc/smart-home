"""
Test internationalisation (i18n) module.

Ensures all required translation keys exist and translations work correctly.
"""


class TestTranslationFunction:
    """Tests for the t() translation function."""

    def test_basic_translation(self):
        """Basic translation lookup should work."""
        from i18n import t

        # Should return something for known keys
        result = t("general.loading")
        assert result is not None
        assert len(result) > 0

    def test_unknown_key_returns_key(self):
        """Unknown keys should return the key itself."""
        from i18n import t

        result = t("nonexistent.key.here")
        assert result == "nonexistent.key.here"

    def test_interpolation(self):
        """String interpolation should work."""
        from i18n import t

        result = t("etf.phase1", months=12)
        assert "12" in result

    def test_both_languages_have_entries(self):
        """Both ES and EN should have translations for critical keys."""
        from i18n import _CATALOGUE

        critical_keys = [
            "general.loading",
            "alert.ok",
            "alert.warn",
            "alert.danger",
            "etf.title",
            "crypto.title",
        ]

        for key in critical_keys:
            assert key in _CATALOGUE, f"Missing key: {key}"
            assert "es" in _CATALOGUE[key], f"Missing ES translation for {key}"
            assert "en" in _CATALOGUE[key], f"Missing EN translation for {key}"


class TestSignalTranslations:
    """Tests for signal-related translations."""

    def test_ath_signals_are_not_prescriptive(self):
        """ATH signals should be informational, not prescriptive."""
        from i18n import _CATALOGUE

        ath_keys = ["crypto.ath_danger", "crypto.ath_warn"]
        prescriptive_words_es = ["considera", "vender", "planificar salida"]
        prescriptive_words_en = ["consider", "sell", "planning", "exit"]

        for key in ath_keys:
            if key in _CATALOGUE:
                es_text = _CATALOGUE[key].get("es", "").lower()
                en_text = _CATALOGUE[key].get("en", "").lower()

                for word in prescriptive_words_es:
                    assert word not in es_text, (
                        f"ATH signal '{key}' contains prescriptive word '{word}'"
                    )

                for word in prescriptive_words_en:
                    assert word not in en_text, (
                        f"ATH signal '{key}' contains prescriptive word '{word}'"
                    )

    def test_pump_signal_is_not_negative(self):
        """Pump signal should not predict corrections."""
        from i18n import _CATALOGUE

        key = "crypto.pump_warn"
        if key in _CATALOGUE:
            es_text = _CATALOGUE[key].get("es", "").lower()
            en_text = _CATALOGUE[key].get("en", "").lower()

            # Should not contain negative predictions
            negative_words = ["corrección", "correction", "cuidado", "caution"]
            for word in negative_words:
                assert word not in es_text, (
                    f"Pump signal contains negative word '{word}'"
                )
                assert word not in en_text, (
                    f"Pump signal contains negative word '{word}'"
                )

    def test_recommendation_signals_are_informational(self):
        """Recommendation signals should inform, not prescribe."""
        from i18n import _CATALOGUE

        rec_keys = ["rec.danger.title", "rec.warn.title", "rec.ok.title"]

        for key in rec_keys:
            if key in _CATALOGUE:
                es_text = _CATALOGUE[key].get("es", "").lower()

                # Should not contain urgent action language
                urgent_words = ["urgente", "inmediato", "ahora"]
                for word in urgent_words:
                    if "danger" in key:
                        # Danger can have "urgente" but title shouldn't prescribe action
                        continue
                    assert word not in es_text, (
                        f"Rec signal '{key}' is too prescriptive"
                    )


class TestAlertLevelTranslations:
    """Tests for alert level translations."""

    def test_all_alert_levels_have_translations(self):
        """All alert levels should have translations."""
        from i18n import _CATALOGUE

        alert_keys = ["alert.ok", "alert.info", "alert.warn", "alert.danger"]

        for key in alert_keys:
            assert key in _CATALOGUE, f"Missing alert translation: {key}"
            assert _CATALOGUE[key].get("es"), f"Missing ES for {key}"
            assert _CATALOGUE[key].get("en"), f"Missing EN for {key}"
