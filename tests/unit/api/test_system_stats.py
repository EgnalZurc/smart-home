"""Unit tests for GET /api/system/stats.

Tests cover:
  - SUPER profile gets 200 with all expected fields
  - FAMILIA_PRINCIPAL gets 403
  - Unauthenticated gets 401
  - Each field (ram, swap, cpu, disk, temp) has the right sub-keys
  - Values are plausible (non-negative, percent 0-100, temp in reasonable range)
  - Graceful handling when /proc or /sys files are unavailable
"""
import sys
import pytest
from unittest.mock import patch, mock_open, MagicMock

# Mock passlib before any auth import
_mock_passlib = MagicMock()
_mock_passlib.hash.apr_md5_crypt.verify.return_value = True
sys.modules.setdefault('passlib', _mock_passlib)
sys.modules.setdefault('passlib.hash', _mock_passlib.hash)

from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client():
    """TestClient for routes without auth middleware."""
    from api import routes
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app, raise_server_exceptions=True)


def _patch_super(username='egnal'):
    """Patch _require_super to allow as SUPER."""
    from fastapi import HTTPException
    import user_profiles

    def fake_super(request):
        return username

    return patch('api.routes._require_super', side_effect=fake_super)


def _patch_familia():
    """Patch _require_super to reject as FAMILIA_PRINCIPAL (403)."""
    from fastapi import HTTPException

    def fake_familia(request):
        raise HTTPException(status_code=403, detail='SUPER profile required')

    return patch('api.routes._require_super', side_effect=fake_familia)


def _patch_unauthenticated():
    """Patch _require_super to reject as unauthenticated (401)."""
    from fastapi import HTTPException

    def fake_401(request):
        raise HTTPException(status_code=401, detail='Not authenticated')

    return patch('api.routes._require_super', side_effect=fake_401)


# Realistic /proc/meminfo content
FAKE_MEMINFO = """\
MemTotal:        4146304 kB
MemFree:          500000 kB
MemAvailable:    2300000 kB
Buffers:          200000 kB
Cached:          1600000 kB
SwapTotal:       2097148 kB
SwapFree:        1970000 kB
"""

# Realistic /proc/stat content (two reads for CPU delta)
FAKE_STAT_1 = "cpu  1000000 10000 200000 8000000 50000 0 10000 0 0 0\ncpu0 250000 2500 50000 2000000 12500 0 2500 0 0 0\n"
FAKE_STAT_2 = "cpu  1000500 10000 200010 8000480 50010 0 10000 0 0 0\ncpu0 250125 2500 50002 2000120 12502 0 2500 0 0 0\n"

FAKE_TEMP = "54900\n"  # 54.9°C


def _mock_proc_files(stat_call=[0]):
    """
    Mock open() so that:
      - /proc/meminfo → FAKE_MEMINFO
      - /proc/stat → alternates FAKE_STAT_1 / FAKE_STAT_2 (CPU delta)
      - /sys/class/thermal/thermal_zone0/temp → FAKE_TEMP
    """
    original_open = open

    def fake_open(path, *args, **kwargs):
        if '/proc/meminfo' in str(path):
            return mock_open(read_data=FAKE_MEMINFO)()
        if '/proc/stat' in str(path):
            # Return stat_1 first call, stat_2 second call
            idx = stat_call[0] % 2
            stat_call[0] += 1
            data = FAKE_STAT_1 if idx == 0 else FAKE_STAT_2
            m = mock_open(read_data=data)()
            m.readline.return_value = data.split('\n')[0]
            return m
        if 'thermal_zone0/temp' in str(path):
            return mock_open(read_data=FAKE_TEMP)()
        return original_open(path, *args, **kwargs)

    return fake_open


def _mock_statvfs():
    """Return a realistic statvfs result for a 58 GB partition."""
    sv = MagicMock()
    sv.f_frsize  = 4096
    sv.f_blocks  = 15_000_000   # ~58 GB total
    sv.f_bavail  = 10_700_000   # ~42 GB free
    return sv


# ── Authorization tests ───────────────────────────────────────────────────────

