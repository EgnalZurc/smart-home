"""
Notificador Telegram para Casita Sueños.

Usa python-telegram-bot en modo síncrono (Bot.send_message sin asyncio)
para ser compatible con el patrón de threading del proyecto.

Mensajes enviados:
  - Alerta inmediata: anuncio nuevo ≥ 45 puntos
  - Alerta bajada de precio: cualquier bajada detectada
  - Resumen semanal: top 5 de la semana
"""

from __future__ import annotations

import logging
from datetime import datetime

import telegram

from models import PriceEvent, ScoredProperty

logger = logging.getLogger(__name__)

_SCORE_EMOJI = {
    range(60, 76): "🏆",
    range(55, 60): "⭐⭐⭐",
    range(50, 55): "⭐⭐",
    range(45, 50): "⭐",
}

_PISCINA_EMOJI = {
    "propia":      "🏊 piscina propia",
    "espacio":     "🏊 espacio para piscina",
    "comunitaria": "🏊 piscina comunitaria",
    "ninguna":     "",
}


def _score_emoji(score: float) -> str:
    for r, emoji in _SCORE_EMOJI.items():
        if int(score) in r:
            return emoji
    return ""


def _format_price(price: int) -> str:
    return f"{price:,}€".replace(",", ".")


def _format_new_property_alert(scored: ScoredProperty) -> str:
    prop = scored.prop
    s = scored.score
    emoji = _score_emoji(scored.total_score)
    piscina = _PISCINA_EMOJI.get(prop.piscina.value, "")

    lines = [
        f"{emoji} *Nueva vivienda — {scored.total_score:.1f}/75 pts*",
        f"📍 *{scored.zone.name}*",
        f"💰 *{_format_price(prop.price)}*",
        "",
    ]

    details = []
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

    # Desglose de puntuación compacto
    lines.append("📊 *Puntuación*")
    lines.append(
        f"  P3 Madrid: {s.p3_distance:.0f}  "
        f"P4 Playa: {s.p4_beach:.0f}  "
        f"P5 Nat: {s.p5_pools:.0f}"
    )
    lines.append(
        f"  P6 Super: {s.p6_supermarket:.0f}  "
        f"P7 CS: {s.p7_health:.0f}  "
        f"P8 Hosp: {s.p8_hospital:.0f}"
    )
    lines.append(
        f"  P9 Precio: {s.p9_price:.0f}  "
        f"P10 Incendio: {s.p10_fire:.0f}"
    )
    lines.append("")
    lines.append(f"🔗 {prop.url}")

    return "\n".join(lines)


def _format_price_drop_alert(event: PriceEvent, title: str, url: str, zone_name: str) -> str:
    direction = "📉 *Bajada de precio*" if event.delta < 0 else "📈 *Subida de precio*"
    lines = [
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
    lines = [
        "📋 *Resumen semanal — Casita Sueños*",
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

        lines.append(f"*{i}. {score:.1f}pts* — {price}")
        lines.append(f"   📍 {prop.get('zone_id', '').replace('_', ' ')}")
        if details:
            lines.append(f"   {details}")
        lines.append(f"   {prop['url']}")
        lines.append("")

    return "\n".join(lines)


class TelegramNotifier:
    """
    Envía notificaciones a Telegram.
    Usa python-telegram-bot en modo síncrono compatible con threading.
    """

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot = telegram.Bot(token=bot_token)
        self._chat_id = chat_id
        logger.info("[telegram] Notificador inicializado para chat %s", chat_id)

    def _send(self, text: str) -> bool:
        """Envía un mensaje. Devuelve True si tuvo éxito."""
        try:
            import asyncio
            asyncio.run(
                self._bot.send_message(
                    chat_id=self._chat_id,
                    text=text,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
            )
            return True
        except Exception as e:
            logger.error("[telegram] Error enviando mensaje: %s", e)
            return False

    def send_new_property_alert(self, scored: ScoredProperty) -> bool:
        """Alerta de nueva propiedad que supera el umbral de 45 puntos."""
        text = _format_new_property_alert(scored)
        success = self._send(text)
        if success:
            logger.info(
                "[telegram] Alerta enviada: %s — %.1f pts",
                scored.prop.unique_id, scored.total_score,
            )
        return success

    def send_price_drop_alert(
        self,
        event: PriceEvent,
        title: str,
        url: str,
        zone_name: str,
    ) -> bool:
        """Alerta de bajada (o subida) de precio."""
        text = _format_price_drop_alert(event, title, url, zone_name)
        success = self._send(text)
        if success:
            logger.info(
                "[telegram] Alerta precio enviada: %s %+.1f%%",
                event.property_uid, event.delta_pct,
            )
        return success

    def send_weekly_summary(self, top_properties: list[dict]) -> bool:
        """Resumen semanal con el top de propiedades."""
        text = _format_weekly_summary(top_properties)
        success = self._send(text)
        if success:
            logger.info("[telegram] Resumen semanal enviado (%d propiedades)", len(top_properties))
        return success

    def send_status(self, message: str) -> bool:
        """Mensaje de estado/diagnóstico."""
        return self._send(f"ℹ️ {message}")
