"""
Parser de alertas de Idealista recibidas por Gmail.
Autenticacion: IMAP con App Password de Google.

Flujo:
  1. Conectar a Gmail via IMAP
  2. Buscar emails de noreply@idealista.com en INBOX, Papelera y Todos
     Sin filtro UNSEEN — procesa todos independientemente del estado de lectura
  3. Extraer URLs y datos básicos (precio, hab, m2, título, zona) de cada email
  4. Devolver lista de alertas + conexión IMAP abierta
  5. El llamador elimina los emails después de procesar (INBOX + Papelera)
"""
from __future__ import annotations
import email
import imaplib
import logging
import re
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_IDEALISTA_SENDER = "noreply@idealista.com"
_IMAP_HOST  = "imap.gmail.com"
_IMAP_PORT  = 993

# Carpetas donde buscar — en orden de prioridad
# Los usuarios pueden mover los emails de Idealista a la papelera manualmente
_SEARCH_FOLDERS = [
    "INBOX",
    "[Gmail]/Papelera",   # Gmail en español
    "Trash",              # Gmail en inglés / otros clientes
    "[Gmail]/Todos",      # Todos los emails como fallback
]

# URL de anuncio: https://www.idealista.com/inmueble/12345678/
_URL_PATTERN   = re.compile(r"https://www\.idealista\.com/inmueble/(\d+)/?", re.IGNORECASE)
_PRICE_PATTERN = re.compile(r"([\d]{2,3}[\.\s]?\d{3})\s*\u20ac")
_ROOMS_PATTERN = re.compile(r"(\d+)\s+hab", re.IGNORECASE)
_SIZE_PATTERN  = re.compile(r"([\d]+[,.]?\d*)\s*m[\u00b22]", re.IGNORECASE)
_TITLE_PATTERN = re.compile(r"(Casa\s+o\s+chalet|Chalet|Casa|Piso|Apartamento|Finca)[^<\n]{5,80}", re.IGNORECASE)
_ZONE_PATTERN  = re.compile(r"(?:chalets|casas|pisos)\s+en\s+([A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00d1][a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00d1\s]+)", re.IGNORECASE)


@dataclass
class IdealistaAlert:
    url: str
    property_id: str
    email_id: str          # IMAP message ID (para eliminar después)
    folder: str            # Carpeta donde se encontró
    price: int | None = None
    rooms: int | None = None
    size_m2: float | None = None
    title: str = ""
    location_hint: str = ""  # texto de zona del email para inferir zona


def _connect_imap(email_address: str, app_password: str) -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
    imap.login(email_address, app_password)
    logger.info("[gmail] Conectado a IMAP como %s", email_address)
    return imap


def _parse_price(text: str) -> int | None:
    m = _PRICE_PATTERN.search(text)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(" ", "").replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_rooms(text: str) -> int | None:
    m = _ROOMS_PATTERN.search(text)
    return int(m.group(1)) if m else None


def _parse_size(text: str) -> float | None:
    m = _SIZE_PATTERN.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _get_body(msg: email.message.Message) -> str:
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                try:
                    parts.append(part.get_payload(decode=True).decode("utf-8", errors="ignore"))
                except Exception:
                    pass
    else:
        try:
            parts.append(msg.get_payload(decode=True).decode("utf-8", errors="ignore"))
        except Exception:
            parts.append(str(msg.get_payload()))
    return "\n".join(parts)


def _extract_alerts(msg: email.message.Message, msg_id: str, folder: str) -> list[IdealistaAlert]:
    body = _get_body(msg)
    alerts: list[IdealistaAlert] = []
    seen: set[str] = set()
    location_hints = [m.group(1).strip() for m in _ZONE_PATTERN.finditer(body)]

    for match in _URL_PATTERN.finditer(body):
        pid = match.group(1)
        if pid in seen:
            continue
        seen.add(pid)
        url = f"https://www.idealista.com/inmueble/{pid}/"
        start = max(0, match.start() - 300)
        end   = min(len(body), match.end() + 300)
        ctx   = body[start:end]

        title_m = _TITLE_PATTERN.search(ctx)
        loc_hint = location_hints[0] if location_hints else ""
        if len(location_hints) > 1:
            for hint in location_hints:
                if hint.lower() in ctx.lower():
                    loc_hint = hint
                    break

        alerts.append(IdealistaAlert(
            url=url,
            property_id=pid,
            email_id=msg_id,
            folder=folder,
            price=_parse_price(ctx),
            rooms=_parse_rooms(ctx),
            size_m2=_parse_size(ctx),
            title=title_m.group(0).strip() if title_m else "",
            location_hint=loc_hint,
        ))
    return alerts


