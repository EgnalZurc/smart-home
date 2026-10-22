"""Tests for coherence between APP_CATALOGUE, CONTROLLABLE_CONTAINERS, and health routes.

These tests ensure that:
1. Every APP_CATALOGUE service with controllable=true is in CONTROLLABLE_CONTAINERS
2. Every CONTROLLABLE_CONTAINERS entry has a corresponding health route
3. APP_CATALOGUE statusUrl paths match actual health route paths
4. No orphan entries exist in any of the three registries

This catches mismatches like:
- A service showing a broken '...' button because it's not in CONTROLLABLE_CONTAINERS
- Health checks failing because the route doesn't exist
- Status dots not working because statusUrl doesn't match an actual endpoint
"""

import re
from pathlib import Path

import pytest

# ── Extract APP_CATALOGUE from dashboard.html ─────────────────────────────────


def _extract_app_catalogue() -> dict[str, dict]:
    """Parse APP_CATALOGUE from dashboard.html JavaScript.

    Returns a dict mapping app key -> {statusUrl, url, ...} from the JS object.
    """
    dashboard_path = (
        Path(__file__).parent.parent.parent / "src" / "static" / "dashboard.html"
    )
    content = dashboard_path.read_text(encoding="utf-8")

    # Find the APP_CATALOGUE block
    match = re.search(
        r"const\s+APP_CATALOGUE\s*=\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\};",
        content,
        re.DOTALL,
    )
    if not match:
        pytest.fail("Could not find APP_CATALOGUE in dashboard.html")

    catalogue_block = match.group(1)

    # Parse each entry: key: { ... }
    entries = {}
    # Match entries like: ac: { url: '...', statusUrl: '/api/health/ac', ... }
    entry_pattern = re.compile(
        r"(\w+)\s*:\s*\{\s*"
        r"url:\s*['\"]([^'\"]+)['\"].*?"
        r"statusUrl:\s*['\"]([^'\"]+)['\"]",
        re.DOTALL,
    )

    for m in entry_pattern.finditer(catalogue_block):
        key = m.group(1)
        entries[key] = {
            "url": m.group(2),
            "statusUrl": m.group(3),
        }

    return entries


# ── Extract health route paths from health.py ─────────────────────────────────


def _extract_health_routes() -> set[str]:
    """Parse health route paths from health.py.

    Returns a set of route paths like {'/ac', '/vacaciones', ...}.
    """
    health_path = Path(__file__).parent.parent.parent / "src" / "api" / "health.py"
    content = health_path.read_text(encoding="utf-8")

    # Find all @router.get("...") decorators
    routes = set()
    for match in re.finditer(r'@router\.get\(["\']([^"\']+)["\']', content):
        path = match.group(1)
        # Skip /all and empty path (the base health endpoint)
        if path and path not in ("/all", ""):
            routes.add(path)

    return routes


# ── Import CONTROLLABLE_CONTAINERS from the actual module ─────────────────────


def _get_controllable_containers() -> dict[str, list[str]]:
    """Import CONTROLLABLE_CONTAINERS from the containers module."""
    from system.containers import CONTROLLABLE_CONTAINERS

    return CONTROLLABLE_CONTAINERS


# ══════════════════════════════════════════════════════════════════════════════
# TESTS
# ══════════════════════════════════════════════════════════════════════════════


