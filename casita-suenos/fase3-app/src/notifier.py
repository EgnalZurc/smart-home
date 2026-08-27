"""
Notificador Telegram para Casita Suenos.
Envia mensajes a TODOS los chats que hayan iniciado el bot (/start).
Los chat_ids se guardan en la BD (tabla telegram_chats).
Si no hay chats en BD, usa TELEGRAM_CHAT_ID del .env como fallback.
"""
from __future__ import annotations
import logging
from datetime import datetime
import telegram
from models import PriceEvent, ScoredProperty
logger = logging.getLogger(__name__)
_SCORE_EMOJI = {
    range(70, 85): "🏆",
    range(60, 70): "⭐⭐⭐",
    range(55, 60): "⭐⭐",
    range(50, 55): "⭐",
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


def _escape_md(text: str) -> str:
    """Escapa caracteres especiales de Markdown para evitar errores 400 en Telegram."""
    # Escapa los caracteres que abren entidades pero Telegram no puede cerrar
    for ch in ['*', '_', '`', '[']:
        text = text.replace(ch, '\\' + ch)
    return text

def _format_new_property_alert(scored: ScoredProperty) -> str:
    prop = scored.prop
    s = scored.score
    emoji = _score_emoji(scored.total_score)
    safe_title = _escape_md(prop.title or '')
    safe_zone  = _escape_md(scored.zone.name)
    piscina = _PISCINA_EMOJI.get(prop.piscina.value, "")
    lines = [
        f"{emoji} Nueva vivienda — {scored.total_score:.1f}/84 pts",
        f"📍 {safe_zone}",
        f"💰 {_format_price(prop.price)}",
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
    lines.append("📊 *Puntuacion*")
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
        f"P10 Incendio: {s.p10_fire:.0f}  "
        f"P11 Zona: {getattr(s, 'p11_preference', 0.0):.0f}"
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

    def __init__(self, bot_token: str, fallback_chat_id: str,
                 db=None) -> None:
        self._bot = telegram.Bot(token=bot_token)
        self._fallback_chat_id = fallback_chat_id
        self._db = db  # instancia de Database para leer chat_ids
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
            except Exception as e:
                logger.warning("[telegram] Error leyendo chat_ids de BD: %s", e)
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
        import httpx
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
                    logger.error("[telegram] API error para chat %s: %s", chat_id, resp.text[:120])
                    success = False
            except Exception as e:
                logger.error("[telegram] Error enviando a chat %s: %s", chat_id, e)
                success = False
        return success

    def register_chat(self, chat_id: str, username: str = "") -> None:
        """Registra un nuevo chat_id (llamado cuando el usuario hace /start)."""
        if self._db is not None:
            try:
                self._db.register_telegram_chat(chat_id, username)
                logger.info("[telegram] Chat registrado: %s (%s)", chat_id, username)
            except Exception as e:
                logger.error("[telegram] Error registrando chat %s: %s", chat_id, e)

    def send_new_property_alert(self, scored: ScoredProperty) -> bool:
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
        text = _format_price_drop_alert(event, title, url, zone_name)
        success = self._send(text)
        if success:
            logger.info(
                "[telegram] Alerta precio enviada: %s %+.1f%%",
                event.property_uid, event.delta_pct,
            )
        return success

    def send_weekly_summary(self, top_properties: list[dict]) -> bool:
        text = _format_weekly_summary(top_properties)
        success = self._send(text)
        if success:
            logger.info(
                "[telegram] Resumen semanal enviado (%d propiedades)", len(top_properties)
            )
        return success

    def send_status(self, message: str) -> bool:
        return self._send(f"ℹ️ {message}")
