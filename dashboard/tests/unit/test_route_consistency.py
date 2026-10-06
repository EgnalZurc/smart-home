"""Unit tests to verify frontend-backend route consistency.

These tests ensure that:
1. All frontend HTML/JS files use the correct API route prefixes
2. Backend email/URL generators use routes that actually exist
3. No hardcoded legacy routes remain that would cause 404s

This prevents deployment of mismatched frontend/backend routes.
"""

import re
from pathlib import Path

import pytest

# Path to dashboard source
DASHBOARD_SRC = Path(__file__).parent.parent.parent / "src"
STATIC_DIR = DASHBOARD_SRC / "static"


class TestFrontendAuthRoutes:
    """Verify all frontend files use /api/auth/* routes, not /auth/*."""

    # Pattern to find fetch('/auth/...) or action="/auth/..."
    # Excludes comments and /api/auth/
    LEGACY_AUTH_PATTERN = re.compile(
        r"""(?:fetch\s*\(\s*['"]|action\s*=\s*['"])(/auth/[^'"]+)""",
        re.IGNORECASE,
    )

    def _scan_file_for_legacy_auth(self, filepath: Path) -> list[tuple[int, str]]:
        """Return list of (line_number, matched_route) for legacy auth routes."""
        issues = []
        content = filepath.read_text(encoding="utf-8")
        for i, line in enumerate(content.splitlines(), 1):
            # Skip if it's the /api/auth pattern (correct usage)
            if "/api/auth/" in line:
                continue
            match = self.LEGACY_AUTH_PATTERN.search(line)
            if match:
                issues.append((i, match.group(1)))
        return issues

    def test_dashboard_html_uses_api_auth_routes(self):
        """dashboard.html must use /api/auth/* for all auth calls."""
        dashboard = STATIC_DIR / "dashboard.html"
        if not dashboard.exists():
            pytest.skip("dashboard.html not found")

        issues = self._scan_file_for_legacy_auth(dashboard)
        assert not issues, (
            "dashboard.html has legacy /auth/ routes that should be /api/auth/:\n"
            + "\n".join(f"  Line {ln}: {route}" for ln, route in issues)
        )

    def test_login_html_uses_api_auth_routes(self):
        """login.html must use /api/auth/* for form actions."""
        login = STATIC_DIR / "login.html"
        if not login.exists():
            pytest.skip("login.html not found")

        issues = self._scan_file_for_legacy_auth(login)
        assert not issues, (
            "login.html has legacy /auth/ routes that should be /api/auth/:\n"
            + "\n".join(f"  Line {ln}: {route}" for ln, route in issues)
        )

    def test_all_static_html_uses_api_auth_routes(self):
        """All HTML files in static/ must use /api/auth/* for auth calls."""
        if not STATIC_DIR.exists():
            pytest.skip("static directory not found")

        all_issues = {}
        for html_file in STATIC_DIR.glob("*.html"):
            issues = self._scan_file_for_legacy_auth(html_file)
            if issues:
                all_issues[html_file.name] = issues

        assert not all_issues, (
            "Found legacy /auth/ routes (should be /api/auth/):\n"
            + "\n".join(
                f"  {fname}:\n"
                + "\n".join(f"    Line {ln}: {route}" for ln, route in issues)
                for fname, issues in all_issues.items()
            )
        )

    def test_js_files_use_api_auth_routes(self):
        """All JS files must use /api/auth/* for auth calls."""
        if not STATIC_DIR.exists():
            pytest.skip("static directory not found")

        all_issues = {}
        for js_file in STATIC_DIR.rglob("*.js"):
            issues = self._scan_file_for_legacy_auth(js_file)
            if issues:
                all_issues[str(js_file.relative_to(STATIC_DIR))] = issues

        assert not all_issues, "Found legacy /auth/ routes in JS files:\n" + "\n".join(
            f"  {fname}:\n"
            + "\n".join(f"    Line {ln}: {route}" for ln, route in issues)
            for fname, issues in all_issues.items()
        )


