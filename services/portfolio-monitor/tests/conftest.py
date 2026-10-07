"""
Pytest configuration and fixtures for portfolio-monitor tests.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Set DATA_DIR to temp directory before any imports that use config
_temp_dir = tempfile.mkdtemp()
os.environ.setdefault("DATA_DIR", _temp_dir)


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singletons between tests."""
    # Reset orchestrator singleton
    try:
        from orchestrator import reset_orchestrator

        reset_orchestrator()
    except ImportError:
        pass

    yield

    try:
        from orchestrator import reset_orchestrator

        reset_orchestrator()
    except ImportError:
        pass


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create a temporary data directory for tests."""
    with patch("config.DATA_DIR", tmp_path):
        yield tmp_path


@pytest.fixture
def sample_etf_config():
    """Sample ETF configuration for testing."""
    return {
        "IUIT": {
            "id": "IUIT",
            "ticker": "IUIT.L",
            "name": "iShares S&P 500 IT Sector UCITS ETF",
            "isin": "IE00B3WJKG14",
            "avg_cost": 32.77,
            "units": 33.547411,
            "monthly_contrib": 50.0,
            "phase2_contrib": 500.0,
            "start_date": "2024-01-01",
            "color": "#3A7BD5",
        }
    }


@pytest.fixture
def sample_crypto_position():
    """Sample crypto position for testing."""
    return {
        "symbol": "ETH",
        "name": "Ethereum",
        "amount": 0.17130007,
        "product": "Flexible Stake",
        "apy": 2.14,
        "type": "flexible",
        "rescue_days": 5,
        "start_date": "2024-01-01",
        "next_distribution": "2024-01-03",
        "distribution_freq_days": 2,
        "coingecko_id": "ethereum",
    }


@pytest.fixture
def sample_savings_account():
    """Sample savings account for testing."""
    return {
        "id": "emergency-fund",
        "name": "Emergency Fund",
        "bank": "Test Bank",
        "balance": 10000.0,
        "apy": 3.0,
        "type": "remunerada",
        "start_date": "2024-01-01",
        "payment_day": 25,
    }


@pytest.fixture
def irpf_2025_brackets():
    """IRPF 2025 tax brackets (Ley 7/2024)."""
    return [
        (6_000, 0.19),
        (50_000, 0.21),
        (200_000, 0.23),
        (300_000, 0.27),
        (float("inf"), 0.30),
    ]


@pytest.fixture
def mock_yfinance_response():
    """Mock yfinance ticker response."""
    import pandas as pd
    from datetime import datetime, timedelta

    dates = pd.date_range(end=datetime.now(), periods=252, freq="D")
    prices = [100 + i * 0.1 for i in range(252)]

    return pd.DataFrame(
        {
            "Open": prices,
            "High": [p * 1.01 for p in prices],
            "Low": [p * 0.99 for p in prices],
            "Close": prices,
        },
        index=dates,
    )


@pytest.fixture
def mock_coingecko_response():
    """Mock CoinGecko API response."""
    return {
        "bitcoin": {
            "eur": 50000,
            "eur_24h_change": 2.5,
            "market_cap": 1000000000,
            "ath": 60000,
            "ath_change_percentage": -16,
            "price_change_percentage_14d_in_currency": 5,
            "price_change_percentage_30d_in_currency": 10,
        },
        "ethereum": {
            "eur": 2500,
            "eur_24h_change": -1.2,
            "market_cap": 300000000,
            "ath": 4000,
            "ath_change_percentage": -37,
            "price_change_percentage_14d_in_currency": -3,
            "price_change_percentage_30d_in_currency": -8,
        },
    }
