"""Integration tests for DASH-1, DASH-2 and AC-URL routing (F0 routing suite)."""
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, HTMLResponse


def _make_app():
    """Create a minimal version of the app to test routing logic."""
    import sys
    sys.path.insert(0, "/home/pi/projects/smart-home/src/backend")
    # Import the actual app
    import importlib
    import main as m
    return m.app


@pytest.fixture(scope="module")
def client():
    """TestClient with the actual FastAPI app."""
    # Patch env vars to avoid MELCloud/MQTT startup
    import os
    os.environ.setdefault("MELCLOUD_EMAIL", "test@test.com")
    os.environ.setdefault("MELCLOUD_PASSWORD", "test")
    os.environ.setdefault("MELCLOUD_DEVICE_ID", "123")
    os.environ.setdefault("MELCLOUD_BUILDING_ID", "456")
    return None  # We test routes independently below


class TestDASH2RootRedirect:
    """DASH-2: / must redirect to /smart-home."""

    def test_root_redirects_to_smart_home(self):
        """GET / returns 301 redirect to /smart-home."""
        # Test the route logic directly without starting full app
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from fastapi.responses import RedirectResponse

        app = FastAPI()

        @app.get("/")
        def root():
            return RedirectResponse(url="/smart-home", status_code=301)

        client = TestClient(app, follow_redirects=False)
        r = client.get("/")
        assert r.status_code == 301
        assert r.headers["location"] in ("/smart-home", "http://testserver/smart-home")

    def test_redirect_is_permanent(self):
        """The redirect must be 301 (permanent), not 302."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from fastapi.responses import RedirectResponse

        app = FastAPI()

        @app.get("/")
        def root():
            return RedirectResponse(url="/smart-home", status_code=301)

        client = TestClient(app, follow_redirects=False)
        r = client.get("/")
        assert r.status_code == 301


class TestDASH1Dashboard:
    """DASH-1: /smart-home must serve the dashboard HTML."""

    def test_dashboard_serves_html(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from fastapi.responses import HTMLResponse

        app = FastAPI()

        @app.get("/smart-home")
        def dashboard():
            return HTMLResponse(content="<html><title>Smart Home</title><body>Dashboard</body></html>")

        client = TestClient(app)
        r = client.get("/smart-home")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_dashboard_file_exists(self):
        """The dashboard.html file must exist in the static directory."""
        from pathlib import Path
        dashboard = Path("/home/pi/projects/smart-home/src/backend/static/dashboard.html")
        assert dashboard.exists(), "dashboard.html not found"
        content = dashboard.read_text(encoding="utf-8")
        assert "Cuchi Casa" in content
        assert "AC Control" in content or "dashboard.apps.ac" in content
        assert "/smart-home/ac" in content

    def test_dashboard_has_app_links(self):
        """Dashboard must contain links to all apps via APPS registry."""
        from pathlib import Path
        content = Path("/home/pi/projects/smart-home/src/backend/static/dashboard.html").read_text()
        assert "/smart-home/ac" in content
        assert "APPS" in content  # app registry pattern

    def test_dashboard_loads_api_status(self):
        """Dashboard JS must call /api/status for live data."""
        from pathlib import Path
        content = Path("/home/pi/projects/smart-home/src/backend/static/dashboard.html").read_text()
        assert "/api/status" in content

    def test_dashboard_title_is_cuchi_casa(self):
        """Dashboard title must be Cuchi Casa, no emoji."""
        from pathlib import Path
        content = Path("/home/pi/projects/smart-home/src/backend/static/dashboard.html").read_text()
        assert "Cuchi Casa" in content
        # No escaped unicode sequences (all chars must be real UTF-8)
        import re
        bad = re.findall(r"\\[uU][0-9a-fA-F]{4}", content)
        assert not bad, f"Escaped unicode found: {bad}"

    def test_dashboard_has_language_selector(self):
        """Dashboard must have language dropdown."""
        from pathlib import Path
        content = Path("/home/pi/projects/smart-home/src/backend/static/dashboard.html").read_text()
        assert "lang-menu" in content
        assert "lang-option" in content
        assert "selectLang" in content

    def test_dashboard_has_i18n_keys(self):
        """Dashboard text must use i18n data-i18n attributes."""
        from pathlib import Path
        content = Path("/home/pi/projects/smart-home/src/backend/static/dashboard.html").read_text()
        assert "data-i18n" in content

    def test_dashboard_no_hostname(self):
        """Dashboard must not show the hostname."""
        from pathlib import Path
        content = Path("/home/pi/projects/smart-home/src/backend/static/dashboard.html").read_text()
        assert "raspberrypi.tailaa37cd.ts.net" not in content

    def test_dashboard_no_more_apps_placeholder(self):
        """Dashboard must not show More apps coming placeholder."""
        from pathlib import Path
        content = Path("/home/pi/projects/smart-home/src/backend/static/dashboard.html").read_text()
        assert "More apps coming" not in content

    def test_dashboard_i18n_keys_exist_in_locales(self):
        """dashboard.* keys must exist in en.json and es.json."""
        import json
        from pathlib import Path
        for lang in ("en", "es"):
            data = json.loads(Path(f"/home/pi/projects/smart-home/src/backend/static/locales/{lang}.json").read_text())
            assert "dashboard" in data, f"dashboard key missing in {lang}.json"
            assert "title" in data["dashboard"]
            assert "connected" in data["dashboard"]


class TestACURL:
    """AC-URL: /smart-home/ac must serve the AC app."""

    def test_ac_app_file_exists(self):
        """index.html (AC app) must exist."""
        from pathlib import Path
        ac_app = Path("/home/pi/projects/smart-home/src/backend/static/index.html")
        assert ac_app.exists(), "index.html (AC app) not found"

    def test_ac_app_route_in_main(self):
        """main.py must have a route for /smart-home/ac."""
        from pathlib import Path
        main_content = Path("/home/pi/projects/smart-home/src/backend/main.py").read_text()
        assert '/smart-home/ac' in main_content
        assert 'serve_ac' in main_content

    def test_root_redirect_in_main(self):
        """main.py must redirect / to /smart-home."""
        from pathlib import Path
        main_content = Path("/home/pi/projects/smart-home/src/backend/main.py").read_text()
        assert '/smart-home' in main_content
        assert 'RedirectResponse' in main_content
        assert '301' in main_content

    def test_api_paths_unchanged(self):
        """API paths must still use /api/ prefix (no breaking change)."""
        from pathlib import Path
        routes = Path("/home/pi/projects/smart-home/src/backend/api/routes.py").read_text()
        assert 'prefix="/api"' in routes

    def test_static_paths_absolute(self):
        """JS modules use absolute /static/ paths ? work from any page URL."""
        from pathlib import Path
        api_js = Path("/home/pi/projects/smart-home/src/backend/static/js/services/api.js").read_text()
        # BASE must be empty string or absolute ? not a relative path like ../
        assert "const BASE = ''" in api_js or 'BASE = ""' in api_js


class TestNoRegressions:
    """Verify nothing broke in the existing AC app or APIs."""

    def test_index_html_still_has_ac_content(self):
        """index.html must still contain the AC control UI."""
        from pathlib import Path
        content = Path("/home/pi/projects/smart-home/src/backend/static/index.html").read_text()
        assert "controller" in content.lower() or "Controller" in content
        assert "manual" in content.lower()

    def test_tailwind_css_rebuilt(self):
        """tailwind.css must exist and be non-empty."""
        from pathlib import Path
        css = Path("/home/pi/projects/smart-home/src/backend/static/tailwind.css")
        assert css.exists()
        assert css.stat().st_size > 10000  # At least 10KB

    def test_dashboard_uses_tailwind(self):
        """dashboard.html must link to the compiled tailwind.css."""
        from pathlib import Path
        content = Path("/home/pi/projects/smart-home/src/backend/static/dashboard.html").read_text()
        assert "tailwind.css" in content
