"""
Parser de alertas de Idealista recibidas por Gmail.
Autenticacion: IMAP con App Password de Google.

Tipos de email de Idealista EspaÃ±a manejados:
  1. NUEVO_ANUNCIO:    "Â¡Nuevo chalet en tu bÃºsqueda: chalets en Burgos!"
                       â†’ 1 URL, zona en subject, precio junto a URL
  2. BAJADA_PRECIO:    "Â¡Bajada de precio en tu bÃºsqueda: chalets en LeÃ³n!"
                       â†’ 1 URL, precio puede estar lejos de la URL en el body
  3. VISITA_3D:        "Â¡Ha incluido una Visita 3D!"
                       â†’ 1 URL, actualizaciÃ³n de anuncio existente
  4. RECOMENDADO:      "Â¡Nuevo chalet recomendado para ti!"
                       â†’ 1 URL, anuncio fuera de los filtros del usuario
  5. PRECIO_REDUCIDO:  "Â¡Precio reducido!"
                       â†’ 1 URL, similar a bajada de precio
  6. RESUMEN_DIARIO:   "Resumen diario de nuevos anuncios"
                       â†’ MÃºltiples URLs, sin zona fija por anuncio
  7. NOVEDADES:        "Te enviamos N novedades de tus bÃºsquedas guardadas"
                       â†’ MÃºltiples URLs, similar al resumen

Estrategia de extracciÃ³n de precio:
  1. Contexto Â±600 chars alrededor de la URL
  2. Si no hay precio, buscar en TODO el body (para bajadas de precio)
  3. PatrÃ³n especÃ­fico de bajada: "de X a Y â‚¬" â†’ captura Y (precio actual)

PolÃ­tica de errores:
  - Si un email falla al procesarse â†’ NO se elimina del buzÃ³n â†’ se notifica por Telegram
  - Solo se eliminan los emails procesados con Ã©xito
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from dataclasses import dataclass
from enum import Enum

import imap_base
from config import sanitize_imap_error
from imap_base import (
    ROOMS_PATTERN as _ROOMS_PATTERN,
)
from imap_base import (
    SIZE_PATTERN as _SIZE_PATTERN,
)
from imap_base import (
    collect_messages,
    connect_imap,
    decode_subject,
    delete_processed,
    get_body,
    parse_price_value,
)

logger = logging.getLogger(__name__)

_LOG_PREFIX = "gmail"
_IDEALISTA_SENDER = "noresponder@idealista.com"

_URL_PATTERN = re.compile(
    r"https://www\.idealista\.com/inmueble/(\d+)/?", re.IGNORECASE
)

_ZONE_FROM_SUBJECT = re.compile(
    r"(?:chalets?|casas?|pisos?|apartamentos?)\s+en\s+"
    r"([\w\s\-\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00c1\u00c9\u00cd\u00d3\u00da\u00d1]+?)"
    r"(?:\s*[!,?.]|$)",
    re.IGNORECASE,
)

# Precio estÃ¡ndar: compartido con el resto de parsers.
_PRICE_PATTERN = imap_base.PRICE_PATTERN

# Bajada de precio: "de 150.000 a 130.000 â‚¬" â†’ captura 130.000
_PRICE_DROP_CURRENT = re.compile(
    r"(?:ahora|actual|nuevo\s+precio|baj[ao]do?\s+a|precio\s+actual)[^\d]{0,20}"
    r"([\d]{2,3}[.\s]?\d{3})\s*(?:\u20ac|&euro;|&#8364;)",
    re.IGNORECASE,
)


class EmailType(str, Enum):
    NUEVO_ANUNCIO = "nuevo_anuncio"
    BAJADA_PRECIO = "bajada_precio"
    PRECIO_REDUCIDO = "precio_reducido"
    VISITA_3D = "visita_3d"
    RECOMENDADO = "recomendado"
    RESUMEN_DIARIO = "resumen_diario"
    OTRO = "otro"


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
    parse_error: str | None = None  # descripciÃ³n del error si lo hay


def _connect_imap(email_address: str, app_password: str) -> imaplib.IMAP4_SSL:
    return connect_imap(email_address, app_password, log_prefix=_LOG_PREFIX)


# Alias a los helpers compartidos (mantienen el nombre interno histÃ³rico).
_decode_subject = decode_subject
_get_body = get_body


def _classify_email(subject: str) -> EmailType:
    """Clasifica el tipo de email de Idealista por su subject."""
    sl = subject.lower()
    if (
        "resumen diario" in sl
        or "novedades" in sl
        and ("busqueda" in sl or "guardada" in sl or "b" in sl)
        or "anuncios recomendados" in sl
    ):
        return EmailType.RESUMEN_DIARIO
    if "bajada de precio" in sl or "precio ha bajado" in sl:
        return EmailType.BAJADA_PRECIO
    if "precio reducido" in sl or "precio rebajado" in sl:
        return EmailType.PRECIO_REDUCIDO
    if "visita 3d" in sl or "tour virtual" in sl:
        return EmailType.VISITA_3D
    if "recomendado" in sl and ("nuevo" in sl or "anuncio" in sl):
        return EmailType.RECOMENDADO
    if "nuevo" in sl and any(
        t in sl for t in ["chalet", "casa", "piso", "apartamento", "finca", "vivienda"]
    ):
        return EmailType.NUEVO_ANUNCIO
    if "busqueda" in sl or "b" in sl:
        return EmailType.NUEVO_ANUNCIO
    return EmailType.OTRO


def _parse_price(text: str) -> int | None:
    """Extrae precio. Para bajadas intenta capturar el precio ACTUAL (no el anterior)."""
    # Intentar patrÃ³n especÃ­fico de precio actual en bajada
    m_current = _PRICE_DROP_CURRENT.search(text)
    m_std = _PRICE_PATTERN.search(text)

    match, group = None, 1
    if m_current and m_std:
        # Si detectamos "precio actual X" explÃ­cito, preferirlo
        match = m_current if m_current.start() < m_std.start() + 50 else m_std
    elif m_current:
        match = m_current
    elif m_std:
        match = m_std

    if not match:
        return None

    return parse_price_value(match.group(group))


def _extract_price_from_body(
    body: str, pid: str
) -> tuple[int | None, int | None, float | None]:
    """
    Extrae precio, habitaciones y mÂ² del body del email.
    1. Contexto Â±600 chars alrededor de la URL del anuncio
    2. Si no hay precio, busca en todo el body (para bajadas de precio)
    """
    url_match = re.search(rf"inmueble/{re.escape(pid)}", body)

    if url_match:
        start = max(0, url_match.start() - 600)
        end = min(len(body), url_match.end() + 600)
        ctx = body[start:end]
    else:
        ctx = body[:2000]  # fallback: primeros 2000 chars

    price = _parse_price(ctx)
    rooms_m = _ROOMS_PATTERN.search(ctx)
    size_m = _SIZE_PATTERN.search(ctx)

    # Fallback: si no hay precio cerca de la URL, buscar en todo el body
    if not price:
        price = _parse_price(body)
        if price:
            logger.debug(
                "[gmail] Precio no en contexto de %s, hallado en body completo: %s",
                pid,
                price,
            )

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
    Si hay error de parseo, devuelve lista vacÃ­a + descripciÃ³n del error.
    """
    try:
        subject_raw = msg.get("Subject", "")
        subject = _decode_subject(subject_raw)
        body = _get_body(msg)
        email_type = _classify_email(subject)

        subject.lower()
        is_summary = email_type == EmailType.RESUMEN_DIARIO
        is_price_drop = email_type in (
            EmailType.BAJADA_PRECIO,
            EmailType.PRECIO_REDUCIDO,
        )

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

            alerts.append(
                IdealistaAlert(
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
                )
            )

        if not alerts:
            # Email sin URLs â€” puede ser informativo, no es error
            logger.info(
                "[gmail] Email %s sin URLs de anuncios (tipo: %s, subject: %s)",
                msg_id,
                email_type.value,
                subject[:60],
            )

        return alerts, None

    except (ValueError, AttributeError, KeyError, TypeError) as e:
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

    Note:
        IMAP connection errors are sanitized to prevent the app_password
        from appearing in logs.
    """
    try:
        imap = _connect_imap(email_address, app_password)
    except (imaplib.IMAP4.error, OSError) as e:
        # Sanitize error to prevent app_password from leaking in logs
        safe_error = sanitize_imap_error(str(e), app_password)
        logger.error("[gmail] Error conectando a IMAP: %s", safe_error)
        return [], [safe_error], None

    all_alerts: list[IdealistaAlert] = []
    seen_property_ids: set[str] = set()

    collected, all_errors, failed_email_ids = collect_messages(
        imap, _IDEALISTA_SENDER, log_prefix=_LOG_PREFIX
    )

    # Individuales primero (tienen zona en subject)
    def _is_summary(m: email.message.Message) -> bool:
        subj = _decode_subject(m.get("Subject", "")).lower()
        return (
            "resumen diario" in subj
            or "novedades de tus b" in subj
            or "anuncios recomendados" in subj
        )

    collected.sort(key=lambda x: 1 if _is_summary(x[0]) else 0)

    for msg, msg_id, folder in collected:
        alerts, error = _extract_alerts_from_email(msg, msg_id, folder)
        if error:
            all_errors.append(error)
            failed_email_ids.add(msg_id)
            # Marcar estas alertas con el error para que no se elimine el email
            IdealistaAlert(
                url="",
                property_id="",
                email_id=msg_id,
                folder=folder,
                location_hint="",
                parse_error=error,
            )
            # No aÃ±adir al procesado â€” el email se conservarÃ¡
            continue

        new_count = 0
        for a in alerts:
            if a.property_id and a.property_id not in seen_property_ids:
                seen_property_ids.add(a.property_id)
                all_alerts.append(a)
                new_count += 1

        if alerts:
            subj = _decode_subject(msg.get("Subject", ""))[:60]
            logger.info(
                "[gmail] %s | %s -> %d (%d nuevos)",
                folder,
                subj,
                len(alerts),
                new_count,
            )

    logger.info(
        "[gmail] Total: %d anuncios, %d errores", len(all_alerts), len(all_errors)
    )
    return all_alerts, all_errors, imap


def delete_processed_emails(
    imap: imaplib.IMAP4_SSL,
    alerts: list[IdealistaAlert],
    failed_ids: set[str] | None = None,
) -> None:
    """
    Elimina SOLO los emails procesados con Ã©xito.
    Los emails con error (en failed_ids) se conservan.
    """
    delete_processed(imap, alerts, failed_ids, log_prefix=_LOG_PREFIX)


# Compatibilidad legacy
def fetch_new_alert_urls(email_address, app_password, lookback_minutes=35, **kwargs):
    lookback_days = max(1, lookback_minutes // 60 + 1)
    alerts, _errors, imap = fetch_new_alerts(email_address, app_password, lookback_days)
    if imap:
        try:
            imap.close()
            imap.logout()
        except (imaplib.IMAP4.error, OSError):
            logger.debug("[idealista_parser] IMAP logout failed (legacy)")
    return [a.url for a in alerts if a.property_id]