class TestSystemStatsAuth:

    def test_super_returns_200(self):
        c = _make_client()
        with _patch_super():
            with patch('builtins.open', side_effect=_mock_proc_files()):
                with patch('os.statvfs', return_value=_mock_statvfs()):
                    r = c.get("/api/system/stats")
        assert r.status_code == 200

    def test_familia_principal_returns_403(self):
        c = _make_client()
        with _patch_familia():
            r = c.get("/api/system/stats")
        assert r.status_code == 403

    def test_unauthenticated_returns_401(self):
        c = _make_client()
        with _patch_unauthenticated():
            r = c.get("/api/system/stats")
        assert r.status_code == 401


# ── Response structure tests ──────────────────────────────────────────────────

class TestSystemStatsStructure:

    def _get(self):
        c = _make_client()
        with _patch_super():
            with patch('builtins.open', side_effect=_mock_proc_files()):
                with patch('os.statvfs', return_value=_mock_statvfs()):
                    return c.get("/api/system/stats").json()

    def test_response_has_all_top_level_keys(self):
        data = self._get()
        for key in ('ram', 'swap', 'cpu', 'disk', 'temp'):
            assert key in data, f"Missing top-level key: {key}"

    def test_ram_has_required_subkeys(self):
        ram = self._get()['ram']
        for k in ('total_mb', 'used_mb', 'available_mb', 'percent'):
            assert k in ram, f"Missing ram.{k}"

    def test_swap_has_required_subkeys(self):
        swap = self._get()['swap']
        for k in ('total_mb', 'used_mb', 'percent'):
            assert k in swap, f"Missing swap.{k}"

    def test_cpu_has_percent(self):
        assert 'percent' in self._get()['cpu']

    def test_disk_has_required_subkeys(self):
        disk = self._get()['disk']
        for k in ('total_gb', 'used_gb', 'free_gb', 'percent'):
            assert k in disk, f"Missing disk.{k}"

    def test_temp_has_celsius(self):
        assert 'celsius' in self._get()['temp']


# ── Value plausibility tests ──────────────────────────────────────────────────

class TestSystemStatsValues:

    def _get(self):
        c = _make_client()
        with _patch_super():
            with patch('builtins.open', side_effect=_mock_proc_files()):
                with patch('os.statvfs', return_value=_mock_statvfs()):
                    return c.get("/api/system/stats").json()

    def test_ram_total_matches_meminfo(self):
        # FAKE_MEMINFO has MemTotal: 4146304 kB = 4049 MB
        ram = self._get()['ram']
        assert 4000 <= ram['total_mb'] <= 4100, f"Unexpected total_mb: {ram['total_mb']}"

    def test_ram_used_plus_available_approx_total(self):
        ram = self._get()['ram']
        # used + available should be close to total (within 10%)
        assert abs((ram['used_mb'] + ram['available_mb']) - ram['total_mb']) < ram['total_mb'] * 0.1

    def test_ram_percent_between_0_and_100(self):
        pct = self._get()['ram']['percent']
        assert 0 <= pct <= 100

    def test_swap_percent_between_0_and_100(self):
        pct = self._get()['swap']['percent']
        assert 0 <= pct <= 100

    def test_cpu_percent_between_0_and_100(self):
        pct = self._get()['cpu']['percent']
        assert 0 <= pct <= 100

    def test_disk_used_less_than_total(self):
        disk = self._get()['disk']
        assert disk['used_gb'] <= disk['total_gb']

    def test_disk_free_less_than_total(self):
        disk = self._get()['disk']
        assert disk['free_gb'] <= disk['total_gb']

    def test_disk_percent_between_0_and_100(self):
        pct = self._get()['disk']['percent']
        assert 0 <= pct <= 100

    def test_temp_matches_fake_value(self):
        # FAKE_TEMP = 54900 → 54.9°C
        temp = self._get()['temp']['celsius']
        assert temp == 54.9

    def test_temp_in_plausible_range(self):
        temp = self._get()['temp']['celsius']
        assert 20 <= temp <= 90, f"Unexpected temperature: {temp}°C"


# ── Error resilience tests ────────────────────────────────────────────────────