def fetch_new_alerts(
    email_address: str,
    app_password: str,
    lookback_days: int = 3,
) -> tuple[list[IdealistaAlert], imaplib.IMAP4_SSL | None]:
    """
    Busca emails de Idealista en múltiples carpetas (INBOX + Papelera + Todos).
    Sin filtro UNSEEN — procesa todos los emails del remitente en los últimos N días.

    Returns (lista_alertas, imap_connection) — la conexión queda abierta
    para que el llamador pueda eliminar los emails procesados.
    """
    try:
        imap = _connect_imap(email_address, app_password)
    except Exception as e:
        logger.error("[gmail] Error conectando a IMAP: %s", e)
        return [], None

    all_alerts: list[IdealistaAlert] = []
    seen_property_ids: set[str] = set()
    since_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
    search_criteria = f'(FROM "{_IDEALISTA_SENDER}" SINCE "{since_date}")'

    for folder in _SEARCH_FOLDERS:
        try:
            status, _ = imap.select(folder)
            if status != "OK":
                logger.debug("[gmail] Carpeta no disponible: %s", folder)
                continue

            _, message_numbers = imap.search(None, search_criteria)
            if not message_numbers or not message_numbers[0]:
                logger.debug("[gmail] Sin emails de Idealista en %s", folder)
                continue

            ids = message_numbers[0].split()
            logger.info("[gmail] %s: %d emails de Idealista encontrados", folder, len(ids))

            for msg_id in ids:
                try:
                    _, msg_data = imap.fetch(msg_id, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    alerts = _extract_alerts(msg, msg_id.decode(), folder)
                    # Deduplicar entre carpetas
                    for a in alerts:
                        if a.property_id not in seen_property_ids:
                            seen_property_ids.add(a.property_id)
                            all_alerts.append(a)
                    if alerts:
                        logger.info("[gmail] %s email %s: %d anuncios",
                                    folder, msg_id.decode(), len(alerts))
                except Exception as e:
                    logger.warning("[gmail] Error procesando email %s en %s: %s", msg_id, folder, e)

        except Exception as e:
            logger.warning("[gmail] Error accediendo a carpeta %s: %s", folder, e)

    logger.info("[gmail] Total anuncios unicos extraidos: %d", len(all_alerts))
    return all_alerts, imap


def delete_processed_emails(imap: imaplib.IMAP4_SSL, alerts: list[IdealistaAlert]) -> None:
    """
    Elimina los emails procesados de cada carpeta donde se encontraron.
    Agrupa por carpeta para minimizar operaciones IMAP.
    """
    if not imap or not alerts:
        return

    # Agrupar email_ids por carpeta
    by_folder: dict[str, list[str]] = {}
    for alert in alerts:
        by_folder.setdefault(alert.folder, []).append(alert.email_id)

    for folder, ids in by_folder.items():
        try:
            imap.select(folder)
            for msg_id in set(ids):
                imap.store(msg_id.encode(), "+FLAGS", "\\Deleted")
            imap.expunge()
            logger.info("[gmail] Eliminados %d emails de %s", len(set(ids)), folder)
        except Exception as e:
            logger.warning("[gmail] Error eliminando emails de %s: %s", folder, e)

    try:
        imap.close()
        imap.logout()
    except Exception:
        pass


# ── Compatibilidad con API legacy ──────────────────────────────────────────────
def fetch_new_alert_urls(
    email_address: str,
    app_password: str,
    lookback_minutes: int = 35,
    **kwargs,
) -> list[str]:
    """API legacy — devuelve solo URLs. Usar fetch_new_alerts() para la nueva API."""
    lookback_days = max(1, lookback_minutes // 60 + 1)
    alerts, imap = fetch_new_alerts(email_address, app_password, lookback_days)
    if imap:
        try:
            imap.close()
            imap.logout()
        except Exception:
            pass
    return [a.url for a in alerts]
