"""Integration tests for dashboard routing and static assets.

Updated post-refactoring:
- AC app (/smart-home/ac) now served by ac-service, NOT by backend main.py
- /api/status now in ac-service, NOT in backend routes.py
- Dashboard uses /api/health/* endpoints for status polling
- Dashboard has two sections: infrastructure (SUPER) + services
- Stop/start buttons only visible to SUPER
"""
import pytest
from pathlib import Path

BACKEND_STATIC = Path("/home/pi/projects/smart-home/src/backend/static")
BACKEND_SRC    = Path("/home/pi/projects/smart-home/src/backend")


# ── Helper ────────────────────────────────────────────────────────────────────

def _html():
    return (BACKEND_STATIC / "dashboard.html").read_text(encoding="utf-8")


def _main():
    return (BACKEND_SRC / "main.py").read_text(encoding="utf-8")


# ── Dashboard file ────────────────────────────────────────────────────────────

class TestDashboardFileExists:

    def test_dashboard_html_exists(self):
        assert (BACKEND_STATIC / "dashboard.html").exists()

    def test_dashboard_title_is_cuchi_casa(self):
        assert "Cuchi Casa" in _html()

    def test_dashboard_has_language_selector(self):
        html = _html()
        assert "lang-menu" in html
        assert "setLang" in html

    def test_dashboard_links_tailwind(self):
        assert "tailwind.css" in _html()

    def test_tailwind_css_exists_and_is_large(self):
        css = BACKEND_STATIC / "tailwind.css"
        assert css.exists()
        assert css.stat().st_size > 10_000

    def test_dashboard_has_user_chip(self):
        assert "user-chip" in _html()
        assert "user-avatar" in _html()


# ── App catalogue and service cards ───────────────────────────────────────────

class TestDashboardAppCatalogue:

    def test_app_catalogue_contains_ac(self):
        html = _html()
        assert "APP_CATALOGUE" in html
        assert "/smart-home/ac" in html

    def test_app_catalogue_contains_vacaciones(self):
        assert "/smart-home/vacaciones" in _html()

    def test_app_catalogue_contains_casita(self):
        assert "/smart-home/casita" in _html()

    def test_app_catalogue_contains_photos(self):
        assert "photos" in _html()

    def test_app_catalogue_contains_passwords(self):
        assert "passwords" in _html()

    def test_zigbee_not_in_app_catalogue(self):
        """zigbee must NOT be in APP_CATALOGUE — it's infrastructure, not a service card."""
        html = _html()
        # zigbee should not be a key in APP_CATALOGUE
        assert "APP_CATALOGUE" in html
        # Check that zigbee only appears in CORE_SERVICES, not APP_CATALOGUE
        app_cat_start = html.index("APP_CATALOGUE")
        app_cat_end = html.index("let APPS", app_cat_start)
        app_catalogue_block = html[app_cat_start:app_cat_end]
        # zigbee key must NOT be in the APP_CATALOGUE object
        assert "zigbee:" not in app_catalogue_block

    def test_apps_filters_zigbee_client_side(self):
        """Dashboard JS must filter out zigbee from service cards."""
        html = _html()
        assert "!== 'zigbee'" in html or "key !== 'zigbee'" in html


# ── Infrastructure bar (SUPER only) ──────────────────────────────────────────

class TestInfrastructureBar:

    def test_core_section_exists(self):
        assert "core-section" in _html()

    def test_core_services_has_three_items(self):
        """CORE_SERVICES must contain exactly Backend, MQTT, Zigbee."""
        html = _html()
        assert "CORE_SERVICES" in html
        assert "core_backend" in html
        assert "core_mqtt" in html
        assert "core_zigbee" in html

    def test_ac_not_in_core_services(self):
        """AC is an external service, NOT in CORE_SERVICES."""
        html = _html()
        core_start = html.index("CORE_SERVICES")
        core_end = html.index("APP_CATALOGUE")
        core_block = html[core_start:core_end]
        assert "core_ac" not in core_block

    def test_vacaciones_not_in_core_services(self):
        """Vacaciones is an external service, NOT in CORE_SERVICES."""
        html = _html()
        core_start = html.index("CORE_SERVICES")
        core_end = html.index("APP_CATALOGUE")
        core_block = html[core_start:core_end]
        assert "core_vacaciones" not in core_block

    def test_core_section_gated_by_show_config_apps(self):
        """Infrastructure bar must only render for SUPER (show_config_apps=true)."""
        html = _html()
        assert "show_config_apps" in html

    def test_zigbee_is_clickable_in_core_bar(self):
        """Zigbee in core bar must link to /zigbee/."""
        html = _html()
        core_start = html.index("CORE_SERVICES")
        core_end = html.index("APP_CATALOGUE")
        core_block = html[core_start:core_end]
        assert "/zigbee/" in core_block

    def test_backend_health_uses_json_endpoint(self):
        """Backend health must use /api/health/backend (JSON), not /health (plain text)."""
        html = _html()
        assert "/api/health/backend" in html
        # Old /health endpoint (nginx plain text) must NOT be the backend status URL
        core_start = html.index("CORE_SERVICES")
        core_end = html.index("APP_CATALOGUE")
        core_block = html[core_start:core_end]
        # core_backend entry should not use bare /health
        backend_entry_start = core_block.index("core_backend")
        backend_entry_end = core_block.index("core_mqtt")
        backend_entry = core_block[backend_entry_start:backend_entry_end]
        assert "'/api/health/backend'" in backend_entry or '"/api/health/backend"' in backend_entry


