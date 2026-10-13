"""Unit tests for POST /api/deploy/{service}.

Covers:
  - SUPER profile can trigger a deploy (200 + payload)
  - FAMILIA/non-super gets 403
  - Unauthenticated gets 401
  - Every valid CI service name is accepted
  - Unknown service returns 400 and never shells out
  - gh failure surfaces as 502
  - The gh invocation is fully mocked — no real subprocess runs
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# Mock passlib before any auth import (mirrors sibling test modules).
_mock_passlib = MagicMock()
_mock_passlib.hash.apr_md5_crypt.verify.return_value = True
sys.modules.setdefault("passlib", _mock_passlib)
sys.modules.setdefault("passlib.hash", _mock_passlib.hash)

from api import deploy  # noqa: E402  (import after passlib is stubbed)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_client():
    """TestClient mounting only the deploy router (no auth middleware)."""
    app = FastAPI()
    app.include_router(deploy.router)
    return TestClient(app, raise_server_exceptions=True)


def _patch_super(username="egnal"):
    """Patch require_super (as imported into api.deploy) to allow as SUPER."""
    return patch("api.deploy.require_super", side_effect=lambda request: username)


def _patch_forbidden():
    """Patch require_super to reject as non-SUPER (403)."""

    def _raise(request):
        raise HTTPException(status_code=403, detail="Admin access required (level 0)")

    return patch("api.deploy.require_super", side_effect=_raise)


def _patch_unauthenticated():
    """Patch require_super to reject as unauthenticated (401)."""

    def _raise(request):
        raise HTTPException(status_code=401, detail="Not authenticated")

    return patch("api.deploy.require_super", side_effect=_raise)


def _patch_gh(dispatch_rc=0, dispatch_err="", list_out='[{"url": "https://x/run/1"}]'):
    """Patch api.deploy._run_gh.

    First call = `workflow run` (returns dispatch_rc / dispatch_err).
    Second call = `run list` (returns list_out as stdout).
    """
    calls = {"n": 0}

    async def fake_run_gh(args):
        calls["n"] += 1
        if calls["n"] == 1:
            return dispatch_rc, "", dispatch_err
        return 0, list_out, ""

    return patch.object(deploy, "_run_gh", side_effect=fake_run_gh), calls


# ── Authorization ───────────────────────────────────────────────────────────────


class TestDeployAuth:
    def test_super_can_trigger(self):
        c = _make_client()
        gh_patch, _ = _patch_gh()
        # No real sleep between dispatch and run-list lookup.
        with (
            _patch_super(),
            gh_patch,
            patch("api.deploy.asyncio.sleep", new=AsyncMock()),
        ):
            r = c.post("/api/deploy/casita")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "triggered"
        assert body["service"] == "casita"
        assert body["run_url"] == "https://x/run/1"
        assert "github.com/EgnalZurc/smart-home" in body["actions_url"]

    def test_non_super_forbidden(self):
        c = _make_client()
        with _patch_forbidden():
            r = c.post("/api/deploy/casita")
        assert r.status_code == 403

    def test_unauthenticated(self):
        c = _make_client()
        with _patch_unauthenticated():
            r = c.post("/api/deploy/casita")
        assert r.status_code == 401

    def test_forbidden_never_shells_out(self):
        """A rejected request must not invoke gh at all."""
        c = _make_client()
        gh_patch, calls = _patch_gh()
        with _patch_forbidden(), gh_patch:
            c.post("/api/deploy/casita")
        assert calls["n"] == 0


# ── Service validation ──────────────────────────────────────────────────────────


class TestDeployServiceValidation:
    @pytest.mark.parametrize(
        "service",
        [
            "dashboard",
            "ac-service",
            "baby-gifts",
            "portfolio-monitor",
            "vacaciones",
            "casita",
            "vaultwarden",
            "valheim-admin",
        ],
    )
    def test_valid_services_accepted(self, service):
        c = _make_client()
        gh_patch, _ = _patch_gh()
        with (
            _patch_super(),
            gh_patch,
            patch("api.deploy.asyncio.sleep", new=AsyncMock()),
        ):
            r = c.post(f"/api/deploy/{service}")
        assert r.status_code == 200
        assert r.json()["service"] == service

    @pytest.mark.parametrize(
        "service",
        ["bogus", "all", "auto", "pc-agent", "ac", "casita;rm"],
    )
    def test_invalid_service_returns_400(self, service):
        c = _make_client()
        gh_patch, calls = _patch_gh()
        with _patch_super(), gh_patch:
            r = c.post(f"/api/deploy/{service}")
        assert r.status_code == 400
        # Must never reach the subprocess for an invalid service.
        assert calls["n"] == 0

    def test_valid_services_matches_frozenset(self):
        """The parametrized list above must stay in sync with the allow-list."""
        assert deploy.VALID_SERVICES == frozenset(
            {
                "dashboard",
                "ac-service",
                "baby-gifts",
                "portfolio-monitor",
                "vacaciones",
                "casita",
                "vaultwarden",
                "valheim-admin",
            }
        )


# ── gh failures ─────────────────────────────────────────────────────────────────


class TestDeployGhFailures:
    def test_gh_dispatch_failure_returns_502(self):
        c = _make_client()
        gh_patch, _ = _patch_gh(
            dispatch_rc=1, dispatch_err="HTTP 404: workflow not found"
        )
        with _patch_super(), gh_patch:
            r = c.post("/api/deploy/casita")
        assert r.status_code == 502
        assert "HTTP 404" in r.json()["detail"]

    def test_run_url_none_when_list_unparseable(self):
        """A broken `run list` response must not fail the request."""
        c = _make_client()
        gh_patch, _ = _patch_gh(list_out="not-json")
        with (
            _patch_super(),
            gh_patch,
            patch("api.deploy.asyncio.sleep", new=AsyncMock()),
        ):
            r = c.post("/api/deploy/casita")
        assert r.status_code == 200
        body = r.json()
        assert body["run_url"] is None
        # Falls back to the static actions URL for the frontend link.
        assert body["actions_url"].endswith("ci.yml")


# ── Subprocess is mocked, not real ──────────────────────────────────────────────


class TestNoRealSubprocess:
    def test_run_gh_uses_create_subprocess_exec(self):
        """_run_gh must call exec with an argument list (no shell string)."""
        c = _make_client()
        fake_proc = AsyncMock()
        fake_proc.communicate = AsyncMock(return_value=(b"", b""))
        fake_proc.returncode = 0

        async def fake_exec(*args, **kwargs):
            # First positional arg must be the gh binary, rest the arg list.
            assert args[0] == "gh"
            return fake_proc

        with (
            _patch_super(),
            patch("api.deploy.asyncio.create_subprocess_exec", side_effect=fake_exec),
            patch("api.deploy.asyncio.sleep", new=AsyncMock()),
        ):
            r = c.post("/api/deploy/casita")
        assert r.status_code == 200