class TestBackendUrlGenerators:
    """Verify backend URL generators produce routes that exist."""

    def test_make_action_url_uses_api_prefix(self):
        """auth_users.make_action_url must generate /api/auth/* URLs.

        Checks the source code directly to avoid import dependency issues.
        """
        auth_users_path = DASHBOARD_SRC / "auth_users.py"
        if not auth_users_path.exists():
            pytest.skip("auth_users.py not found")

        content = auth_users_path.read_text(encoding="utf-8")

        # Find the make_action_url function and check it uses /api/auth/
        # Look for the f-string that builds the URL
        pattern = re.compile(
            r'def\s+make_action_url.*?return\s+f["\']([^"\']+)["\']', re.DOTALL
        )
        match = pattern.search(content)
        assert match, "Could not find make_action_url function"

        url_template = match.group(1)
        assert "/api/auth/trust/" in url_template, (
            f"make_action_url uses legacy route pattern: {url_template}\n"
            "Should use /api/auth/trust/ prefix"
        )

    def test_trust_url_comments_use_api_prefix(self):
        """Comments documenting trust URLs should reflect /api/auth/ paths."""
        auth_users_path = DASHBOARD_SRC / "auth_users.py"
        if not auth_users_path.exists():
            pytest.skip("auth_users.py not found")

        content = auth_users_path.read_text(encoding="utf-8")

        # Check that comments about trust URLs use /api/auth/
        if (
            "/auth/trust/approve" in content
            and "/api/auth/trust/approve" not in content
        ):
            pytest.fail(
                "auth_users.py has comments with legacy /auth/trust/ URLs - "
                "update to /api/auth/trust/"
            )


class TestFrontendApiRoutes:
    """Verify frontend uses consistent /api/* prefixed routes."""

    # Pattern for fetch calls that DON'T use /api/ prefix (excluding external URLs)
    # This catches things like fetch('/health') that should be fetch('/api/health')
    NON_API_FETCH_PATTERN = re.compile(
        r"""fetch\s*\(\s*['"](?!/api/|/static/|https?://|//)(/[a-z][^'"]+)""",
        re.IGNORECASE,
    )

    # Known exceptions - routes that legitimately don't use /api/
    ALLOWED_NON_API_ROUTES = {
        "/static/",  # Static assets
    }

    def _scan_file_for_non_api_fetch(self, filepath: Path) -> list[tuple[int, str]]:
        """Return list of (line_number, matched_route) for non-/api/ fetches."""
        issues = []
        content = filepath.read_text(encoding="utf-8")
        for i, line in enumerate(content.splitlines(), 1):
            match = self.NON_API_FETCH_PATTERN.search(line)
            if match:
                route = match.group(1)
                # Check if it's an allowed exception
                if not any(
                    route.startswith(allowed) for allowed in self.ALLOWED_NON_API_ROUTES
                ):
                    issues.append((i, route))
        return issues

    def test_dashboard_fetches_use_api_prefix(self):
        """dashboard.html fetches should use /api/* prefix."""
        dashboard = STATIC_DIR / "dashboard.html"
        if not dashboard.exists():
            pytest.skip("dashboard.html not found")

        issues = self._scan_file_for_non_api_fetch(dashboard)
        # Filter out known OK patterns
        issues = [(ln, r) for ln, r in issues if not r.startswith("/api/")]

        assert not issues, (
            "dashboard.html has fetch calls without /api/ prefix:\n"
            + "\n".join(f"  Line {ln}: {route}" for ln, route in issues)
        )


class TestAuthRouterPrefix:
    """Verify auth router configuration via source code inspection."""

    def test_auth_router_has_api_prefix_in_source(self):
        """Auth router definition must specify /api/auth prefix."""
        auth_routes_path = DASHBOARD_SRC / "api" / "auth_routes.py"
        if not auth_routes_path.exists():
            pytest.skip("auth_routes.py not found")

        content = auth_routes_path.read_text(encoding="utf-8")

        # Look for router definition with prefix
        # Pattern: router = APIRouter(prefix="/api/auth"...)
        if 'prefix="/api/auth"' not in content and "prefix='/api/auth'" not in content:
            pytest.fail(
                "auth_routes.py router does not have prefix='/api/auth' - "
                "check APIRouter definition"
            )

    def test_auth_routes_docstring_reflects_api_prefix(self):
        """Auth routes docstring should document /api/auth/* paths."""
        auth_routes_path = DASHBOARD_SRC / "api" / "auth_routes.py"
        if not auth_routes_path.exists():
            pytest.skip("auth_routes.py not found")

        content = auth_routes_path.read_text(encoding="utf-8")

        # Extract docstring (first triple-quoted string)
        docstring_match = re.search(r'^"""(.*?)"""', content, re.DOTALL)
        if not docstring_match:
            pytest.skip("No module docstring found")

        docstring = docstring_match.group(1)

        # Check that route documentation uses /api/auth/ prefix
        if "/auth/" in docstring:
            # Should have /api/auth/ for all routes
            lines_with_auth = [
                line.strip()
                for line in docstring.split("\n")
                if "/auth/" in line and "GET" in line or "POST" in line
            ]
            for line in lines_with_auth:
                if "/auth/" in line and "/api/auth/" not in line:
                    pytest.fail(
                        f"Docstring has legacy route documentation: {line}\n"
                        "Should use /api/auth/ prefix"
                    )