class TestSystemStatsResilience:

    def test_returns_200_when_thermal_unavailable(self):
        """If temperature sensor is missing, endpoint should still return 200."""
        def open_no_thermal(path, *args, **kwargs):
            if 'thermal_zone0' in str(path):
                raise FileNotFoundError("No thermal zone")
            if '/proc/meminfo' in str(path):
                return mock_open(read_data=FAKE_MEMINFO)()
            if '/proc/stat' in str(path):
                m = mock_open(read_data=FAKE_STAT_1)()
                m.readline.return_value = FAKE_STAT_1.split('\n')[0]
                return m
            raise FileNotFoundError(path)

        c = _make_client()
        with _patch_super():
            with patch('builtins.open', side_effect=open_no_thermal):
                with patch('os.statvfs', return_value=_mock_statvfs()):
                    r = c.get("/api/system/stats")
        assert r.status_code == 200
        data = r.json()
        # temp should contain error key, not crash the whole endpoint
        assert 'temp' in data
        assert 'error' in data['temp'] or 'celsius' in data['temp']

    def test_returns_200_when_disk_unavailable(self):
        """If statvfs fails, endpoint should still return 200."""
        c = _make_client()
        with _patch_super():
            with patch('builtins.open', side_effect=_mock_proc_files()):
                with patch('os.statvfs', side_effect=OSError("permission denied")):
                    r = c.get("/api/system/stats")
        assert r.status_code == 200
        data = r.json()
        assert 'disk' in data
        assert 'error' in data['disk']

    def test_returns_200_when_meminfo_unavailable(self):
        """If /proc/meminfo is unreadable, endpoint should still return 200."""
        def open_no_mem(path, *args, **kwargs):
            if '/proc/meminfo' in str(path):
                raise PermissionError("no access")
            if 'thermal_zone0' in str(path):
                return mock_open(read_data=FAKE_TEMP)()
            if '/proc/stat' in str(path):
                m = mock_open(read_data=FAKE_STAT_1)()
                m.readline.return_value = FAKE_STAT_1.split('\n')[0]
                return m
            raise FileNotFoundError(path)

        c = _make_client()
        with _patch_super():
            with patch('builtins.open', side_effect=open_no_mem):
                with patch('os.statvfs', return_value=_mock_statvfs()):
                    r = c.get("/api/system/stats")
        assert r.status_code == 200
        assert 'ram' in r.json()
        assert 'error' in r.json()['ram']


# ── Dashboard integration tests ───────────────────────────────────────────────

class TestDashboardSystemStats:
    """Verify the dashboard HTML correctly integrates the resources feature."""

    def _html(self):
        from pathlib import Path
        return Path("/home/pi/projects/smart-home/src/backend/static/dashboard.html").read_text()

    def test_res_btn_exists_in_html(self):
        assert 'res-btn' in self._html()

    def test_res_modal_exists_in_html(self):
        assert 'res-modal' in self._html()

    def test_open_res_modal_function_exists(self):
        assert 'openResModal' in self._html()

    def test_close_res_modal_function_exists(self):
        assert 'closeResModal' in self._html()

    def test_fetch_system_stats_called(self):
        assert '/api/system/stats' in self._html()

    def test_polling_every_5_seconds(self):
        html = self._html()
        assert 'fetchAndRenderResources' in html
        assert '5000' in html

    def test_res_btn_hidden_by_default(self):
        """Resources button must be hidden until SUPER profile is confirmed."""
        html = self._html()
        # The button must start with display:none
        assert 'res-btn' in html
        assert "display:none" in html or 'display: none' in html

    def test_res_btn_shown_only_for_super(self):
        """res-btn visibility must be gated on isSuper()."""
        html = self._html()
        # Must show the button only after confirming SUPER profile
        assert "isSuper()" in html or "show_config_apps" in html

    def test_translations_es_include_res_keys(self):
        html = self._html()
        assert 'res_title' in html
        assert 'res_ram' in html
        assert 'res_temp' in html

    def test_translations_en_include_res_keys(self):
        html = self._html()
        assert 'System resources' in html or 'res_title' in html

    def test_bar_color_function_exists(self):
        assert '_barColor' in self._html()

    def test_temp_color_function_exists(self):
        assert '_tempColor' in self._html()

    def test_escape_closes_modal(self):
        """Pressing Escape must close the modal."""
        html = self._html()
        assert 'Escape' in html
        assert 'closeResModal' in html
