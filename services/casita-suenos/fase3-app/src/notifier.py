"""
Notificador Telegram para Casita Suenos.
Envia mensajes a TODOS los chats que hayan iniciado el bot (/start).
Los chat_ids se guardan en la BD (tabla telegram_chats).
Si no hay chats en BD, usa TELEGRAM_CHAT_ID del .env como fallback.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Final

import httpx
import telegram
from models import PriceEvent, ScoreBreakdown, ScoredProperty

if TYPE_CHECKING:
    from database import Database

logger = logging.getLogger(__name__)


def _sanitize_telegram_error(exc: Exception) -> str:
    """Strip Telegram bot token from exception messages to prevent leaks in logs.

    Args:
        exc: The exception to sanitize.

    Returns:
        A sanitized error string with any bot token replaced by <REDACTED>.
    """
    msg = str(exc)
    # Telegram bot tokens look like: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
    # Match /bot<token>/ in URLs and standalone tokens
    sanitized = re.sub(r"/bot[0-9]+:[A-Za-z0-9_-]+/", "/bot<REDACTED>/", msg)
    sanitized = re.sub(r"\b[0-9]+:[A-Za-z0-9_-]{20,}\b", "<REDACTED>", sanitized)
    return sanitized


_SCORE_EMOJI: Final[dict[range, str]] = {
    range(70, 85): "🏆",
    range(60, 70): "⭐⭐⭐",
    range(55, 60): "⭐⭐",
    range(50, 55): "⭐",
}
_PISCINA_EMOJI: Final[dict[str, str]] = {
    "propia": "🏊 piscina propia",
    "espacio": "🏊 espacio para piscina",
    "comunitaria": "🏊 piscina comunitaria",
    "ninguna": "",
}


def _score_emoji(score: float) -> str:
    for r, emoji in _SCORE_EMOJI.items():
        if int(score) in r:
            return emoji
    return ""


def _format_price(price: int) -> str:
    return f"{price:,}€".replace(",", ".")


def _escape_md(text: str) -> str:
    """Escapa caracteres especiales de Markdown para evitar errores 400 en Telegram."""
    # Escapa los caracteres que abren entidades pero Telegram no puede cerrar
    for ch in ["*", "_", "`", "["]:
        text = text.replace(ch, "\\" + ch)
    return text


def _format_new_property_alert(scored: ScoredProperty) -> str:
    prop = scored.prop
    s = scored.score
    emoji = _score_emoji(scored.total_score)
    safe_zone = _escape_md(scored.zone.name)
    piscina = _PISCINA_EMOJI.get(prop.piscina.value, "")
    lines: list[str] = [
        f"{emoji} Nueva vivienda — {scored.total_score:.1f}/{ScoreBreakdown.MAX_SCORE:.0f} pts",
        f"📍 {safe_zone}",
        f"💰 {_format_price(prop.price)}",
        "",
    ]
    details: list[str] = []
    if prop.rooms:
        details.append(f"🛏 {prop.rooms} hab.")
    if prop.size_m2:
        details.append(f"📐 {prop.size_m2:.0f} m²")
    if prop.has_garage:
        details.append("🚗 garaje")
    if piscina:
        details.append(piscina)
    if details:
        lines.append("  ".join(details))
        lines.append("")
    lines.append("📊 *Puntuacion*")
    lines.append(
        f"  Madrid: {s.r12_madrid:.0f}  "
        f"Playa: {s.r13_beach:.0f}  "
        f"Nat: {s.r14_pools:.0f}"
    )
    lines.append(
        f"  Super: {s.r8_supermarket:.0f}  "
        f"CS: {s.r9_health:.0f}  "
        f"Hosp: {s.r10_hospital:.0f}"
    )
    lines.append(
        f"  Precio: {s.r7_price:.0f}  "
        f"Incendio: {s.r15_fire:.0f}  "
        f"Costa: {s.r17_coast:.0f}"
    )
    lines.append("")
    lines.append(f"🔗 {prop.url}")
    return "\n".join(lines)


def _format_high_scorer_alert(prop: dict) -> str:
    """Formatea la notificación de una propiedad que supera el umbral de score.

    Espera un dict con, al menos: ``title``, ``price``, ``score`` y ``url``.
    Campos opcionales (``zone``/``zone_id``, ``rooms``, ``size_m2``) se incluyen
    si están presentes.
    """
    score = float(prop.get("score") or 0.0)
    emoji = _score_emoji(score) or "🎯"
    title = _escape_md(str(prop.get("title") or "Nueva vivienda"))
    lines: list[str] = [
        f"{emoji} Propiedad destacada — {score:.1f}/{ScoreBreakdown.MAX_SCORE:.0f} pts",
        f"🏠 {title}",
    ]
    zone_name = prop.get("zone") or prop.get("zone_id")
    if zone_name:
        lines.append(f"📍 {_escape_md(str(zone_name).replace('_', ' '))}")
    price = prop.get("price")
    if price:
        lines.append(f"💰 {_format_price(int(price))}")

    details: list[str] = []
    if prop.get("rooms"):
        details.append(f"🛏 {prop['rooms']} hab.")
    if prop.get("size_m2"):
        details.append(f"📐 {float(prop['size_m2']):.0f} m²")
    if details:
        lines.append("  ".join(details))

    url = prop.get("url")
    if url:
        lines.append("")
        lines.append(f"🔗 {url}")
    return "\n".join(lines)


def _format_price_drop_alert(
    event: PriceEvent, title: str, url: str, zone_name: str
) -> str:
    direction = "📉 *Bajada de precio*" if event.delta < 0 else "📈 *Subida de precio*"
    lines: list[str] = [
        direction,
        f"📍 *{zone_name}*",
        f"🏠 {title}",
        "",
        f"  Antes: {_format_price(event.old_price)}",
        f"  Ahora: *{_format_price(event.new_price)}*",
        f"  Diferencia: {event.delta:+,}€ ({event.delta_pct:+.1f}%)".replace(",", "."),
        "",
        f"🔗 {url}",
    ]
    return "\n".join(lines)


def _format_weekly_summary(top_properties: list[dict]) -> str:
    lines: list[str] = [
        "📋 *Resumen semanal — Casita Suenos*",
        f"_{datetime.now().strftime('%d/%m/%Y')}_",
        "",
    ]
    if not top_properties:
        lines.append("Sin propiedades destacadas esta semana.")
        return "\n".join(lines)
    for i, prop in enumerate(top_properties[:5], 1):
        price = _format_price(prop["price"])
        score = prop["score_total"]
        rooms = f"{prop['rooms']} hab." if prop.get("rooms") else ""
        size = f"{prop['size_m2']:.0f}m²" if prop.get("size_m2") else ""
        details = "  ".join(filter(None, [rooms, size]))
        lines.append(f"{i}. {score:.1f}pts — {price}")
        lines.append(f"   📍 {prop.get('zone_id', '').replace('_', ' ')}")
        if details:
            lines.append(f"   {details}")
        lines.append(f"   {prop['url']}")
        lines.append("")
    return "\n".join(lines)


class TelegramNotifier:
    """
    Envia notificaciones a Telegram.
    Envia a TODOS los chats registrados (via /start).
    Fallback al chat_id del .env si no hay chats en BD.
    """

    def __init__(
        self, bot_token: str, fallback_chat_id: str, db: Database | None = None
    ) -> None:
        self._bot = telegram.Bot(token=bot_token)
        self._fallback_chat_id = fallback_chat_id
        self._db: Database | None = db  # instancia de Database para leer chat_ids
        logger.info(
            "[telegram] Notificador inicializado. fallback_chat=%s",
            fallback_chat_id,
        )

    def _get_chat_ids(self) -> list[str]:
        """Devuelve todos los chat_ids registrados. Fallback al .env."""
        if self._db is not None:
            try:
                ids = self._db.get_telegram_chat_ids()
                if ids:
                    return ids
            except (sqlite3.Error, AttributeError) as e:
                logger.warning(
                    "[telegram] Error leyendo chat_ids de BD: %s",
                    _sanitize_telegram_error(e),
                )
        # Fallback
        return [self._fallback_chat_id] if self._fallback_chat_id else []

    def _send(self, text: str) -> bool:
        """
        Envia un mensaje a todos los chats registrados.
        Usa httpx sincrono directo a la API REST de Telegram para evitar
        el Pool timeout de python-telegram-bot con muchos mensajes seguidos.
        """
        chat_ids = self._get_chat_ids()
        if not chat_ids:
            logger.warning("[telegram] Sin chat_ids configurados, mensaje no enviado.")
            return False

        # Usar httpx sincrono: mas robusto para envio masivo sin asyncio overhead

        token = self._bot.token
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        success = True
        for chat_id in chat_ids:
            try:
                resp = httpx.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "disable_web_page_preview": True,
                    },
                    timeout=15.0,
                )
                if not resp.json().get("ok"):
                    logger.error(
                        "[telegram] API error para chat %s: %s",
                        chat_id,
                        resp.text[:120],
                    )
                    success = False
            except (httpx.HTTPError, httpx.TimeoutException, OSError) as e:
                # Log sanitized error to prevent token leak in tracebacks
                logger.error(
                    "[telegram] Error enviando a chat %s: %s",
                    chat_id,
                    _sanitize_telegram_error(e),
                )
                success = False
        return success

    def register_chat(self, chat_id: str, username: str = "") -> None:
        """Registra un nuevo chat_id (llamado cuando el usuario hace /start)."""
        if self._db is not None:
            try:
                self._db.register_telegram_chat(chat_id, username)
                logger.info("[telegram] Chat registrado: %s (%s)", chat_id, username)
            except (sqlite3.Error, AttributeError) as e:
                logger.error(
                    "[telegram] Error registrando chat %s: %s",
                    chat_id,
                    _sanitize_telegram_error(e),
                )

    def send_new_property_alert(self, scored: ScoredProperty) -> bool:
        text = _format_new_property_alert(scored)
        success = self._send(text)
        if success:
            logger.info(
                "[telegram] Alerta enviada: %s — %.1f pts",
                scored.prop.unique_id,
                scored.total_score,
            )
        return success

    def notify_high_scorer(self, property_dict: dict) -> bool:
        """Notifica una propiedad que ha superado el umbral de score.

        ``property_dict`` debe contener al menos ``title``, ``price``, ``score``
        y ``url``. Devuelve True si el mensaje se envió a algún chat.
        """
        text = _format_high_scorer_alert(property_dict)
        success = self._send(text)
        if success:
            logger.info(
                "[telegram] High-scorer notificado: %s — %.1f pts",
                property_dict.get("url", "?"),
                float(property_dict.get("score") or 0.0),
            )
        return success

    def send_price_drop_alert(
        self,
        event: PriceEvent,
        title: str,
        url: str,
        zone_name: str,
    ) -> bool:
        text = _format_price_drop_alert(event, title, url, zone_name)
        success = self._send(text)
        if success:
            logger.info(
                "[telegram] Alerta precio enviada: %s %+.1f%%",
                event.property_uid,
                event.delta_pct,
            )
        return success

    def send_weekly_summary(self, top_properties: list[dict]) -> bool:
        text = _format_weekly_summary(top_properties)
        success = self._send(text)
        if success:
            logger.info(
                "[telegram] Resumen semanal enviado (%d propiedades)",
                len(top_properties),
            )
        return success

    def send_status(self, message: str) -> bool:
        return self._send(f"ℹ️ {message}")
