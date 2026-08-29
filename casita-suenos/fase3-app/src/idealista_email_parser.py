"""
Parser de alertas de Idealista recibidas por Gmail.
Autenticacion: IMAP con App Password de Google.
Flujo:
  1. Conectar a Gmail via IMAP con LOGIN
  2. Buscar emails de noreply@idealista.com en los ultimos N dias
     (sin filtro UNSEEN — el usuario puede haber abierto el email)
  3. Extraer URLs de anuncios y datos del email (precio, hab, m2, titulo)
  4. Devolver lista de (url, email_id, datos_basicos) para procesado posterior
  5. El llamador es responsable de eliminar los emails procesados
"""
from __future__ import annotations
import email
import imaplib
import logging
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_IDEALISTA_SENDER = "noreply@idealista.com"
_IMAP_HOST  = "imap.gmail.com"
_IMAP_PORT  = 993

# URL de anuncio: https://www.idealista.com/inmueble/12345678/
_URL_PATTERN = re.compile(
    r"https://www\.idealista\.com/inmueble/(\d+)/?",
    re.IGNORECASE,
)
# Precio en el email: "170.000 €" o "170000€"
_PRICE_PATTERN = re.compile(r"([\d]{2,3}[\.\s]?\d{3})\s*€")
# Habitaciones: "5 hab" o "5 habitaciones"
_ROOMS_PATTERN = re.compile(r"(\d+)\s+hab", re.IGNORECASE)
# m2: "143,00 m²" o "143 m²"
_SIZE_PATTERN  = re.compile(r"([\d]+[,.]?\d*)\s*m[²2]", re.IGNORECASE)
# Titulo del anuncio (en el link del email)
_TITLE_PATTERN = re.compile(
    r"(Casa\s+o\s+chalet|Chalet|Casa|Piso|Apartamento|Finca)[^<\n]{5,80}",
    re.IGNORECASE,
)
# Zona/ciudad en el email: "chalets en Burgos"
_ZONE_PATTERN  = re.compile(r"(?:chalets|casas|pisos)\s+en\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s]+)", re.IGNORECASE)


@dataclass
class IdealistaAlert:
    url: str
    property_id: str
    email_id: str          # IMAP message ID para borrar después
    price: int | None = None
    rooms: int | None = None
    size_m2: float | None = None
    title: str = ""
    location_hint: str = ""  # texto de zona/ciudad del email para inferir zona


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


def _extract_body_text(msg: email.message.Message) -> str:
    """Extrae texto plano + HTML del email."""
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html"):
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


def _extract_alerts_from_message(msg: email.message.Message, msg_id: str) -> list[IdealistaAlert]:
    """Extrae todas las alertas de un email de Idealista."""
    body = _extract_body_text(msg)
    alerts: list[IdealistaAlert] = []
    seen_ids: set[str] = set()

    # Zona/ciudad del email (ej: "chalets en Burgos")
    location_hints = [m.group(1).strip() for m in _ZONE_PATTERN.finditer(body)]

    for match in _URL_PATTERN.finditer(body):
        prop_id = match.group(1)
        if prop_id in seen_ids:
            continue
        seen_ids.add(prop_id)
        url = f"https://www.idealista.com/inmueble/{prop_id}/"

        # Extraer contexto del anuncio en el email (±300 chars alrededor de la URL)
        start = max(0, match.start() - 300)
        end   = min(len(body), match.end() + 300)
        ctx   = body[start:end]

        price  = _parse_price(ctx)
        rooms  = _parse_rooms(ctx)
        size   = _parse_size(ctx)
        title_m = _TITLE_PATTERN.search(ctx)
        title  = title_m.group(0).strip() if title_m else ""

        # Asignar la hint de zona más cercana (primera del email si hay varias)
        loc_hint = location_hints[0] if location_hints else ""
        # Si hay múltiples zonas en el email, intentar asignar la más cercana
        if len(location_hints) > 1:
            for hint in location_hints:
                if hint.lower() in ctx.lower():
                    loc_hint = hint
                    break

        alerts.append(IdealistaAlert(
            url=url,
            property_id=prop_id,
            email_id=msg_id,
            price=price,
            rooms=rooms,
            size_m2=size,
            title=title,
            location_hint=loc_hint,
        ))

    return alerts


def fetch_new_alerts(
    email_address: str,
    app_password: str,
    lookback_days: int = 3,
) -> tuple[list[IdealistaAlert], imaplib.IMAP4_SSL | None]:
    """
    Busca emails de Idealista en los últimos lookback_days días.
    NO filtra por UNSEEN — procesa todos, leídos o no.
    Devuelve (lista_de_alertas, conexion_imap_abierta).
    La conexión se devuelve abierta para que el llamador pueda eliminar
    los emails después de procesarlos.
    """
    try:
        imap = _connect_imap(email_address, app_password)
    except Exception as e:
        logger.error("[gmail] Error conectando a IMAP: %s", e)
        return [], None

    all_alerts: list[IdealistaAlert] = []
    try:
        imap.select("INBOX")
        since_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
        # Sin UNSEEN — buscamos todos los emails recientes de Idealista
        search_criteria = f'(FROM "{_IDEALISTA_SENDER}" SINCE "{since_date}")'
        _, message_numbers = imap.search(None, search_criteria)

        if not message_numbers or not message_numbers[0]:
            logger.info("[gmail] Sin emails de Idealista en los ultimos %d dias", lookback_days)
            return [], imap

        ids = message_numbers[0].split()
        logger.info("[gmail] Encontrados %d emails de Idealista para procesar", len(ids))

        for msg_id in ids:
            try:
                _, msg_data = imap.fetch(msg_id, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                alerts = _extract_alerts_from_message(msg, msg_id.decode())
                if alerts:
                    logger.info("[gmail] Email %s: %d anuncios extraidos", msg_id.decode(), len(alerts))
                all_alerts.extend(alerts)
            except Exception as e:
                logger.warning("[gmail] Error procesando email %s: %s", msg_id, e)

    except Exception as e:
        logger.error("[gmail] Error en búsqueda IMAP: %s", e)
        try:
            imap.close()
            imap.logout()
        except Exception:
            pass
        return [], None

    # Deduplicar por property_id
    seen: set[str] = set()
    unique = [a for a in all_alerts if not (a.property_id in seen or seen.add(a.property_id))]
    logger.info("[gmail] Total anuncios unicos: %d", len(unique))
    return unique, imap


def delete_processed_emails(imap: imaplib.IMAP4_SSL, email_ids: list[str]) -> None:
    """Elimina los emails procesados del buzón."""
    if not imap or not email_ids:
        return
    try:
        for msg_id in set(email_ids):
            imap.store(msg_id.encode(), "+FLAGS", "\\Deleted")
        imap.expunge()
        logger.info("[gmail] %d emails eliminados de INBOX", len(set(email_ids)))
    except Exception as e:
        logger.warning("[gmail] Error eliminando emails: %s", e)
    finally:
        try:
            imap.close()
            imap.logout()
        except Exception:
            pass


# Mantener compatibilidad con el código antiguo
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
