"""
Portfolio Monitor — Email Notifier.

Sends alerts via email when monitors detect WARN or DANGER signals.
Uses the same SMTP credentials as the dashboard auth system.

Configuration via environment variables:
  - SMTP_USER: Gmail address (e.g., acmlsn@gmail.com)
  - SMTP_PASSWORD: Gmail App Password
  - ALERT_EMAIL: Recipient address (defaults to SMTP_USER)
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import AlertLevel, CryptoAnalysis, ETFAnalysis

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", os.environ.get("AUTH_SMTP_USER", ""))
SMTP_PASSWORD = os.environ.get(
    "SMTP_PASSWORD", os.environ.get("AUTH_SMTP_PASSWORD", "")
)
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", SMTP_USER)


@dataclass
class NotificationResult:
    """Result of a notification attempt."""

    success: bool
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# HTML Templates
# ─────────────────────────────────────────────────────────────────────────────
def _format_price(value: float, decimals: int = 2) -> str:
    """Format a price with thousand separators."""
    if decimals == 0:
        return f"{int(value):,}€".replace(",", ".")
    return f"{value:,.{decimals}f}€".replace(",", ".")


def _level_color(level: str) -> str:
    """Return color for alert level."""
    return {
        "DANGER": "#dc3545",
        "WARN": "#ffc107",
        "INFO": "#17a2b8",
        "OK": "#28a745",
    }.get(level, "#6c757d")


def _level_emoji(level: str) -> str:
    """Return emoji for alert level."""
    return {
        "DANGER": "🔴",
        "WARN": "🟡",
        "INFO": "🔵",
        "OK": "🟢",
    }.get(level, "⚪")


def _build_html_summary(
    etf_results: list[ETFAnalysis],
    crypto_results: list[CryptoAnalysis],
    savings_results: list,
    overall_level: AlertLevel,
    fear_greed: int | None,
) -> str:
    """Build HTML email body for portfolio summary."""
    from models import AlertLevel

    level_color = _level_color(overall_level.name)
    level_emoji = "🔴" if overall_level == AlertLevel.DANGER else "🟡"
    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Calculate totals
    total_etf = sum(e.current_value for e in etf_results)
    total_crypto = sum(c.current_value for c in crypto_results)
    total_savings = sum(s.balance for s in savings_results) if savings_results else 0
    total_portfolio = total_etf + total_crypto + total_savings

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .header {{ background: {level_color}; color: white; padding: 20px; }}
        .header h1 {{ margin: 0; font-size: 20px; }}
        .header .date {{ opacity: 0.9; font-size: 14px; margin-top: 5px; }}
        .content {{ padding: 20px; }}
        .section {{ margin-bottom: 25px; }}
        .section-title {{ font-size: 16px; font-weight: 600; color: #333; margin-bottom: 12px; border-bottom: 2px solid #eee; padding-bottom: 8px; }}
        .item {{ padding: 10px; background: #f8f9fa; border-radius: 6px; margin-bottom: 8px; }}
        .item-header {{ display: flex; justify-content: space-between; align-items: center; }}
        .item-name {{ font-weight: 500; }}
        .item-value {{ font-weight: 600; }}
        .item-change {{ font-size: 13px; color: #666; }}
        .item-change.positive {{ color: #28a745; }}
        .item-change.negative {{ color: #dc3545; }}
        .signal {{ font-size: 13px; color: #666; margin-top: 5px; padding-left: 10px; border-left: 3px solid {level_color}; }}
        .totals {{ background: #e9ecef; padding: 15px; border-radius: 6px; }}
        .totals-row {{ display: flex; justify-content: space-between; margin-bottom: 8px; }}
        .totals-row:last-child {{ margin-bottom: 0; font-weight: 600; font-size: 18px; }}
        .footer {{ padding: 15px 20px; background: #f8f9fa; text-align: center; font-size: 13px; color: #666; }}
        .footer a {{ color: #007bff; text-decoration: none; }}
        .fear-greed {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 13px; font-weight: 500; }}
        .fear-greed.low {{ background: #d4edda; color: #155724; }}
        .fear-greed.medium {{ background: #fff3cd; color: #856404; }}
        .fear-greed.high {{ background: #f8d7da; color: #721c24; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{level_emoji} Portfolio Monitor — Alertas Detectadas</h1>
            <div class="date">{date_str}</div>
        </div>
        <div class="content">
"""

    # ETF Section
    etf_alerts = [
        e for e in etf_results if e.level in (AlertLevel.WARN, AlertLevel.DANGER)
    ]
    if etf_alerts:
        html += """
            <div class="section">
                <div class="section-title">📈 ETFs</div>
"""
        for etf in etf_alerts:
            change_class = "positive" if etf.gain_loss_pct >= 0 else "negative"
            emoji = _level_emoji(etf.level.name)
            html += f"""
                <div class="item">
                    <div class="item-header">
                        <span class="item-name">{emoji} {etf.name}</span>
                        <span class="item-value">{_format_price(etf.current_value)}</span>
                    </div>
                    <div class="item-change {change_class}">
                        Precio: {_format_price(etf.price)} · P/L: {etf.gain_loss_pct:+.1%}
                    </div>
"""
            danger_signals = [s for s in etf.signals if s.level in ("DANGER", "WARN")]
            if danger_signals:
                html += f"""
                    <div class="signal">{danger_signals[0].body[:100]}</div>
"""
            html += """
                </div>
"""
        html += """
            </div>
"""

    # Crypto Section
    crypto_alerts = [
        c for c in crypto_results if c.level in (AlertLevel.WARN, AlertLevel.DANGER)
    ]
    if crypto_alerts or fear_greed is not None:
        html += """
            <div class="section">
                <div class="section-title">🪙 Crypto</div>
"""
        if fear_greed is not None:
            fg_class = (
                "low" if fear_greed < 30 else "medium" if fear_greed < 60 else "high"
            )
            fg_label = (
                "Fear" if fear_greed < 30 else "Neutral" if fear_greed < 60 else "Greed"
            )
            html += f"""
                <div style="margin-bottom: 12px;">
                    Fear & Greed Index: <span class="fear-greed {fg_class}">{fear_greed} ({fg_label})</span>
                </div>
"""
        for crypto in crypto_alerts:
            change_class = "positive" if crypto.change_24h >= 0 else "negative"
            emoji = _level_emoji(crypto.level.name)
            html += f"""
                <div class="item">
                    <div class="item-header">
                        <span class="item-name">{emoji} {crypto.symbol} ({crypto.name})</span>
                        <span class="item-value">{_format_price(crypto.current_value)}</span>
                    </div>
                    <div class="item-change {change_class}">
                        Precio: {_format_price(crypto.price_eur)} · 24h: {crypto.change_24h:+.1f}%
                    </div>
"""
            danger_signals = [
                s for s in crypto.signals if s.level in ("DANGER", "WARN")
            ]
            if danger_signals:
                html += f"""
                    <div class="signal">{danger_signals[0].body[:100]}</div>
"""
            html += """
                </div>
"""
        html += """
            </div>
"""

    # Totals Section
    html += f"""
            <div class="section">
                <div class="section-title">💼 Resumen</div>
                <div class="totals">
                    <div class="totals-row">
                        <span>ETFs</span>
                        <span>{_format_price(total_etf)}</span>
                    </div>
                    <div class="totals-row">
                        <span>Crypto</span>
                        <span>{_format_price(total_crypto)}</span>
                    </div>
                    <div class="totals-row">
                        <span>Ahorros</span>
                        <span>{_format_price(total_savings)}</span>
                    </div>
                    <div class="totals-row">
                        <span>Total Portfolio</span>
                        <span>{_format_price(total_portfolio)}</span>
                    </div>
                </div>
            </div>
"""

    # Footer
    html += """
        </div>
        <div class="footer">
            <a href="https://raspberrypi.tailaa37cd.ts.net/smart-home/portfolio">Ver Dashboard Completo →</a>
        </div>
    </div>
</body>
</html>
"""
    return html


