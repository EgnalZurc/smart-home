"""Tests for energy-monitor configuration (config.py) defaults + env overrides."""

from __future__ import annotations

import importlib


def _reload_config(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config

    return importlib.reload(config)


def test_defaults_match_design(monkeypatch):
    for var in (
        "ENERGY_PORT",
        "ENERGY_POLL_INTERVAL_S",
        "ENERGY_RING_BUFFER_MAXLEN",
        "ENERGY_ENERGY_RETENTION_DAYS",
        "ENERGY_DEVICES",
        "ENERGY_ALERTS_ENABLED",
        "ENERGY_POWER_ALERT_W",
        "ENERGY_DAILY_KWH_ALERT",
        "ENERGY_MONTHLY_KWH_ALERT",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg = _reload_config(monkeypatch)
    assert cfg.SERVICE_NAME == "energy-monitor"
    assert cfg.PORT == 8012
    assert cfg.POLL_INTERVAL_S == 10
    assert cfg.RING_BUFFER_MAXLEN == 360
    assert cfg.ENERGY_RETENTION_DAYS == 1095
    assert cfg.DEVICES_JSON == "[]"
    assert cfg.ALERTS_ENABLED is True
    assert cfg.POWER_ALERT_W == 3500
    assert cfg.DAILY_KWH_ALERT == 20
    assert cfg.MONTHLY_KWH_ALERT == 400


def test_env_overrides(monkeypatch):
    cfg = _reload_config(
        monkeypatch,
        ENERGY_PORT="9999",
        ENERGY_POLL_INTERVAL_S="30",
        ENERGY_PRICE_EUR_KWH="0.22",
        ENERGY_ALERTS_ENABLED="false",
    )
    assert cfg.PORT == 9999
    assert cfg.POLL_INTERVAL_S == 30
    assert cfg.PRICE_EUR_KWH == 0.22
    assert cfg.ALERTS_ENABLED is False
    # Restore defaults for any later test that imports config fresh.
    for var in (
        "ENERGY_PORT",
        "ENERGY_POLL_INTERVAL_S",
        "ENERGY_PRICE_EUR_KWH",
        "ENERGY_ALERTS_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)
    importlib.reload(cfg)


def test_negative_threshold_logs_warning(monkeypatch, caplog):
    """LOW#8: Negative thresholds log a warning (config.py:87-89)."""
    import logging

    # Set a negative threshold value
    monkeypatch.setenv("ENERGY_POWER_ALERT_W", "-100")

    with caplog.at_level(logging.WARNING):
        cfg = _reload_config(monkeypatch)

    # The negative value should still be loaded (treated as disabled)
    assert cfg.POWER_ALERT_W == -100.0

    # But a warning should have been logged
    assert any("ENERGY_POWER_ALERT_W is negative" in r.message for r in caplog.records)
    assert any("treating as disabled" in r.message for r in caplog.records)

    # Clean up
    monkeypatch.delenv("ENERGY_POWER_ALERT_W", raising=False)
    importlib.reload(cfg)


# ══════════════════════════════════════════════════════════════════════════════
# SSRF Mitigation Tests (M1 fix)
# ══════════════════════════════════════════════════════════════════════════════


class TestIsPrivateIp:
    """Tests for is_private_ip() SSRF mitigation function."""

    def test_private_class_c(self, monkeypatch):
        """192.168.x.x addresses are private."""
        cfg = _reload_config(monkeypatch)
        assert cfg.is_private_ip("192.168.1.50") is True
        assert cfg.is_private_ip("192.168.0.1") is True
        assert cfg.is_private_ip("192.168.255.255") is True

    def test_private_class_a(self, monkeypatch):
        """10.x.x.x addresses are private."""
        cfg = _reload_config(monkeypatch)
        assert cfg.is_private_ip("10.0.0.1") is True
        assert cfg.is_private_ip("10.255.255.255") is True

    def test_private_class_b(self, monkeypatch):
        """172.16-31.x.x addresses are private."""
        cfg = _reload_config(monkeypatch)
        assert cfg.is_private_ip("172.16.0.1") is True
        assert cfg.is_private_ip("172.31.255.255") is True
        # 172.15.x.x is NOT private
        assert cfg.is_private_ip("172.15.0.1") is False
        # 172.32.x.x is NOT private
        assert cfg.is_private_ip("172.32.0.1") is False

    def test_loopback(self, monkeypatch):
        """127.x.x.x and localhost are private."""
        cfg = _reload_config(monkeypatch)
        assert cfg.is_private_ip("127.0.0.1") is True
        assert cfg.is_private_ip("127.255.255.255") is True
        assert cfg.is_private_ip("localhost") is True
        assert cfg.is_private_ip("LOCALHOST") is True  # case insensitive

    def test_public_ips_rejected(self, monkeypatch):
        """Public IPs are not private."""
        cfg = _reload_config(monkeypatch)
        assert cfg.is_private_ip("8.8.8.8") is False
        assert cfg.is_private_ip("1.1.1.1") is False
        assert cfg.is_private_ip("93.184.216.34") is False  # example.com

    def test_hostnames_rejected(self, monkeypatch):
        """Hostnames (except localhost) are not private."""
        cfg = _reload_config(monkeypatch)
        assert cfg.is_private_ip("evil.com") is False
        assert cfg.is_private_ip("google.com") is False
        assert cfg.is_private_ip("shelly.local") is False  # mDNS not allowed

    def test_url_with_private_ip(self, monkeypatch):
        """URLs with private IPs are accepted."""
        cfg = _reload_config(monkeypatch)
        assert cfg.is_private_ip("http://192.168.1.50:80") is True
        assert cfg.is_private_ip("http://10.0.0.1:8080/status") is True
        assert cfg.is_private_ip("https://172.16.0.1/api") is True

    def test_url_with_public_ip(self, monkeypatch):
        """URLs with public IPs are rejected."""
        cfg = _reload_config(monkeypatch)
        assert cfg.is_private_ip("http://8.8.8.8:80") is False
        assert cfg.is_private_ip("http://evil.com/steal-data") is False
