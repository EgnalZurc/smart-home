"""
Portfolio Monitor — Data models and enums.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any


class AlertLevel(IntEnum):
    """Alert severity levels, ordered by severity."""

    OK = 0
    INFO = 1
    WARN = 2
    DANGER = 3

    def escalate(self, other: "AlertLevel") -> "AlertLevel":
        """Return the higher severity level."""
        return max(self, other)


@dataclass
class Signal:
    """A single alert signal."""

    title: str
    body: str
    level: str  # "OK", "INFO", "WARN", "DANGER"


@dataclass
class ETFAnalysis:
    """Analysis result for a single ETF."""

    fund_id: str
    ticker: str
    name: str
    color: str

    # Price data
    price: float = 0.0
    high_52w: float = 0.0
    low_52w: float = 0.0

    # Changes
    chg_1d: float = 0.0
    chg_1m: float = 0.0
    chg_3m: float = 0.0
    chg_ytd: float = 0.0

    # Technical indicators
    ma50: float | None = None
    ma200: float | None = None
    drawdown: float = 0.0
    annual_vol: float = 0.0

    # Position data
    units: float = 0.0
    avg_cost: float | None = None
    current_value: float = 0.0
    gain_loss_eur: float = 0.0
    gain_loss_pct: float = 0.0
    monthly_contrib: float = 0.0
    start_date: str = ""

    # Tax impact
    tax_gain: float = 0.0
    tax_irpf: float = 0.0
    tax_net: float = 0.0

    # Projection
    proj_expected: float | None = None
    proj_actual: float = 0.0
    proj_deviation: float = 0.0
    proj_year: int = 1

    # Signals
    signals: list[Signal] = field(default_factory=list)
    level: AlertLevel = AlertLevel.OK
    recommendation: Signal | None = None

    # OHLC for sparkline
    ohlc: list[list[float]] = field(default_factory=list)


@dataclass
class CryptoAnalysis:
    """Analysis result for a single crypto staking position."""

    symbol: str
    name: str
    coingecko_id: str

    # Position data
    amount: float = 0.0
    product: str = ""
    position_type: str = "flexible"  # "flexible" or "fixed"
    apy: float = 0.0
    rescue_days: int = 0
    start_date: str = ""
    maturity_date: str | None = None
    next_distribution: str | None = None
    distribution_freq_days: int = 1

    # Price data
    price_eur: float = 0.0
    change_24h: float = 0.0
    change_30d: float | None = None
    ath: float | None = None
    ath_change_pct: float | None = None

    # Calculated values
    current_value: float = 0.0
    daily_gain: float = 0.0
    accumulated_gain: float = 0.0
    days_staked: int = 0
    days_until_available: int = 0
    days_until_reward: int | None = None

    # Signals
    signals: list[Signal] = field(default_factory=list)
    level: AlertLevel = AlertLevel.OK

    # OHLC for sparkline
    ohlc: list[list[float]] = field(default_factory=list)


@dataclass
class SavingsAnalysis:
    """Analysis result for a savings account."""

    account_id: str
    name: str
    bank: str

    # Account data
    balance: float = 0.0
    apy: float = 0.0
    account_type: str = "remunerada"
    start_date: str = ""

    # Calculated values
    monthly_interest: float = 0.0
    yearly_interest: float = 0.0
    days_until_payment: int = 0
    payment_day: int = 25

    # Level (always OK for savings)
    level: AlertLevel = AlertLevel.OK


@dataclass
class ScheduledAlert:
    """A scheduled alert for future action."""

    alert_id: str
    date: str  # ISO format YYYY-MM-DD
    action: str  # "sell_crypto", "stop_etf", "modify_etf", "review" (NO buy_etf - automated)
    symbol: str
    title: str
    description: str
    priority: str = "medium"  # "high", "medium", "low"
    recurring: str | None = None  # "monthly", "weekly", None
    triggered: bool = False


@dataclass
class PortfolioSummary:
    """Summary of the entire portfolio."""

    # ETF totals
    etf_total_value: float = 0.0
    etf_total_invested: float = 0.0
    etf_total_gain_loss: float = 0.0
    etf_total_gain_loss_pct: float = 0.0
    etf_analysis: list[ETFAnalysis] = field(default_factory=list)
    etf_level: AlertLevel = AlertLevel.OK

    # Crypto totals
    crypto_total_value: float = 0.0
    crypto_total_daily_gain: float = 0.0
    crypto_analysis: list[CryptoAnalysis] = field(default_factory=list)
    crypto_level: AlertLevel = AlertLevel.OK
    crypto_fear_greed: int | None = None
    crypto_fear_greed_label: str | None = None

    # Savings totals
    savings_total_balance: float = 0.0
    savings_yearly_interest: float = 0.0
    savings_analysis: list[SavingsAnalysis] = field(default_factory=list)

    # Scheduled alerts
    upcoming_alerts: list[ScheduledAlert] = field(default_factory=list)

    # Plan info
    phase: str = ""
    phase_months_remaining: int | None = None

    # Timestamps
    etf_last_update: datetime | None = None
    crypto_last_update: datetime | None = None
    savings_last_update: datetime | None = None


@dataclass
class MonitorState:
    """Persisted state of the monitor."""

    summary: PortfolioSummary = field(default_factory=PortfolioSummary)
    last_etf_run: datetime | None = None
    last_crypto_run: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "last_etf_run": self.last_etf_run.isoformat()
            if self.last_etf_run
            else None,
            "last_crypto_run": self.last_crypto_run.isoformat()
            if self.last_crypto_run
            else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MonitorState":
        """Create from dict."""
        state = cls()
        if data.get("last_etf_run"):
            state.last_etf_run = datetime.fromisoformat(data["last_etf_run"])
        if data.get("last_crypto_run"):
            state.last_crypto_run = datetime.fromisoformat(data["last_crypto_run"])
        return state
