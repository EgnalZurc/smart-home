"""
Parser de alertas de Idealista recibidas por Gmail.
Autenticacion: IMAP con App Password de Google.

Tipos de email de Idealista España manejados:
  1. NUEVO_ANUNCIO:    "¡Nuevo chalet en tu búsqueda: chalets en Burgos!"
                       → 1 URL, zona en subject, precio junto a URL
  2. BAJADA_PRECIO:    "¡Bajada de precio en tu búsqueda: chalets en León!"
                       → 1 URL, precio puede estar lejos de la URL en el body
  3. VISITA_3D:        "¡Ha incluido una Visita 3D!"
                       → 1 URL, actualización de anuncio existente
  4. RECOMENDADO:      "¡Nuevo chalet recomendado para ti!"
                       → 1 URL, anuncio fuera de los filtros del usuario
  5. PRECIO_REDUCIDO:  "¡Precio reducido!"
                       → 1 URL, similar a bajada de precio
  6. RESUMEN_DIARIO:   "Resumen diario de nuevos anuncios"
                       → Múltiples URLs, sin zona fija por anuncio
  7. NOVEDADES:        "Te enviamos N novedades de tus búsquedas guardadas"
                       → Múltiples URLs, similar al resumen

Estrategia de extracción de precio:
  1. Contexto ±600 chars alrededor de la URL
  2. Si no hay precio, buscar en TODO el body (para bajadas de precio)
  3. Patrón específico de bajada: "de X a Y €" → captura Y (precio actual)

Política de errores:
  - Si un email falla al procesarse → NO se elimina del buzón → se notifica por Telegram
  - Solo se eliminan los emails procesados con éxito
"""
from __future__ import annotations
import email
import email.header
import imaplib
import logging
import re
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

_IDEALISTA_SENDER = "noresponder@idealista.com"
_IMAP_HOST  = "imap.gmail.com"
_IMAP_PORT  = 993
_SEARCH_FOLDERS = ["INBOX", "[Gmail]/Todos"]

_URL_PATTERN = re.compile(r"https://www\.idealista\.com/inmueble/(\d+)/?", re.IGNORECASE)

_ZONE_FROM_SUBJECT = re.compile(
    r'(?:chalets?|casas?|pisos?|apartamentos?)\s+en\s+'
    r'([\w\s\-\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00c1\u00c9\u00cd\u00d3\u00da\u00d1]+?)'
    r'(?:\s*[!,?.]|$)',
    re.IGNORECASE,
)

# Precio: "205.000 €", "205.000 &euro;", con separador de miles
_PRICE_PATTERN = re.compile(
    r"([\d]{2,3}[.\xa0\s]?\d{3})\s*(?:\u20ac|&euro;|&#8364;|EUR)",
    re.IGNORECASE,
)

# Bajada de precio: "de 150.000 a 130.000 €" → captura 130.000
_PRICE_DROP_CURRENT = re.compile(
    r"(?:ahora|actual|nuevo\s+precio|baj[ao]do?\s+a|precio\s+actual)[^\d]{0,20}"
    r"([\d]{2,3}[.\s]?\d{3})\s*(?:\u20ac|&euro;|&#8364;)",
    re.IGNORECASE,
)

_ROOMS_PATTERN = re.compile(r"(\d+)\s+hab", re.IGNORECASE)
_SIZE_PATTERN  = re.compile(r"([\d]+[,.]?\d*)\s*m[\u00b22]", re.IGNORECASE)


class EmailType(str, Enum):
    NUEVO_ANUNCIO   = "nuevo_anuncio"
    BAJADA_PRECIO   = "bajada_precio"
    PRECIO_REDUCIDO = "precio_reducido"
    VISITA_3D       = "visita_3d"
    RECOMENDADO     = "recomendado"
    RESUMEN_DIARIO  = "resumen_diario"
    OTRO            = "otro"


@dataclass
class IdealistaAlert:
    url: str
    property_id: str
    email_id: str
    folder: str
    location_hint: str
    email_type: EmailType = EmailType.OTRO
    price: int | None = None
    rooms: int | None = None
    size_m2: float | None = None
    title: str = ""
    is_price_drop: bool = False
    # Para control de errores
    parse_error: str | None = None  # descripción del error si lo hay


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