class TestCatalogueCoherence:
    """Tests that APP_CATALOGUE, CONTROLLABLE_CONTAINERS, and health routes are in sync."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Load all three registries for tests."""
        self.app_catalogue = _extract_app_catalogue()
        self.controllable = _get_controllable_containers()
        self.health_routes = _extract_health_routes()

    def test_app_catalogue_parsed_correctly(self):
        """Sanity check: APP_CATALOGUE was parsed and has expected entries."""
        assert len(self.app_catalogue) >= 5, "APP_CATALOGUE should have several entries"
        # Check a known entry exists
        assert "ac" in self.app_catalogue
        assert self.app_catalogue["ac"]["statusUrl"] == "/api/health/ac"

    def test_controllable_containers_not_empty(self):
        """Sanity check: CONTROLLABLE_CONTAINERS has entries."""
        assert len(self.controllable) >= 5
        assert "ac" in self.controllable

    def test_health_routes_not_empty(self):
        """Sanity check: health routes were parsed."""
        assert len(self.health_routes) >= 5
        assert "/ac" in self.health_routes

    def test_controllable_services_have_health_routes(self):
        """Every CONTROLLABLE_CONTAINERS key should have a health route.

        If a service is controllable (start/stop buttons), the dashboard
        also needs to check its health to show the status dot.
        """
        # Map CONTROLLABLE_CONTAINERS keys to their expected health route paths
        # Some keys differ (photos -> /immich, babygifts -> /baby-gifts)
        key_to_health_path = {
            "ac": "/ac",
            "vacaciones": "/vacaciones",
            "casita": "/casita",
            "photos": "/immich",
            "passwords": "/passwords",
            "babygifts": "/baby-gifts",
            "portfolio": "/portfolio",
            "valheim": "/valheim",
        }

        missing = []
        for key in self.controllable:
            expected_path = key_to_health_path.get(key)
            if expected_path is None:
                # New service without mapping - fail loudly
                missing.append(f"{key} (no mapping in test)")
            elif expected_path not in self.health_routes:
                missing.append(f"{key} (expected {expected_path})")

        assert not missing, (
            f"CONTROLLABLE_CONTAINERS keys without health routes: {missing}. "
            f"Available routes: {sorted(self.health_routes)}"
        )

    def test_app_catalogue_status_urls_match_health_routes(self):
        """Every APP_CATALOGUE statusUrl should point to an existing health route."""
        missing = []
        for key, entry in self.app_catalogue.items():
            status_url = entry.get("statusUrl", "")
            # Extract the path part (remove /api/health prefix)
            if status_url.startswith("/api/health"):
                path = status_url.replace("/api/health", "") or "/"
                if path != "/" and path not in self.health_routes:
                    missing.append(f"{key}: {status_url} -> {path}")

        assert not missing, (
            f"APP_CATALOGUE entries with invalid statusUrl: {missing}. "
            f"Available routes: {sorted(self.health_routes)}"
        )

    def test_controllable_containers_in_app_catalogue(self):
        """Services in CONTROLLABLE_CONTAINERS should be in APP_CATALOGUE.

        If a service can be started/stopped, it should appear in the dashboard.
        This catches orphan entries in CONTROLLABLE_CONTAINERS.
        """
        not_in_catalogue = []
        for key in self.controllable:
            if key not in self.app_catalogue:
                not_in_catalogue.append(key)

        assert not not_in_catalogue, (
            f"CONTROLLABLE_CONTAINERS keys not in APP_CATALOGUE: {not_in_catalogue}. "
            f"Either add them to APP_CATALOGUE or remove from CONTROLLABLE_CONTAINERS."
        )

    def test_app_catalogue_controllable_in_controllable_containers(self):
        """APP_CATALOGUE entries should be in CONTROLLABLE_CONTAINERS.

        Every app shown in the dashboard should be controllable (start/stop).
        This catches services that show a '...' button because they're missing
        from CONTROLLABLE_CONTAINERS.

        Note: Some services may intentionally not be controllable (external services,
        core infrastructure). Add them to the allowlist below.
        """
        # Services that are intentionally not controllable from the dashboard
        # (external services, core infra that shouldn't be stopped)
        intentionally_not_controllable: set[str] = set()

        not_controllable = []
        for key in self.app_catalogue:
            if (
                key not in self.controllable
                and key not in intentionally_not_controllable
            ):
                not_controllable.append(key)

        assert not not_controllable, (
            f"APP_CATALOGUE entries not in CONTROLLABLE_CONTAINERS: {not_controllable}. "
            f"Either add them to CONTROLLABLE_CONTAINERS (system/containers.py) "
            f"or add to intentionally_not_controllable in this test."
        )

    def test_no_duplicate_container_names(self):
        """No container name should appear in multiple CONTROLLABLE_CONTAINERS entries.

        This would cause confusing behavior where starting one service affects another.
        """
        seen: dict[str, str] = {}  # container_name -> key
        duplicates = []

        for key, containers in self.controllable.items():
            for container in containers:
                if container in seen:
                    duplicates.append(
                        f"{container} in both '{seen[container]}' and '{key}'"
                    )
                else:
                    seen[container] = key

        assert not duplicates, f"Duplicate container names: {duplicates}"


class TestHealthRouteCoverage:
    """Tests that health routes cover all expected services."""

    def test_infrastructure_services_have_health_routes(self):
        """Infrastructure services should have health routes even if not in APP_CATALOGUE.

        These services (metrics, energy, presence, calendar) are internal infrastructure
        and may not appear in the user-facing catalogue, but should still be monitored.
        """
        health_routes = _extract_health_routes()

        infra_services = ["/metrics", "/energy", "/presence", "/calendar"]
        missing = [s for s in infra_services if s not in health_routes]

        assert not missing, (
            f"Infrastructure services without health routes: {missing}. "
            f"Add them to health.py."
        )

    def test_health_all_includes_controllable_services(self):
        """The /all endpoint should include all controllable services.

        Parsing the get_all_health function to verify the keys list matches.
        """
        health_path = Path(__file__).parent.parent.parent / "src" / "api" / "health.py"
        content = health_path.read_text(encoding="utf-8")

        # Find the keys list in get_all_health
        match = re.search(r"keys\s*=\s*\[([^\]]+)\]", content, re.DOTALL)
        if not match:
            pytest.fail("Could not find 'keys' list in get_all_health")

        keys_str = match.group(1)
        # Parse the list: ["backend", "zigbee", ...]
        keys = [k.strip().strip("\"'") for k in keys_str.split(",") if k.strip()]

        controllable = _get_controllable_containers()

        # Map controllable keys to health keys
        key_mapping = {
            "photos": "immich",
            "babygifts": "baby-gifts",
        }

        missing = []
        for ctrl_key in controllable:
            health_key = key_mapping.get(ctrl_key, ctrl_key)
            if health_key not in keys:
                missing.append(f"{ctrl_key} (as {health_key})")

        assert not missing, (
            f"CONTROLLABLE_CONTAINERS services not in /all keys: {missing}. "
            f"Add the health check call and key to get_all_health in health.py."
        )
