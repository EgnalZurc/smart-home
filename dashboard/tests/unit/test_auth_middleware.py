"""Unit tests for AuthMiddleware (defined in main.py).

AuthMiddleware is the central authentication gate added to the FastAPI app.
Its decision tree (see the class docstring in main.py) is:

    1. Public path prefix          -> pass through
    2. /static/* assets            -> pass through
    3. Valid JWT session cookie    -> pass through
    4. Expired/missing JWT but a valid device (Jaspan) cookie:
         - theft detected          -> clear cookies, 302 to /api/auth/login?alert=theft
         - ok                      -> issue fresh JWT (+ rotate device cookie), pass through
    5. No session and no device    -> 302 to /api/auth/login?next=<path>

main.py requires AUTH_SECRET at import time, so we set it before importing.
These tests build a *minimal* FastAPI app with only AuthMiddleware mounted and
patch the collaborator functions (auth_core / auth_devices) on the main module,
so no real JWT/DB machinery is exercised — the middleware logic is tested in
isolation.

Note on 401 vs 302: the task spec mentions "missing/invalid token returns 401",
but the real implementation *redirects* unauthenticated browser requests to the
login page with HTTP 302. The tests assert the actual (302-redirect) behaviour.
"""

import os
from unittest.mock import MagicMock

import pytest

# AuthMiddleware's host module validates AUTH_SECRET at import time.
os.environ.setdefault("AUTH_SECRET", "test-secret-key-32-chars-minimum")

import main  # noqa: E402  (import after env is set)
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import PlainTextResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# ── Test app factory ──────────────────────────────────────────────────────────


def _make_client() -> TestClient:
    """Minimal app with only AuthMiddleware and a couple of routes.

    `follow_redirects=False` lets us inspect the 302 redirects the middleware
    emits instead of transparently following them.
    """
    app = FastAPI()
    app.add_middleware(main.AuthMiddleware)

    @app.get("/smart-home")
    async def protected():
        return PlainTextResponse("protected-ok")

    @app.get("/health")
    async def health():
        return PlainTextResponse("health-ok")

    @app.get("/static/app.css")
    async def static_asset():
        return PlainTextResponse("css-ok")

    return TestClient(app, follow_redirects=False)


@pytest.fixture
def client():
    return _make_client()


@pytest.fixture(autouse=True)
def _reset_auth(monkeypatch):
    """Default: no valid JWT, no device cookie. Each test overrides as needed."""
    monkeypatch.setattr(main.auth_core, "get_current_user", lambda request: None)
    monkeypatch.setattr(
        main.auth_devices, "get_device_cookie_from_request", lambda request: None
    )


# ── 1. Public path prefixes bypass auth ────────────────────────────────────────


class TestPublicPaths:
    @pytest.mark.parametrize(
        "path",
        [
            "/health",
            "/api/health",
            "/api/health/ac-service",
            "/auth/login",
            "/api/auth/login",
            "/api/proxy/flood",
            "/static/manifest.json",
            "/favicon.ico",
            "/swagger",
            "/redoc",
            "/openapi.json",
        ],
    )
    def test_public_prefixes_are_defined(self, path):
        """Every tested path must match one of the configured public prefixes."""
        assert any(path.startswith(p) for p in main._AUTH_PUBLIC_PREFIXES)

    def test_health_endpoint_bypasses_auth(self, client):
        # No JWT, no device cookie -> would normally redirect, but /health is public.
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.text == "health-ok"

    def test_health_not_redirected_even_when_unauthenticated(self, client):
        resp = client.get("/health")
        assert resp.status_code != 302


# ── 2. Static assets bypass auth ───────────────────────────────────────────────


class TestStaticAssets:
    def test_static_asset_bypasses_auth(self, client):
        resp = client.get("/static/app.css")
        assert resp.status_code == 200
        assert resp.text == "css-ok"


# ── 3. Valid JWT session passes through ────────────────────────────────────────


class TestValidSession:
    def test_valid_jwt_passes_through(self, client, monkeypatch):
        monkeypatch.setattr(main.auth_core, "get_current_user", lambda request: "alice")
        resp = client.get("/smart-home")
        assert resp.status_code == 200
        assert resp.text == "protected-ok"

    def test_valid_jwt_does_not_touch_device_cookie(self, client, monkeypatch):
        """A valid JWT short-circuits before the device-token branch is reached."""
        monkeypatch.setattr(main.auth_core, "get_current_user", lambda request: "alice")
        device_probe = MagicMock(return_value=None)
        monkeypatch.setattr(
            main.auth_devices, "get_device_cookie_from_request", device_probe
        )
        resp = client.get("/smart-home")
        assert resp.status_code == 200
        device_probe.assert_not_called()


# ── 5. No session and no device cookie -> redirect to login ────────────────────


