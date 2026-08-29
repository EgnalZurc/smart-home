"""
Parser de alertas de Idealista recibidas por Gmail.
Autenticacion: IMAP con App Password de Google.

Tipos de email de Idealista:
  1. Email individual: "¡Nuevo chalet en tu búsqueda: chalets en Burgos!"
     → 1 URL, zona en el subject
  2. "Resumen diario de nuevos anuncios"
     → Muchas URLs mezclando zonas — se procesa pero sin zona fija

Flujo:
  1. Buscar en INBOX y [Gmail]/Todos sin filtro UNSEEN
  2. Para emails individuales: zona del subject, URL única
  3. Eliminar emails procesados del INBOX
"""
from __future__ import annotations
import email
import email.header
import imaplib
import logging
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_IDEALISTA_SENDER = "noresponder@idealista.com"  # Idealista España
_IMAP_HOST  = "imap.gmail.com"
_IMAP_PORT  = 993

# Carpetas donde buscar — INBOX primero, luego Todos como fallback
_SEARCH_FOLDERS = [
    "INBOX",
    "[Gmail]/Todos",
]

_URL_PATTERN = re.compile(r"https://www\.idealista\.com/inmueble/(\d+)/?", re.IGNORECASE)

# Zona desde subject: "chalets en Burgos!", "casas en León!"
_ZONE_FROM_SUBJECT = re.compile(
    r'(?:chalets?|casas?|pisos?)\s+en\s+([\w\s\-áéíóúñÁÉÍÓÚÑ]+?)(?:\s*[!,?.]|$)',
    re.IGNORECASE,
)

# Precio en el body HTML: "205.000 €", "170.000&nbsp;€"
_PRICE_PATTERN = re.compile(r"([\d]{2,3}[.\xa0\s]?\d{3})\s*(?:\u20ac|&euro;|&#8364;|\u20ac|EUR)", re.IGNORECASE)
_ROOMS_PATTERN = re.compile(r"(\d+)\s+hab", re.IGNORECASE)
_SIZE_PATTERN  = re.compile(r"([\d]+[,.]?\d*)\s*m[²2]", re.IGNORECASE)


@dataclass
class IdealistaAlert:
    url: str
    property_id: str
    email_id: str       # IMAP message ID para borrar después
    folder: str         # Carpeta donde está el email
    location_hint: str  # Zona extraída del subject (ej: "Burgos", "León")
    price: int | None = None
    rooms: int | None = None
    size_m2: float | None = None
    title: str = ""
    is_price_drop: bool = False


def _connect_imap(email_address: str, app_password: str) -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
    imap.login(email_address, app_password)
    logger.info("[gmail] Conectado a IMAP como %s", email_address)
    return imap


def _decode_subject(subject_raw: str) -> str:
    """Decodifica el subject del email (puede ser quoted-printable o base64)."""
    parts = email.header.decode_header(subject_raw)
    result = ""
    for part, enc in parts:
        if isinstance(part, bytes):
            result += part.decode(enc or "utf-8", errors="ignore")
        else:
            result += str(part)
    return result


def _get_body(msg: email.message.Message) -> str:
    """Extrae el texto del email (HTML + plain)."""
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


def _parse_price(text: str) -> int | None:
    """Extrae precio como entero desde texto con formato europeo."""
    m = _PRICE_PATTERN.search(text)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(" ", "").replace("\xa0", "").replace(",", "")
    try:
        val = int(raw)
        # Sanity: precios entre 10.000 y 10.000.000
        return val if 10_000 <= val <= 10_000_000 else None
    except ValueError:
        return None


def _extract_alerts_from_email(
    msg: email.message.Message,
    msg_id: str,
    folder: str,
) -> list[IdealistaAlert]:
    """
    Extrae alertas de un email de Idealista.
    - Subject: obtener zona y si es bajada de precio
    - Body: obtener URLs de anuncios y datos básicos
    """
    subject_raw = msg.get("Subject", "")
    subject = _decode_subject(subject_raw)
    body = _get_body(msg)

    # Ignorar emails de resumen diario — mezclan muchas zonas sin contexto por anuncio
    # Se procesarán los emails individuales únicamente
    subject_lower = subject.lower()
    is_summary = (
        "resumen diario" in subject_lower or
        "novedades de tus búsquedas" in subject_lower or
        "novedades de tus busquedas" in subject_lower or
        "anuncios recomendados" in subject_lower
    )
    if is_summary:
        logger.info("[gmail] Email %s: resumen diario, procesando de todas formas", msg_id)
        # Para el resumen diario procesamos sin zona fija
        location_hint = ""
    else:
        # Zona desde el subject: "chalets en Burgos!", "casas en León!"
        zone_m = _ZONE_FROM_SUBJECT.search(subject)
        location_hint = zone_m.group(1).strip() if zone_m else ""

    is_price_drop = "bajada de precio" in subject_lower or "baja" in subject_lower

    # Extraer URLs únicas del body
    seen_ids: set[str] = set()
    alerts: list[IdealistaAlert] = []

    for match in _URL_PATTERN.finditer(body):
        pid = match.group(1)
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        url = f"https://www.idealista.com/inmueble/{pid}/"

        # Intentar extraer precio y datos del contexto HTML alrededor de la URL
        start = max(0, match.start() - 500)
        end   = min(len(body), match.end() + 500)
        ctx   = body[start:end]

        price = _parse_price(ctx)
        rooms_m = _ROOMS_PATTERN.search(ctx)
        size_m  = _SIZE_PATTERN.search(ctx)

        alerts.append(IdealistaAlert(
            url=url,
            property_id=pid,
            email_id=msg_id,
            folder=folder,
            location_hint=location_hint,
            price=price,
            rooms=int(rooms_m.group(1)) if rooms_m else None,
            size_m2=float(size_m.group(1).replace(",", ".")) if size_m else None,
            is_price_drop=is_price_drop,
        ))

    return alerts


