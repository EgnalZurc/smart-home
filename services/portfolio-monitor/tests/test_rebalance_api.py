"""
Tests for the GET /api/portfolio/rebalance endpoint and the rebalance alerts
surfaced through GET /api/portfolio/alerts/active.

Both read the orchestrator's cached summary plus config (targets + threshold),
so these tests patch ``api.routes.get_orchestrator`` and the ``config``
accessors to fully control the inputs.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models import CryptoAnalysis, ETFAnalysis, PortfolioSummary


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


def _etf(fund_id, value):
    return ETFAnalysis(
        fund_id=fund_id,
        ticker=f"{fund_id}.L",
        name=fund_id,
        color="#000000",
        current_value=value,
    )


def _crypto(symbol, value):
    return CryptoAnalysis(
        symbol=symbol,
        name=symbol,
        coingecko_id=symbol.lower(),
        current_value=value,
    )


def _patch_all(summary, etf_funds, crypto_positions, threshold=5.0):
    """Patch orchestrator + config accessors used by the rebalance code paths."""
    orch = MagicMock()
    orch.get_summary.return_value = summary

    # get_etf_portfolio returns {id: entry}; compute_rebalance consumes .values()
    etf_portfolio = {f["id"]: f for f in etf_funds}

    return [
        patch("api.routes.get_orchestrator", return_value=orch),
        patch("config.get_etf_portfolio", return_value=etf_portfolio),
        patch("config.get_crypto_positions", return_value=crypto_positions),
        patch("config.get_rebalance_config", return_value={"threshold_pct": threshold}),
    ]


def _enter(patches):
    for p in patches:
        p.start()


def _exit(patches):
    for p in patches:
        p.stop()


class TestRebalanceEndpoint:
    def test_endpoint_exists(self, client):
        summary = PortfolioSummary()
        patches = _patch_all(summary, [], [])
        _enter(patches)
        try:
            response = client.get("/api/portfolio/rebalance")
        finally:
            _exit(patches)
        assert response.status_code == 200

    def test_returns_positions_and_trades(self, client):
        summary = PortfolioSummary(
            etf_analysis=[_etf("VUAA", 70.0), _etf("VWCE", 30.0)],
        )
        funds = [
            {"id": "VUAA", "target_allocation_pct": 50.0},
            {"id": "VWCE", "target_allocation_pct": 50.0},
        ]
        patches = _patch_all(summary, funds, [])
        _enter(patches)
        try:
            response = client.get("/api/portfolio/rebalance")
        finally:
            _exit(patches)

        data = response.json()
        assert data["total_value"] == 100.0
        assert data["needs_rebalance"] is True
        by_sym = {p["symbol"]: p for p in data["positions"]}
        assert by_sym["VUAA"]["current_allocation"] == 70.0
        assert by_sym["VUAA"]["target_allocation"] == 50.0
        assert by_sym["VUAA"]["deviation"] == 20.0
        assert by_sym["VUAA"]["needs_rebalance"] is True

        trades = {t["symbol"]: t for t in data["suggested_trades"]}
        assert trades["VUAA"]["action"] == "SELL"
        assert trades["VWCE"]["action"] == "BUY"

    def test_balanced_no_trades(self, client):
        summary = PortfolioSummary(
            etf_analysis=[_etf("VUAA", 50.0)],
            crypto_analysis=[_crypto("BTC", 50.0)],
        )
        funds = [{"id": "VUAA", "target_allocation_pct": 50.0}]
        positions = [{"symbol": "BTC", "target_allocation_pct": 50.0}]
        patches = _patch_all(summary, funds, positions)
        _enter(patches)
        try:
            response = client.get("/api/portfolio/rebalance")
        finally:
            _exit(patches)

        data = response.json()
        assert data["needs_rebalance"] is False
        assert data["suggested_trades"] == []

    def test_threshold_echoed(self, client):
        summary = PortfolioSummary(etf_analysis=[_etf("VUAA", 100.0)])
        funds = [{"id": "VUAA", "target_allocation_pct": 100.0}]
        patches = _patch_all(summary, funds, [], threshold=3.0)
        _enter(patches)
        try:
            response = client.get("/api/portfolio/rebalance")
        finally:
            _exit(patches)
        assert response.json()["threshold_pct"] == 3.0


class TestRebalanceAlertsInActive:
    def test_drift_surfaces_as_active_alert(self, client):
        summary = PortfolioSummary(
            etf_analysis=[_etf("VUAA", 70.0), _etf("VWCE", 30.0)],
        )
        funds = [
            {"id": "VUAA", "target_allocation_pct": 50.0},
            {"id": "VWCE", "target_allocation_pct": 50.0},
        ]
        patches = _patch_all(summary, funds, [])
        _enter(patches)
        try:
            response = client.get("/api/portfolio/alerts/active")
        finally:
            _exit(patches)

        data = response.json()
        rebalance_alerts = [
            a for a in data["alerts"] if a["title"].startswith("Rebalance:")
        ]
        assert len(rebalance_alerts) == 2
        for a in rebalance_alerts:
            assert a["source"] == "portfolio"
            assert a["severity"] == "warning"
            assert a["link"] == "/portfolio"
            assert "target" in a["detail"]

    def test_no_rebalance_alert_when_balanced(self, client):
        summary = PortfolioSummary(etf_analysis=[_etf("VUAA", 100.0)])
        funds = [{"id": "VUAA", "target_allocation_pct": 100.0}]
        patches = _patch_all(summary, funds, [])
        _enter(patches)
        try:
            response = client.get("/api/portfolio/alerts/active")
        finally:
            _exit(patches)

        data = response.json()
        rebalance_alerts = [
            a for a in data["alerts"] if a["title"].startswith("Rebalance:")
        ]
        assert rebalance_alerts == []