def _build_html_scheduled_alert(alert) -> str:
    """Build HTML email for a scheduled alert."""
    priority_color = {
        "high": "#dc3545",
        "medium": "#ffc107",
        "low": "#17a2b8",
    }.get(alert.priority, "#6c757d")

    priority_emoji = {
        "high": "🔴",
        "medium": "🟡",
        "low": "🔵",
    }.get(alert.priority, "⚪")

    action_emoji = {
        "sell_crypto": "💰",
        "buy_etf": "📈",
        "review": "👀",
    }.get(alert.action, "📋")

    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 500px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .header {{ background: {priority_color}; color: white; padding: 20px; }}
        .header h1 {{ margin: 0; font-size: 18px; }}
        .header .date {{ opacity: 0.9; font-size: 13px; margin-top: 5px; }}
        .content {{ padding: 20px; }}
        .title {{ font-size: 20px; font-weight: 600; margin-bottom: 15px; }}
        .description {{ color: #333; line-height: 1.6; margin-bottom: 20px; }}
        .meta {{ background: #f8f9fa; padding: 12px; border-radius: 6px; }}
        .meta-row {{ display: flex; justify-content: space-between; margin-bottom: 6px; }}
        .meta-row:last-child {{ margin-bottom: 0; }}
        .meta-label {{ color: #666; }}
        .footer {{ padding: 15px 20px; background: #f8f9fa; text-align: center; font-size: 13px; color: #666; }}
        .footer a {{ color: #007bff; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{priority_emoji} Alerta Programada</h1>
            <div class="date">{date_str}</div>
        </div>
        <div class="content">
            <div class="title">{action_emoji} {alert.title}</div>
            <div class="description">{alert.description}</div>
            <div class="meta">
                <div class="meta-row">
                    <span class="meta-label">📅 Fecha</span>
                    <span>{alert.date}</span>
                </div>
                <div class="meta-row">
                    <span class="meta-label">🏷️ Activo</span>
                    <span>{alert.symbol}</span>
                </div>
                <div class="meta-row">
                    <span class="meta-label">⚡ Prioridad</span>
                    <span>{alert.priority.capitalize()}</span>
                </div>
            </div>
        </div>
        <div class="footer">
            <a href="https://raspberrypi.tailaa37cd.ts.net/smart-home/portfolio">Ver Dashboard →</a>
        </div>
    </div>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Email Notifier
# ─────────────────────────────────────────────────────────────────────────────
class EmailNotifier:
    """
    Sends portfolio alerts via email.

    Only sends notifications when there are WARN or DANGER signals.
    Uses Gmail SMTP with TLS (same config as dashboard auth).
    """

    def __init__(
        self,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        recipient: str | None = None,
    ) -> None:
        self._smtp_user = smtp_user or SMTP_USER
        self._smtp_password = smtp_password or SMTP_PASSWORD
        self._recipient = recipient or ALERT_EMAIL or self._smtp_user
        self._enabled = bool(self._smtp_user and self._smtp_password)

        if self._enabled:
            logger.info("[email] Notifier initialized (recipient: %s)", self._recipient)
        else:
            logger.warning(
                "[email] Notifier disabled — missing SMTP_USER or SMTP_PASSWORD"
            )

    @property
    def enabled(self) -> bool:
        """Return True if notifications are enabled."""
        return self._enabled

    def _send(self, subject: str, html_body: str) -> NotificationResult:
        """Send an HTML email."""
        if not self._enabled:
            return NotificationResult(
                success=False,
                message="Notifications disabled — missing credentials",
            )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._smtp_user
        msg["To"] = self._recipient
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.starttls(context=ctx)
                server.login(self._smtp_user, self._smtp_password)
                server.sendmail(self._smtp_user, self._recipient, msg.as_bytes())

            logger.info("[email] Alert sent to %s", self._recipient)
            return NotificationResult(success=True, message="Email sent")

        except smtplib.SMTPAuthenticationError as e:
            logger.error("[email] SMTP authentication error: %s", e)
            return NotificationResult(success=False, message=f"Auth error: {e}")
        except smtplib.SMTPException as e:
            logger.error("[email] SMTP error: %s", e)
            return NotificationResult(success=False, message=f"SMTP error: {e}")
        except (ConnectionError, TimeoutError) as e:
            logger.error("[email] Connection error: %s", e)
            return NotificationResult(success=False, message=f"Connection error: {e}")
        except Exception as e:
            logger.error("[email] Unexpected error: %s", e)
            return NotificationResult(success=False, message=str(e))

    def send_summary_alert(
        self,
        etf_results: list[ETFAnalysis],
        crypto_results: list[CryptoAnalysis],
        overall_level: AlertLevel,
        fear_greed: int | None = None,
        savings_results: list | None = None,
    ) -> NotificationResult:
        """
        Send a summary alert if there are WARN or DANGER signals.

        This is the main entry point — called after monitors run.
        Only sends if overall_level is WARN or DANGER.
        """
        from models import AlertLevel

        if overall_level not in (AlertLevel.WARN, AlertLevel.DANGER):
            logger.debug("[email] No alert needed — level is %s", overall_level.name)
            return NotificationResult(
                success=True,
                message="No alert needed — all OK",
            )

        level_emoji = "🔴" if overall_level == AlertLevel.DANGER else "🟡"
        subject = f"{level_emoji} Portfolio Monitor — Alertas Detectadas"

        html = _build_html_summary(
            etf_results,
            crypto_results,
            savings_results or [],
            overall_level,
            fear_greed,
        )

        return self._send(subject, html)

    def send_scheduled_alert(self, alert) -> NotificationResult:
        """Send a notification for a scheduled alert."""
        priority_emoji = {
            "high": "🔴",
            "medium": "🟡",
            "low": "🔵",
        }.get(alert.priority, "📋")

        subject = f"{priority_emoji} Alerta: {alert.title}"
        html = _build_html_scheduled_alert(alert)

        return self._send(subject, html)

    def send_test(self) -> NotificationResult:
        """Send a test email to verify configuration."""
        subject = "✅ Portfolio Monitor — Test"
        html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: sans-serif; padding: 20px;">
    <h2>✅ Email Notifications Working</h2>
    <p>Portfolio Monitor email notifications are configured correctly.</p>
    <p><small>{datetime.now().strftime("%d/%m/%Y %H:%M")}</small></p>
</body>
</html>
"""
        return self._send(subject, html)
