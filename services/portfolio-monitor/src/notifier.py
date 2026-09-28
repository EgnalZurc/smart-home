"""
Portfolio Monitor — Telegram Notifier.

Sends alerts to Telegram when monitors detect WARN or DANGER signals.
Uses the same bot as casita-suenos for unified notifications.

Configuration via environment variables:
  - TELEGRAM_BOT_TOKEN: Bot token from @BotFather
  - TELEGRAM_CHAT_ID: Default chat ID (fallback if no DB)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from models import AlertLevel, CryptoAnalysis, ETFAnalysis

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


@dataclass
class NotificationResult:
    """Result of a notification attempt."""
    success: bool
    message: str
    chat_ids_notified: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Message Formatting
# ─────────────────────────────────────────────────────────────────────────────
def _escape_md(text: str) -> str:
    """Escape Markdown special characters for Telegram."""
    for ch in ["*", "_", "`", "["]:
        text = text.replace(ch, "\\" + ch)
    return text


def _format_price(value: float, decimals: int = 2) -> str:
    """Format a price with thousand separators."""
    if decimals == 0:
        return f"{int(value):,}€".replace(",", ".")
    return f"{value:,.{decimals}f}€".replace(",", ".")


def _level_emoji(level: str) -> str:
    """Return emoji for alert level."""
    return {
        "DANGER": "🔴",
        "WARN": "🟡",
        "INFO": "🔵",
        "OK": "🟢",
    }.get(level, "⚪")


def _format_etf_alert(analysis: ETFAnalysis) -> str:
    """Format an ETF alert message."""
    lines = [
        f"📈 *ETF Alert — {analysis.name}*",
        f"_{datetime.now().strftime('%d/%m/%Y %H:%M')}_",
        "",
        f"💰 Precio: {_format_price(analysis.price)}",
        f"📊 Valor cartera: {_format_price(analysis.current_value)}",
    ]
    
    if analysis.gain_loss_pct:
        emoji = "📈" if analysis.gain_loss_pct >= 0 else "📉"
        lines.append(f"{emoji} P/L: {analysis.gain_loss_pct:+.1%} ({_format_price(analysis.gain_loss_eur)})")
    
    # Add signals
    if analysis.signals:
        lines.append("")
        lines.append("*Señales:*")
        for signal in analysis.signals:
            if signal.level in ("DANGER", "WARN"):
                emoji = _level_emoji(signal.level)
                body = _escape_md(signal.body)
                lines.append(f"  {emoji} {body}")
    
    # Add recommendation
    if analysis.recommendation:
        lines.append("")
        lines.append(f"💡 {_escape_md(analysis.recommendation.body)}")
    
    return "\n".join(lines)


def _format_crypto_alert(analysis: CryptoAnalysis, fear_greed: int | None) -> str:
    """Format a crypto alert message."""
    lines = [
        f"🪙 *Crypto Alert — {analysis.name}*",
        f"_{datetime.now().strftime('%d/%m/%Y %H:%M')}_",
        "",
        f"💰 Precio: {_format_price(analysis.price_eur)}",
        f"📊 Valor: {_format_price(analysis.current_value)}",
        f"📈 Staking: {analysis.apy:.2f}% APY",
    ]
    
    if fear_greed is not None:
        fg_emoji = "🟢" if fear_greed < 30 else "🟡" if fear_greed < 60 else "🔴"
        lines.append(f"{fg_emoji} Fear & Greed: {fear_greed}")
    
    # Add signals
    if analysis.signals:
        lines.append("")
        lines.append("*Señales:*")
        for signal in analysis.signals:
            if signal.level in ("DANGER", "WARN"):
                emoji = _level_emoji(signal.level)
                body = _escape_md(signal.body)
                lines.append(f"  {emoji} {body}")
    
    return "\n".join(lines)


def _format_summary_alert(
    etf_results: list[ETFAnalysis],
    crypto_results: list[CryptoAnalysis],
    overall_level: AlertLevel,
    fear_greed: int | None,
) -> str:
    """Format a summary alert when there are warnings/dangers."""
    from models import AlertLevel
    
    level_emoji = "🔴" if overall_level == AlertLevel.DANGER else "🟡"
    
    lines = [
        f"{level_emoji} *Portfolio Monitor — Alertas Detectadas*",
        f"_{datetime.now().strftime('%d/%m/%Y %H:%M')}_",
        "",
    ]
    
    # ETF section
    etf_alerts = [e for e in etf_results if e.level in (AlertLevel.WARN, AlertLevel.DANGER)]
    if etf_alerts:
        lines.append("*📈 ETFs:*")
        for etf in etf_alerts:
            emoji = _level_emoji(etf.level.name)
            lines.append(f"  {emoji} {etf.name}: {_format_price(etf.price)} ({etf.gain_loss_pct:+.1%})")
            # Add top signal
            danger_signals = [s for s in etf.signals if s.level in ("DANGER", "WARN")]
            if danger_signals:
                lines.append(f"      → {_escape_md(danger_signals[0].body[:80])}")
        lines.append("")
    
    # Crypto section
    crypto_alerts = [c for c in crypto_results if c.level in (AlertLevel.WARN, AlertLevel.DANGER)]
    if crypto_alerts:
        lines.append("*🪙 Crypto:*")
        if fear_greed is not None:
            fg_emoji = "🟢" if fear_greed < 30 else "🟡" if fear_greed < 60 else "🔴"
            lines.append(f"  {fg_emoji} Fear & Greed: {fear_greed}")
        for crypto in crypto_alerts:
            emoji = _level_emoji(crypto.level.name)
            lines.append(f"  {emoji} {crypto.symbol}: {_format_price(crypto.price_eur)} ({crypto.change_24h:+.1f}% 24h)")
            danger_signals = [s for s in crypto.signals if s.level in ("DANGER", "WARN")]
            if danger_signals:
                lines.append(f"      → {_escape_md(danger_signals[0].body[:80])}")
        lines.append("")
    
    # Totals
    total_etf = sum(e.current_value for e in etf_results)
    total_crypto = sum(c.current_value for c in crypto_results)
    lines.append(f"💼 *Total Portfolio:* {_format_price(total_etf + total_crypto, 0)}")
    lines.append("")
    lines.append("🔗 Dashboard: /smart-home/portfolio")
    
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Telegram Notifier
# ─────────────────────────────────────────────────────────────────────────────
class TelegramNotifier:
    """
    Sends portfolio alerts to Telegram.
    
    Only sends notifications when there are WARN or DANGER signals.
    """
    
    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        self._token = bot_token or TELEGRAM_BOT_TOKEN
        self._chat_id = chat_id or TELEGRAM_CHAT_ID
        self._enabled = bool(self._token and self._chat_id)
        
        if self._enabled:
            logger.info("[telegram] Notifier initialized (chat_id: %s)", self._chat_id[:6] + "...")
        else:
            logger.warning("[telegram] Notifier disabled — missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    
    @property
    def enabled(self) -> bool:
        """Return True if notifications are enabled."""
        return self._enabled
    
    def _send(self, text: str) -> NotificationResult:
        """Send a message to Telegram."""
        if not self._enabled:
            return NotificationResult(
                success=False,
                message="Notifications disabled — missing credentials",
            )
        
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        
        try:
            resp = httpx.post(
                url,
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=15.0,
            )
            
            data = resp.json()
            if data.get("ok"):
                logger.info("[telegram] Message sent successfully")
                return NotificationResult(
                    success=True,
                    message="Message sent",
                    chat_ids_notified=1,
                )
            else:
                error = data.get("description", "Unknown error")
                logger.error("[telegram] API error: %s", error)
                return NotificationResult(
                    success=False,
                    message=f"API error: {error}",
                )
                
        except httpx.TimeoutException:
            logger.error("[telegram] Request timeout")
            return NotificationResult(success=False, message="Request timeout")
        except Exception as e:
            logger.error("[telegram] Error sending message: %s", e)
            return NotificationResult(success=False, message=str(e))
    
    def send_etf_alert(self, analysis: ETFAnalysis) -> NotificationResult:
        """Send an alert for a single ETF."""
        text = _format_etf_alert(analysis)
        return self._send(text)
    
    def send_crypto_alert(
        self,
        analysis: CryptoAnalysis,
        fear_greed: int | None = None,
    ) -> NotificationResult:
        """Send an alert for a single crypto position."""
        text = _format_crypto_alert(analysis, fear_greed)
        return self._send(text)
    
    def send_summary_alert(
        self,
        etf_results: list[ETFAnalysis],
        crypto_results: list[CryptoAnalysis],
        overall_level: AlertLevel,
        fear_greed: int | None = None,
    ) -> NotificationResult:
        """
        Send a summary alert if there are WARN or DANGER signals.
        
        This is the main entry point — called after monitors run.
        Only sends if overall_level is WARN or DANGER.
        """
        from models import AlertLevel
        
        if overall_level not in (AlertLevel.WARN, AlertLevel.DANGER):
            logger.debug("[telegram] No alert needed — level is %s", overall_level.name)
            return NotificationResult(
                success=True,
                message="No alert needed — all OK",
            )
        
        text = _format_summary_alert(etf_results, crypto_results, overall_level, fear_greed)
        return self._send(text)
    
    def send_test(self) -> NotificationResult:
        """Send a test message to verify configuration."""
        text = (
            "✅ *Portfolio Monitor — Test*\n"
            f"_{datetime.now().strftime('%d/%m/%Y %H:%M')}_\n\n"
            "Telegram notifications are working correctly."
        )
        return self._send(text)
