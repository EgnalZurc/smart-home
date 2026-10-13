"""
Tests for the GET /api/portfolio/alerts/active endpoint.

The endpoint flattens the orchestrator's cached per-asset analyses (ETF +
crypto) into the unified-alerts shape, surfacing only positions at WARN or
DANGER. These tests patch ``api.routes.get_orchestrator`` so the summary is
fully controlled and no real monitors run.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models import (
    AlertLevel,
    CryptoAnalysis,
    ETFAnalysis,
    PortfolioSummary,
    Signal,
)


@pytest.fixture
def client():
    """Create a test client for the API."""
    from main import app

    return TestClient(app)


def _make_etf(name, level, signals=None):
    return ETFAnalysis(
        fund_id=name,
        ticker=f"{name}.L",
        name=name,
        color="#000000",
        level=level,
        signals=signals or [],
    )


def _make_crypto(name, level, signals=None):
    return CryptoAnalysis(
        symbol=name,
        name=name,
        coingecko_id=name.lower(),
        level=level,
        signals=signals or [],
    )


def _patch_summary(summary):
    """Patch the orchestrator singleton to return the given summary."""
    orch = MagicMock()
    orch.get_summary.return_value = summary
    return patch("api.routes.get_orchestrator", return_value=orch)


class TestActiveAlertsEndpoint:
    """Behavioural tests for /api/portfolio/alerts/active."""

    def test_endpoint_exists(self, client):
        """Endpoint is registered (not 404)."""
        response = client.get("/api/portfolio/alerts/active")
        assert response.status_code != 404

    def test_empty_when_all_ok(self, client):
        """No alerts when every analysis is OK/INFO."""
        summary = PortfolioSummary(
            etf_analysis=[_make_etf("VWCE", AlertLevel.OK)],
            crypto_analysis=[_make_crypto("BTC", AlertLevel.INFO)],
        )
        with _patch_summary(summary):
            response = client.get("/api/portfolio/alerts/active")

        assert response.status_code == 200
        assert response.json() == {"alerts": []}

    def test_warn_etf_surfaces_as_warning(self, client):
        """A WARN ETF produces a warning-severity alert."""
        summary = PortfolioSummary(
            etf_analysis=[
                _make_etf(
                    "VWCE",
                    AlertLevel.WARN,
                    signals=[Signal(title="Drawdown", body="Down 12% from high", level="WARN")],
                )
            ],
        )
        with _patch_summary(summary):
            response = client.get("/api/portfolio/alerts/active")

        data = response.json()
        assert len(data["alerts"]) == 1
        alert = data["alerts"][0]
        assert alert["source"] == "portfolio"
        assert alert["severity"] == "warning"
        assert alert["title"] == "VWCE: WARN"
        assert alert["detail"] == "Down 12% from high"
        assert alert["link"] == "/portfolio"
        assert alert["timestamp"].endswith("+00:00")

    def test_danger_crypto_surfaces_as_critical(self, client):
        """A DANGER crypto position produces a critical-severity alert."""
        summary = PortfolioSummary(
            crypto_analysis=[
                _make_crypto(
                    "ETH",
                    AlertLevel.DANGER,
                    signals=[Signal(title="Crash", body="Down 40% in 24h", level="DANGER")],
                )
            ],
        )
        with _patch_summary(summary):
            response = client.get("/api/portfolio/alerts/active")

        data = response.json()
        assert len(data["alerts"]) == 1
        assert data["alerts"][0]["severity"] == "critical"
        assert data["alerts"][0]["title"] == "ETH: DANGER"

    def test_mixed_filters_out_ok_and_info(self, client):
        """Only WARN/DANGER are returned across both asset classes."""
        summary = PortfolioSummary(
            etf_analysis=[
                _make_etf("OK_ETF", AlertLevel.OK),
                _make_etf("INFO_ETF", AlertLevel.INFO),
                _make_etf("WARN_ETF", AlertLevel.WARN),
            ],
            crypto_analysis=[
                _make_crypto("DANGER_C", AlertLevel.DANGER),
                _make_crypto("OK_C", AlertLevel.OK),
            ],
        )
        with _patch_summary(summary):
            response = client.get("/api/portfolio/alerts/active")

        data = response.json()
        titles = {a["title"] for a in data["alerts"]}
        assert titles == {"WARN_ETF: WARN", "DANGER_C: DANGER"}

    def test_detail_joins_first_three_signals(self, client):
        """Detail concatenates at most the first three signal bodies."""
        signals = [
            Signal(title="s1", body="first", level="WARN"),
            Signal(title="s2", body="second", level="WARN"),
            Signal(title="s3", body="third", level="WARN"),
            Signal(title="s4", body="fourth", level="WARN"),
        ]
        summary = PortfolioSummary(
            etf_analysis=[_make_etf("VWCE", AlertLevel.WARN, signals=signals)],
        )
        with _patch_summary(summary):
            response = client.get("/api/portfolio/alerts/active")

        detail = response.json()["alerts"][0]["detail"]
        assert detail == "first; second; third"
        assert "fourth" not in detail

    def test_warn_with_no_signals_has_empty_detail(self, client):
        """A WARN position with no signals still surfaces, with empty detail."""
        summary = PortfolioSummary(
            etf_analysis=[_make_etf("VWCE", AlertLevel.WARN, signals=[])],
        )
        with _patch_summary(summary):
            response = client.get("/api/portfolio/alerts/active")

        data = response.json()
        assert len(data["alerts"]) == 1
        assert data["alerts"][0]["detail"] == ""
