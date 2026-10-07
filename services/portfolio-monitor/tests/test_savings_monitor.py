"""
Tests for the savings_monitor module.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from models import AlertLevel


class TestInterestCalculation:
    """Tests for interest calculation functions."""

    def test_calculate_interest(self):
        """Interest is calculated correctly."""
        from monitors.savings_monitor import calculate_interest

        monthly, yearly = calculate_interest(balance=10000, apy=3.0)

        assert abs(yearly - 300) < 0.01  # 10000 * 0.03
        assert abs(monthly - 25) < 0.01  # 300 / 12

    def test_calculate_interest_zero_balance(self):
        """Zero balance means zero interest."""
        from monitors.savings_monitor import calculate_interest

        monthly, yearly = calculate_interest(balance=0, apy=5.0)

        assert monthly == 0
        assert yearly == 0

    def test_calculate_interest_zero_apy(self):
        """Zero APY means zero interest."""
        from monitors.savings_monitor import calculate_interest

        monthly, yearly = calculate_interest(balance=10000, apy=0)

        assert monthly == 0
        assert yearly == 0


class TestDaysUntilPayment:
    """Tests for payment date calculation."""

    def test_payment_this_month_future(self):
        """Payment day this month is in the future."""
        from monitors.savings_monitor import days_until_next_payment

        # Mock datetime to a known date
        with patch("monitors.savings_monitor.datetime") as mock_dt:
            # Set today to the 10th
            mock_now = datetime(2024, 6, 10, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now

            days = days_until_next_payment(payment_day=25)

        assert days == 15  # 25 - 10

    def test_payment_this_month_past(self):
        """Payment day this month has passed."""
        from monitors.savings_monitor import days_until_next_payment

        with patch("monitors.savings_monitor.datetime") as mock_dt:
            # Set today to the 28th
            mock_now = datetime(2024, 6, 28, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now

            days = days_until_next_payment(payment_day=25)

        # Should be next month's 25th
        assert days > 0
        assert days < 31

    def test_payment_today(self):
        """Payment day is today."""
        from monitors.savings_monitor import days_until_next_payment

        with patch("monitors.savings_monitor.datetime") as mock_dt:
            mock_now = datetime(2024, 6, 25, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now

            days = days_until_next_payment(payment_day=25)

        assert days == 0

    def test_payment_day_doesnt_exist_in_month(self):
        """Payment day adjusted if it doesn't exist in month."""
        from monitors.savings_monitor import days_until_next_payment

        with patch("monitors.savings_monitor.datetime") as mock_dt:
            # February, payment day 30
            mock_now = datetime(2024, 2, 15, tzinfo=timezone.utc)
            mock_dt.now.return_value = mock_now

            days = days_until_next_payment(payment_day=30)

        # Should use last day of month (29 in leap year)
        assert days >= 0


class TestSavingsMonitor:
    """Tests for the SavingsMonitor class."""

    @pytest.mark.asyncio
    async def test_empty_accounts(self):
        """Monitor handles empty accounts list."""
        from monitors.savings_monitor import SavingsMonitor

        with patch("monitors.savings_monitor.SAVINGS_ACCOUNTS", []):
            monitor = SavingsMonitor()
            result = await monitor.run()

        assert result["total_balance"] == 0
        assert result["yearly_interest"] == 0
        assert result["level"] == AlertLevel.OK
        assert len(result["analysis"]) == 0

    @pytest.mark.asyncio
    async def test_single_account(self):
        """Monitor processes single account correctly."""
        from monitors.savings_monitor import SavingsMonitor

        accounts = [
            {
                "id": "savings-1",
                "name": "Emergency Fund",
                "bank": "Test Bank",
                "balance": 10000,
                "apy": 3.0,
                "type": "remunerada",
                "start_date": "2024-01-01",
                "payment_day": 25,
            }
        ]

        with patch("monitors.savings_monitor.SAVINGS_ACCOUNTS", accounts):
            monitor = SavingsMonitor()
            result = await monitor.run()

        assert result["total_balance"] == 10000
        assert abs(result["yearly_interest"] - 300) < 0.01
        assert len(result["analysis"]) == 1

        analysis = result["analysis"][0]
        assert analysis.account_id == "savings-1"
        assert analysis.balance == 10000
        assert analysis.apy == 3.0
        assert analysis.level == AlertLevel.OK

    @pytest.mark.asyncio
    async def test_multiple_accounts(self):
        """Monitor aggregates multiple accounts."""
        from monitors.savings_monitor import SavingsMonitor

        accounts = [
            {
                "id": "savings-1",
                "name": "Account 1",
                "bank": "Bank A",
                "balance": 10000,
                "apy": 3.0,
            },
            {
                "id": "savings-2",
                "name": "Account 2",
                "bank": "Bank B",
                "balance": 5000,
                "apy": 2.5,
            },
        ]

        with patch("monitors.savings_monitor.SAVINGS_ACCOUNTS", accounts):
            monitor = SavingsMonitor()
            result = await monitor.run()

        assert result["total_balance"] == 15000
        # 10000 * 0.03 + 5000 * 0.025 = 300 + 125 = 425
        assert abs(result["yearly_interest"] - 425) < 0.01
        assert len(result["analysis"]) == 2

    @pytest.mark.asyncio
    async def test_get_level(self):
        """Monitor always returns OK level for savings."""
        from monitors.savings_monitor import SavingsMonitor

        with patch("monitors.savings_monitor.SAVINGS_ACCOUNTS", []):
            monitor = SavingsMonitor()
            await monitor.run()

        assert monitor.get_level() == AlertLevel.OK

    @pytest.mark.asyncio
    async def test_get_last_update(self):
        """Monitor tracks last update time."""
        from monitors.savings_monitor import SavingsMonitor

        accounts = [
            {
                "id": "test",
                "name": "Test",
                "bank": "Bank",
                "balance": 1000,
                "apy": 2.0,
            }
        ]

        with patch("monitors.savings_monitor.SAVINGS_ACCOUNTS", accounts):
            monitor = SavingsMonitor()

            # Before run
            assert monitor.get_last_update() is None

            await monitor.run()

            # After run - check the result contains last_update
            result = await monitor.run()
            assert result["last_update"] is not None

    @pytest.mark.asyncio
    async def test_handles_invalid_account(self):
        """Monitor handles invalid account data gracefully."""
        from monitors.savings_monitor import SavingsMonitor

        accounts = [
            {
                "id": "valid",
                "name": "Valid Account",
                "bank": "Bank",
                "balance": 5000,
                "apy": 3.0,
            },
            # Account with missing required fields
            {"id": "invalid"},
        ]

        with patch("monitors.savings_monitor.SAVINGS_ACCOUNTS", accounts):
            monitor = SavingsMonitor()
            result = await monitor.run()

        # Should still process the valid account
        assert result["total_balance"] >= 5000
        assert len(result["analysis"]) >= 1