class TestUnauthenticatedRedirect:
    def test_redirects_to_login_when_no_session(self, client):
        resp = client.get("/smart-home")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/api/auth/login?next=/smart-home"

    def test_redirect_preserves_next_path(self, client):
        resp = client.get("/smart-home")
        assert "next=/smart-home" in resp.headers["location"]

    def test_no_device_cookie_skips_rotation(self, client, monkeypatch):
        """With no device cookie, verify_and_rotate must never be called."""
        rotate = MagicMock()
        monkeypatch.setattr(main.auth_devices, "verify_and_rotate", rotate)
        resp = client.get("/smart-home")
        assert resp.status_code == 302
        rotate.assert_not_called()


# ── 4. Expired JWT + device cookie → silent refresh ────────────────────────────


class TestDeviceTokenRefresh:
    def _device_cookie(self, monkeypatch, value="series:token"):
        monkeypatch.setattr(
            main.auth_devices,
            "get_device_cookie_from_request",
            lambda request: value,
        )

    def test_valid_device_token_refreshes_session(self, client, monkeypatch):
        self._device_cookie(monkeypatch)
        result = main.auth_devices.VerifyResult(
            ok=True, username="bob", new_cookie_value="series:newtoken"
        )
        monkeypatch.setattr(
            main.auth_devices, "verify_and_rotate", lambda cookie: result
        )
        monkeypatch.setattr(
            main.auth_core, "create_token", lambda user: "fresh.jwt.token"
        )

        resp = client.get("/smart-home")

        # Request passed through to the protected route.
        assert resp.status_code == 200
        assert resp.text == "protected-ok"
        # A fresh session cookie was issued.
        set_cookie = resp.headers.get("set-cookie", "")
        assert "smh_session=fresh.jwt.token" in set_cookie
        # And the rotated device cookie was set.
        assert "smh_device=series:newtoken" in set_cookie

    def test_grace_window_issues_jwt_without_rotating_device_cookie(
        self, client, monkeypatch
    ):
        """new_cookie_value == '' (grace window): refresh JWT, keep device cookie."""
        self._device_cookie(monkeypatch)
        result = main.auth_devices.VerifyResult(
            ok=True, username="bob", new_cookie_value=""
        )
        monkeypatch.setattr(
            main.auth_devices, "verify_and_rotate", lambda cookie: result
        )
        monkeypatch.setattr(
            main.auth_core, "create_token", lambda user: "fresh.jwt.token"
        )

        resp = client.get("/smart-home")

        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert "smh_session=fresh.jwt.token" in set_cookie
        # Device cookie must NOT be re-set during the grace window.
        assert "smh_device=" not in set_cookie

    def test_theft_detected_clears_cookies_and_redirects(self, client, monkeypatch):
        self._device_cookie(monkeypatch)
        result = main.auth_devices.VerifyResult(
            ok=False, username="bob", theft_detected=True
        )
        monkeypatch.setattr(
            main.auth_devices, "verify_and_rotate", lambda cookie: result
        )

        resp = client.get("/smart-home")

        assert resp.status_code == 302
        assert resp.headers["location"] == "/api/auth/login?alert=theft"
        # Both cookies must be deleted (expiry in the past / Max-Age=0).
        set_cookie = resp.headers.get("set-cookie", "")
        assert main.auth_core.COOKIE_NAME in set_cookie
        assert main.auth_devices.DEVICE_COOKIE_NAME in set_cookie

    def test_invalid_device_token_redirects_to_login(self, client, monkeypatch):
        """Device cookie present but verify fails (not theft) -> normal login redirect."""
        self._device_cookie(monkeypatch)
        result = main.auth_devices.VerifyResult(ok=False)
        monkeypatch.setattr(
            main.auth_devices, "verify_and_rotate", lambda cookie: result
        )

        resp = client.get("/smart-home")

        assert resp.status_code == 302
        assert resp.headers["location"] == "/api/auth/login?next=/smart-home"
        # No fresh session cookie issued.
        assert "smh_session=" not in resp.headers.get("set-cookie", "")


# ── Edge cases ─────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_root_path_is_not_public(self, client):
        """'/' is not in the public prefixes -> unauthenticated request redirects."""
        resp = client.get("/")
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("/api/auth/login?next=/")

    def test_prefix_match_is_startswith_not_equality(self, client):
        """/api/health/<anything> is public because matching uses startswith."""
        # /api/health is a public prefix; a longer path under it stays public.
        assert any(
            "/api/health/ac-service".startswith(p) for p in main._AUTH_PUBLIC_PREFIXES
        )

    def test_non_public_lookalike_still_requires_auth(self, client):
        """A path that only *contains* a public token mid-string is NOT public."""
        # e.g. '/smart-home/health-widget' does not START with a public prefix.
        resp = client.get("/smart-home/health-widget")
        assert resp.status_code == 302
        assert "next=/smart-home/health-widget" in resp.headers["location"]
