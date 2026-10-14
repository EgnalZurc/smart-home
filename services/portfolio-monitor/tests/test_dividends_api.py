"""
Tests for the /api/portfolio/dividends endpoint.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the API."""
    from main import app

    return TestClient(app)


@pytest.fixture
def mock_orchestrator():
    """Return a mock orchestrator with stub summary data."""
    orch = MagicMock()
    summary = MagicMock()
    summary.etf_analysis = [
        MagicMock(ticker="VWCE.DE", price=100.0, name="VWCE"),
        MagicMock(ticker="ISAC.L", price=50.0, name="ISAC"),
    ]
    orch.get_summary.return_value = summary
    return orch


@pytest.fixture
def mock_portfolio():
    """Return a stub ETF portfolio."""
    return {
        "vwce": {"ticker": "VWCE.DE", "name": "VWCE", "units": 10.0},
        "isac": {"ticker": "ISAC.L", "name": "ISAC", "units": 20.0},
    }


def test_dividends_endpoint_returns_shape(client, mock_orchestrator, mock_portfolio):
    """The endpoint returns the expected top-level keys."""
    with (
        patch("api.routes.get_orchestrator", return_value=mock_orchestrator),
        patch("config.get_etf_portfolio", return_value=mock_portfolio),
        patch(
            "monitors.etf_monitor.calculate_dividend_info",
            return_value={
                "last_dividend_date": "2024-09-01",
                "last_dividend_amount": 0.5,
                "ttm_dividend": 2.0,
                "dividend_yield_pct": 2.0,
                "estimated_annual_income": 20.0,
                "next_dividend_date": None,
                "frequency_days": None,
            },
        ),
    ):
        resp = client.get("/api/portfolio/dividends")

    assert resp.status_code == 200
    data = resp.json()
    assert "etfs" in data
    assert "upcoming" in data
    assert "upcoming_window_days" in data
    assert len(data["etfs"]) == 2


def test_dividends_endpoint_upcoming_window(client, mock_orchestrator, mock_portfolio):
    """Dividends within 90 days appear in 'upcoming'."""
    today = datetime.now(timezone.utc).date()
    next_date = (today + timedelta(days=30)).isoformat()

    with (
        patch("api.routes.get_orchestrator", return_value=mock_orchestrator),
        patch("config.get_etf_portfolio", return_value=mock_portfolio),
        patch(
            "monitors.etf_monitor.calculate_dividend_info",
            return_value={
                "last_dividend_date": "2024-09-01",
                "last_dividend_amount": 0.5,
                "ttm_dividend": 2.0,
                "dividend_yield_pct": 2.0,
                "estimated_annual_income": 20.0,
                "next_dividend_date": next_date,
                "frequency_days": 91,
            },
        ),
    ):
        resp = client.get("/api/portfolio/dividends")

    data = resp.json()
    assert len(data["upcoming"]) == 2
    assert data["upcoming"][0]["days_until"] == 30


def test_dividends_endpoint_empty_portfolio(client, mock_orchestrator):
    """An empty portfolio returns empty lists."""
    with (
        patch("api.routes.get_orchestrator", return_value=mock_orchestrator),
        patch("config.get_etf_portfolio", return_value={}),
    ):
        resp = client.get("/api/portfolio/dividends")

    data = resp.json()
    assert data["etfs"] == []
    assert data["upcoming"] == []