# ── Health status polling ─────────────────────────────────────────────────────

class TestDashboardHealthPolling:

    def test_dashboard_uses_health_ac(self):
        assert "/api/health/ac" in _html()

    def test_dashboard_uses_health_zigbee(self):
        assert "/api/health/zigbee" in _html()

    def test_dashboard_uses_health_vacaciones(self):
        assert "/api/health/vacaciones" in _html()

    def test_dashboard_uses_health_immich(self):
        assert "/api/health/immich" in _html()

    def test_dashboard_uses_health_casita(self):
        assert "/api/health/casita" in _html()

    def test_dashboard_does_not_call_api_status_directly(self):
        """/api/status is now in ac-service — backend dashboard must not call it."""
        html = _html()
        # /api/status must not appear as a statusUrl in APP_CATALOGUE or CORE_SERVICES
        app_cat_start = html.index("APP_CATALOGUE")
        app_cat_end = html.index("let APPS", app_cat_start)
        assert "statusUrl: '/api/status'" not in html[app_cat_start:app_cat_end]
        assert 'statusUrl: "/api/status"' not in html[app_cat_start:app_cat_end]

    def test_status_cache_avoids_duplicate_fetches(self):
        """statusCache must be used to avoid hitting same URL twice."""
        html = _html()
        assert "statusCache" in html


# ── Stop/start buttons (SUPER only) ──────────────────────────────────────────

class TestStopStartButtons:

    def test_dashboard_has_svc_btn_class(self):
        assert "svc-btn" in _html()

    def test_toggle_service_function_exists(self):
        assert "toggleService" in _html()

    def test_toggle_calls_containers_api(self):
        assert "/api/containers/" in _html()

    def test_button_gated_by_is_super(self):
        """Stop/start button must only render for SUPER."""
        html = _html()
        assert "isSuper()" in html

    def test_button_prevents_navigation(self):
        """Button click must call event.preventDefault() to avoid navigating."""
        html = _html()
        assert "preventDefault()" in html

    def test_load_container_states_function_exists(self):
        assert "loadContainerStates" in html()

    def test_container_state_polling_interval(self):
        """Container states must be refreshed periodically."""
        html = _html()
        assert "loadContainerStates" in html
        assert "setInterval" in html


def html():
    return _html()


# ── main.py routing ───────────────────────────────────────────────────────────

class TestMainPyRouting:

    def test_root_redirects_to_smart_home(self):
        """/ must redirect to /smart-home."""
        assert "RedirectResponse" in _main()
        assert "/smart-home" in _main()
        assert "301" in _main()

    def test_smart_home_dashboard_route_exists(self):
        """/smart-home must be registered in main.py."""
        assert "/smart-home" in _main()
        assert "dashboard.html" in _main()

    def test_ac_route_not_in_main(self):
        """/smart-home/ac is served by ac-service, NOT by backend main.py."""
        main = _main()
        # serve_ac must not exist in backend main.py
        assert "serve_ac" not in main
        assert "index.html" not in main or "ac" not in main

    def test_vacaciones_route_not_in_main(self):
        """/smart-home/vacaciones is served by vacaciones-service, NOT backend."""
        assert "serve_vacaciones" not in _main()

    def test_auth_public_prefixes_includes_api_health(self):
        """_AUTH_PUBLIC_PREFIXES must include /api/health/ for status polling."""
        assert '"/api/health/"' in _main() or "'/api/health/'" in _main()


# ── Static assets ─────────────────────────────────────────────────────────────

class TestStaticAssets:

    def test_favicon_exists(self):
        assert (BACKEND_STATIC / "favicon.ico").exists()

    def test_flags_exist(self):
        assert (BACKEND_STATIC / "flags" / "es.svg").exists()
        assert (BACKEND_STATIC / "flags" / "gb.svg").exists()

    def test_no_regression_translations_es(self):
        """Spanish translations must include service names."""
        html = _html()
        assert "Control AC" in html
        assert "Cuchi Vacaciones" in html
        assert "Casita Sueños" in html

    def test_no_regression_translations_en(self):
        """English translations must include service names."""
        html = _html()
        assert "AC Control" in html
        assert "Cuchi Holidays" in html
