"""
Pytest configuration and fixtures for portfolio-monitor tests.
"""

import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


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
def irpf_2025_brackets():
    """IRPF 2025 tax brackets (Ley 7/2024)."""
    return [
        (6_000, 0.19),
        (50_000, 0.21),
        (200_000, 0.23),
        (300_000, 0.27),
        (float("inf"), 0.30),
    ]
