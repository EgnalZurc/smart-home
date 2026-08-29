"""
Parser de alertas de Idealista recibidas por Gmail.
Autenticacion: IMAP con App Password de Google.

Tipos de email de Idealista:
  1. Individual: "¡Nuevo chalet en tu búsqueda: chalets en Burgos!" → 1 URL, zona en subject
  2. Bajada de precio: "¡Bajada de precio en tu búsqueda: chalets en León!" → 1 URL, precio puede estar lejos
  3. Resumen diario: "Resumen diario de nuevos anuncios" → muchas URLs

Estrategia de extracción de precio (orden de prioridad):
  1. Contexto ±600 chars alrededor de la URL
  2. Todo el body del email (para bajadas de precio donde el precio está lejos)
  3. Patrones específicos de bajada: "bajado de X a Y" → usar Y (precio actual)
"""
from __future__ import annotations
import email
import email.header
import imaplib
import logging
import re
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_IDEALISTA_SENDER = "noresponder@idealista.com"
_IMAP_HOST  = "imap.gmail.com"
_IMAP_PORT  = 993

_SEARCH_FOLDERS = ["INBOX", "[Gmail]/Todos"]

_URL_PATTERN = re.compile(r"https://www\.idealista\.com/inmueble/(\d+)/?", re.IGNORECASE)

_ZONE_FROM_SUBJECT = re.compile(
    r'(?:chalets?|casas?|pisos?)\s+en\s+([\w\s\-\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00c1\u00c9\u00cd\u00d3\u00da\u00d1]+?)(?:\s*[!,?.]|$)',
    re.IGNORECASE,
)

# Precio con formato europeo: "205.000 €", "205.000 &euro;", "205.000&#8364;"
_PRICE_PATTERN = re.compile(
    r"([\d]{2,3}[.\xa0\s]?\d{3})\s*(?:\u20ac|&euro;|&#8364;|EUR)",
    re.IGNORECASE,
)

# Patrón específico para bajadas: "bajado de 150.000 a 130.000 €"
_PRICE_DROP_PATTERN = re.compile(
    r"(?:baj[ao]do?|descend[ido]*|ahora|actual|nuevo\s+precio)\D{0,20}([\d]{2,3}[.\s]?\d{3})\s*(?:\u20ac|&euro;|&#8364;)",
    re.IGNORECASE,
)

_ROOMS_PATTERN = re.compile(r"(\d+)\s+hab", re.IGNORECASE)
_SIZE_PATTERN  = re.compile(r"([\d]+[,.]?\d*)\s*m[\u00b22]", re.IGNORECASE)


@dataclass
class IdealistaAlert:
    url: str
    property_id: str
    email_id: str
    folder: str
    location_hint: str
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
    parts = email.header.decode_header(subject_raw)
    result = ""
    for part, enc in parts:
        if isinstance(part, bytes):
            result += part.decode(enc or "utf-8", errors="ignore")
        else:
            result += str(part)
    return result


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


def _parse_price(text: str) -> int | None:
    """Extrae precio como entero. Intenta el patrón de bajada primero."""
    # Intentar patrón de bajada de precio (precio actual)
    m_drop = _PRICE_DROP_PATTERN.search(text)
    m_std  = _PRICE_PATTERN.search(text)

    # Usar el que aparezca antes (más cercano al contexto)
    match = None
    if m_drop and m_std:
        match = m_drop if m_drop.start() < m_std.start() else m_std
        group = 1
    elif m_drop:
        match = m_drop; group = 1
    elif m_std:
        match = m_std; group = 1
    
    if not match:
        return None
    
    raw = match.group(group).replace(".", "").replace(" ", "").replace("\xa0", "").replace(",", "")
    try:
        val = int(raw)
        return val if 10_000 <= val <= 10_000_000 else None
    except ValueError:
        return None