def fetch_new_alerts(
    email_address: str,
    app_password: str,
    lookback_days: int = 7,
) -> tuple[list[IdealistaAlert], imaplib.IMAP4_SSL | None]:
    """
    Busca emails de Idealista en INBOX y Todos.
    Sin filtro UNSEEN — procesa todos los del remitente en los últimos N días.
    Devuelve (alertas, imap_conn) — la conexión queda abierta para borrar después.
    """
    try:
        imap = _connect_imap(email_address, app_password)
    except Exception as e:
        logger.error("[gmail] Error conectando a IMAP: %s", e)
        return [], None

    all_alerts: list[IdealistaAlert] = []
    seen_property_ids: set[str] = set()
    since_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
    # Solo filtrar por remitente — sin UNSEEN ni SINCE para no perder ninguno
    search_criteria = f'(FROM "{_IDEALISTA_SENDER}")'

    # Recoger todos los emails primero, luego procesar individuales antes que resumenes
    collected = []  # list of (msg, msg_id_str, folder)

    for folder in _SEARCH_FOLDERS:
        try:
            status, _ = imap.select(folder)
            if status != "OK":
                continue
            _, message_numbers = imap.search(None, search_criteria)
            if not message_numbers or not message_numbers[0]:
                continue
            ids = message_numbers[0].split()
            logger.info("[gmail] %s: %d emails de Idealista", folder, len(ids))
            for msg_id in ids:
                try:
                    _, msg_data = imap.fetch(msg_id, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    collected.append((msg, msg_id.decode(), folder))
                except Exception as e:
                    logger.warning("[gmail] Error leyendo email %s: %s", msg_id, e)
        except Exception as e:
            logger.warning("[gmail] Error en carpeta %s: %s", folder, e)

    # Ordenar: individuales (con zona) primero, resumenes al final
    # Esto garantiza que si un anuncio esta en ambos, se procesa con zona correcta
    def _is_summary(msg):
        subj = _decode_subject(msg.get("Subject", "")).lower()
        return ("resumen diario" in subj or "novedades de tus b" in subj or
                "anuncios recomendados" in subj)

    collected.sort(key=lambda x: (1 if _is_summary(x[0]) else 0))

    for msg, msg_id, folder in collected:
        try:
            alerts = _extract_alerts_from_email(msg, msg_id, folder)
            new_count = 0
            for a in alerts:
                if a.property_id not in seen_property_ids:
                    seen_property_ids.add(a.property_id)
                    all_alerts.append(a)
                    new_count += 1
            if alerts:
                subj = _decode_subject(msg.get("Subject", ""))[:60]
                logger.info("[gmail] %s | %s -> %d anuncios (%d nuevos)",
                            folder, subj, len(alerts), new_count)
        except Exception as e:
            logger.warning("[gmail] Error procesando email %s: %s", msg_id, e)


    logger.info("[gmail] Total anuncios unicos: %d", len(all_alerts))
    return all_alerts, imap


def delete_processed_emails(imap: imaplib.IMAP4_SSL, alerts: list[IdealistaAlert]) -> None:
    """Elimina los emails procesados agrupando por carpeta."""
    if not imap or not alerts:
        return

    by_folder: dict[str, set[str]] = {}
    for a in alerts:
        by_folder.setdefault(a.folder, set()).add(a.email_id)

    for folder, ids in by_folder.items():
        try:
            imap.select(folder)
            for msg_id in ids:
                imap.store(msg_id.encode(), "+FLAGS", "\\Deleted")
            imap.expunge()
            logger.info("[gmail] %d emails eliminados de %s", len(ids), folder)
        except Exception as e:
            logger.warning("[gmail] Error eliminando emails de %s: %s", folder, e)

    try:
        imap.close()
        imap.logout()
    except Exception:
        pass


# ── Compatibilidad legacy ──────────────────────────────────────────────────────
def fetch_new_alert_urls(email_address, app_password, lookback_minutes=35, **kwargs):
    lookback_days = max(1, lookback_minutes // 60 + 1)
    alerts, imap = fetch_new_alerts(email_address, app_password, lookback_days)
    if imap:
        try: imap.close(); imap.logout()
        except Exception: pass
    return [a.url for a in alerts]