def _classify_email(subject: str) -> EmailType:
    """Clasifica el tipo de email de Idealista por su subject."""
    sl = subject.lower()
    if ("resumen diario" in sl or
            "novedades" in sl and ("busqueda" in sl or "guardada" in sl or "b" in sl) or
            "anuncios recomendados" in sl):
        return EmailType.RESUMEN_DIARIO
    if "bajada de precio" in sl or "precio ha bajado" in sl:
        return EmailType.BAJADA_PRECIO
    if "precio reducido" in sl or "precio rebajado" in sl:
        return EmailType.PRECIO_REDUCIDO
    if "visita 3d" in sl or "tour virtual" in sl:
        return EmailType.VISITA_3D
    if "recomendado" in sl and ("nuevo" in sl or "anuncio" in sl):
        return EmailType.RECOMENDADO
    if "nuevo" in sl and any(t in sl for t in ["chalet", "casa", "piso", "apartamento", "finca", "vivienda"]):
        return EmailType.NUEVO_ANUNCIO
    if "busqueda" in sl or "b" in sl:
        return EmailType.NUEVO_ANUNCIO
    return EmailType.OTRO
def _parse_price(text: str) -> int | None:
    """Extrae precio. Para bajadas intenta capturar el precio ACTUAL (no el anterior)."""
    # Intentar patrón específico de precio actual en bajada
    m_current = _PRICE_DROP_CURRENT.search(text)
    m_std     = _PRICE_PATTERN.search(text)

    match, group = None, 1
    if m_current and m_std:
        # Si detectamos "precio actual X" explícito, preferirlo
        match = m_current if m_current.start() < m_std.start() + 50 else m_std
    elif m_current:
        match = m_current
    elif m_std:
        match = m_std

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
    Extrae precio, habitaciones y m² del body del email.
    1. Contexto ±600 chars alrededor de la URL del anuncio
    2. Si no hay precio, busca en todo el body (para bajadas de precio)
    """
    url_match = re.search(rf"inmueble/{re.escape(pid)}", body)

    if url_match:
        start = max(0, url_match.start() - 600)
        end   = min(len(body), url_match.end() + 600)
        ctx   = body[start:end]
    else:
        ctx = body[:2000]  # fallback: primeros 2000 chars

    price   = _parse_price(ctx)
    rooms_m = _ROOMS_PATTERN.search(ctx)
    size_m  = _SIZE_PATTERN.search(ctx)

    # Fallback: si no hay precio cerca de la URL, buscar en todo el body
    if not price:
        price = _parse_price(body)
        if price:
            logger.debug("[gmail] Precio no en contexto de %s, hallado en body completo: %s", pid, price)

    return (
        price,
        int(rooms_m.group(1)) if rooms_m else None,
        float(size_m.group(1).replace(",", ".")) if size_m else None,
    )


def _extract_alerts_from_email(
    msg: email.message.Message,
    msg_id: str,
    folder: str,
) -> tuple[list[IdealistaAlert], str | None]:
    """
    Extrae alertas de un email de Idealista.
    Retorna (lista_alertas, error_str_o_None).
    Si hay error de parseo, devuelve lista vacía + descripción del error.
    """
    try:
        subject_raw = msg.get("Subject", "")
        subject = _decode_subject(subject_raw)
        body = _get_body(msg)
        email_type = _classify_email(subject)

        subject_lower = subject.lower()
        is_summary = email_type == EmailType.RESUMEN_DIARIO
        is_price_drop = email_type in (EmailType.BAJADA_PRECIO, EmailType.PRECIO_REDUCIDO)

        if is_summary:
            logger.info("[gmail] Email %s: %s", msg_id, email_type.value)
            location_hint = ""
        else:
            zone_m = _ZONE_FROM_SUBJECT.search(subject)
            location_hint = zone_m.group(1).strip() if zone_m else ""

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
                email_type=email_type,
                price=price,
                rooms=rooms,
                size_m2=size_m2,
                is_price_drop=is_price_drop,
            ))

        if not alerts:
            # Email sin URLs — puede ser informativo, no es error
            logger.info("[gmail] Email %s sin URLs de anuncios (tipo: %s, subject: %s)",
                        msg_id, email_type.value, subject[:60])

        return alerts, None

    except Exception as e:
        error_msg = f"Error parseando email {msg_id}: {type(e).__name__}: {e}"
        logger.error("[gmail] %s", error_msg)
        return [], error_msg


def fetch_new_alerts(
    email_address: str,
    app_password: str,
    lookback_days: int = 7,
) -> tuple[list[IdealistaAlert], list[str], imaplib.IMAP4_SSL | None]:
    """
    Busca emails de Idealista. Sin UNSEEN. Individuales primero.
    Devuelve (alertas_ok, errores_list, imap_conn).
    Los emails con error NO se eliminan.
    """
    try:
        imap = _connect_imap(email_address, app_password)
    except Exception as e:
        logger.error("[gmail] Error conectando a IMAP: %s", e)
        return [], [], None

    all_alerts: list[IdealistaAlert] = []
    all_errors: list[str] = []
    seen_property_ids: set[str] = set()
    # Email IDs que tuvieron error — NO se eliminarán
    failed_email_ids: set[str] = set()

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
                    err = f"Error leyendo email {msg_id.decode()}: {e}"
                    logger.warning("[gmail] %s", err)
                    all_errors.append(err)
                    failed_email_ids.add(msg_id.decode())
        except Exception as e:
            logger.warning("[gmail] Error en carpeta %s: %s", folder, e)

    # Individuales primero (tienen zona en subject)
    def _is_summary(m: email.message.Message) -> bool:
        subj = _decode_subject(m.get("Subject", "")).lower()
        return ("resumen diario" in subj or "novedades de tus b" in subj or
                "anuncios recomendados" in subj)

    collected.sort(key=lambda x: (1 if _is_summary(x[0]) else 0))

    for msg, msg_id, folder in collected:
        alerts, error = _extract_alerts_from_email(msg, msg_id, folder)
        if error:
            all_errors.append(error)
            failed_email_ids.add(msg_id)
            # Marcar estas alertas con el error para que no se elimine el email
            alert_with_error = IdealistaAlert(
                url="", property_id="", email_id=msg_id, folder=folder,
                location_hint="", parse_error=error,
            )
            # No añadir al procesado — el email se conservará
            continue

        new_count = 0
        for a in alerts:
            if a.property_id and a.property_id not in seen_property_ids:
                seen_property_ids.add(a.property_id)
                all_alerts.append(a)
                new_count += 1

        if alerts:
            subj = _decode_subject(msg.get("Subject", ""))[:60]
            logger.info("[gmail] %s | %s -> %d (%d nuevos)", folder, subj, len(alerts), new_count)

    logger.info("[gmail] Total: %d anuncios, %d errores", len(all_alerts), len(all_errors))
    return all_alerts, all_errors, imap


def delete_processed_emails(
    imap: imaplib.IMAP4_SSL,
    alerts: list[IdealistaAlert],
    failed_ids: set[str] | None = None,
) -> None:
    """
    Elimina SOLO los emails procesados con éxito.
    Los emails con error (en failed_ids) se conservan.
    """
    if not imap or not alerts:
        return

    by_folder: dict[str, set[str]] = {}
    for a in alerts:
        # No eliminar si el email tuvo error o si no hay property_id (no procesado)
        if not a.property_id:
            continue
        if failed_ids and a.email_id in failed_ids:
            logger.info("[gmail] Email %s conservado (tuvo error)", a.email_id)
            continue
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


# Compatibilidad legacy
def fetch_new_alert_urls(email_address, app_password, lookback_minutes=35, **kwargs):
    lookback_days = max(1, lookback_minutes // 60 + 1)
    alerts, errors, imap = fetch_new_alerts(email_address, app_password, lookback_days)
    if imap:
        try: imap.close(); imap.logout()
        except Exception: pass
    return [a.url for a in alerts if a.property_id]