def _extract_price_from_body(body: str, pid: str) -> tuple[int | None, int | None, float | None]:
    """
    Extrae precio, habitaciones y m² de un email.
    Estrategia:
      1. Contexto ±600 chars alrededor de la URL (más amplio que antes)
      2. Si no encuentra precio, buscar en TODO el body
    Devuelve (price, rooms, size_m2).
    """
    url_match = re.search(rf"inmueble/{re.escape(pid)}", body)
    if not url_match:
        # Buscar precio en todo el body
        return _parse_price(body), None, None

    # Contexto amplio (±600 chars) para capturar precios de bajada
    start = max(0, url_match.start() - 600)
    end   = min(len(body), url_match.end() + 600)
    ctx   = body[start:end]

    price   = _parse_price(ctx)
    rooms_m = _ROOMS_PATTERN.search(ctx)
    size_m  = _SIZE_PATTERN.search(ctx)

    # Si no hay precio en el contexto cercano, buscar en todo el body
    if not price:
        price = _parse_price(body)
        logger.debug("[gmail] Precio no en contexto de %s, buscado en body: %s", pid, price)

    return (
        price,
        int(rooms_m.group(1)) if rooms_m else None,
        float(size_m.group(1).replace(",", ".")) if size_m else None,
    )


def _extract_alerts_from_email(
    msg: email.message.Message,
    msg_id: str,
    folder: str,
) -> list[IdealistaAlert]:
    subject_raw = msg.get("Subject", "")
    subject = _decode_subject(subject_raw)
    body = _get_body(msg)
    subject_lower = subject.lower()

    is_summary = (
        "resumen diario" in subject_lower or
        "novedades de tus b" in subject_lower or
        "anuncios recomendados" in subject_lower
    )
    if is_summary:
        logger.info("[gmail] Email %s: resumen diario", msg_id)
        location_hint = ""
    else:
        zone_m = _ZONE_FROM_SUBJECT.search(subject)
        location_hint = zone_m.group(1).strip() if zone_m else ""

    is_price_drop = "bajada de precio" in subject_lower

    seen_ids: set[str] = set()
    alerts: list[IdealistaAlert] = []

    for match in _URL_PATTERN.finditer(body):
        pid = match.group(1)
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        price, rooms, size_m2 = _extract_price_from_body(body, pid)

        alerts.append(IdealistaAlert(
            url=f"https://www.idealista.com/inmueble/{pid}/",
            property_id=pid,
            email_id=msg_id,
            folder=folder,
            location_hint=location_hint,
            price=price,
            rooms=rooms,
            size_m2=size_m2,
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
    Sin UNSEEN. Individuales procesados antes que resúmenes.
    """
    try:
        imap = _connect_imap(email_address, app_password)
    except Exception as e:
        logger.error("[gmail] Error conectando a IMAP: %s", e)
        return [], None

    all_alerts: list[IdealistaAlert] = []
    seen_property_ids: set[str] = set()
    search_criteria = f'(FROM "{_IDEALISTA_SENDER}")'
    collected = []

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

    # Individuales primero (tienen zona en subject), resúmenes al final
    def _is_summary(msg: email.message.Message) -> bool:
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
                logger.info("[gmail] %s | %s -> %d (%d nuevos)", folder, subj, len(alerts), new_count)
        except Exception as e:
            logger.warning("[gmail] Error procesando email %s: %s", msg_id, e)

    logger.info("[gmail] Total anuncios unicos: %d", len(all_alerts))
    return all_alerts, imap


def delete_processed_emails(imap: imaplib.IMAP4_SSL, alerts: list[IdealistaAlert]) -> None:
    """Elimina emails procesados agrupando por carpeta."""
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
            logger.warning("[gmail] Error eliminando de %s: %s", folder, e)
    try:
        imap.close()
        imap.logout()
    except Exception:
        pass


def fetch_new_alert_urls(email_address, app_password, lookback_minutes=35, **kwargs):
    """Compatibilidad legacy."""
    lookback_days = max(1, lookback_minutes // 60 + 1)
    alerts, imap = fetch_new_alerts(email_address, app_password, lookback_days)
    if imap:
        try: imap.close(); imap.logout()
        except Exception: pass
    return [a.url for a in alerts]
