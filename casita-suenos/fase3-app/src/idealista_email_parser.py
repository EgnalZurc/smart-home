"""
Parser de alertas de Idealista recibidas por Gmail.

Autenticacion: IMAP con App Password de Google (mas simple y fiable que OAuth2).

Flujo:
  1. Conectar a Gmail via IMAP con LOGIN (email + app password)
  2. Buscar emails no leidos de noreply@idealista.com en los ultimos N minutos
  3. Extraer URLs de anuncios del cuerpo del email
  4. Devolver lista de URLs para scraping posterior via Apify

Variables de entorno necesarias:
  - GMAIL_ADDRESS: tu direccion de Gmail
  - GMAIL_APP_PASSWORD: contraseña de aplicacion generada en myaccount.google.com/apppasswords
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_IDEALISTA_SENDER = "noreply@idealista.com"
_IMAP_HOST = "imap.gmail.com"
_IMAP_PORT = 993

# Regex para extraer URLs de anuncios de Idealista del cuerpo del email
_URL_PATTERN = re.compile(
    r"https://www\.idealista\.com/inmueble/(\d+)/?",
    re.IGNORECASE,
)


def _connect_imap(email_address: str, app_password: str) -> imaplib.IMAP4_SSL:
    """Abre conexion IMAP autenticada con App Password."""
    imap = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
    imap.login(email_address, app_password)
    logger.info("[gmail] Conectado a IMAP como %s", email_address)
    return imap


def _extract_urls_from_message(msg: email.message.Message) -> list[str]:
    """Extrae URLs de anuncios de Idealista del cuerpo de un email."""
    urls: set[str] = set()
    body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type in ("text/plain", "text/html"):
                try:
                    body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
        except Exception:
            body = str(msg.get_payload())

    for match in _URL_PATTERN.finditer(body):
        urls.add(f"https://www.idealista.com/inmueble/{match.group(1)}/")

    return list(urls)


def fetch_new_alert_urls(
    email_address: str,
    app_password: str,
    lookback_minutes: int = 35,
    # Los siguientes parametros se mantienen por compatibilidad pero no se usan
    credentials_path: str = "",
    token_path: str = "",
) -> list[str]:
    """
    Busca emails de alerta de Idealista en los ultimos lookback_minutes minutos
    y extrae todas las URLs de anuncios.

    Args:
        email_address: Direccion de Gmail.
        app_password: Contrasena de aplicacion de Google.
        lookback_minutes: Ventana de tiempo hacia atras para buscar emails.

    Returns:
        Lista de URLs unicas de anuncios de Idealista.
    """
    all_urls: list[str] = []

    try:
        imap = _connect_imap(email_address, app_password)
    except Exception as e:
        logger.error("[gmail] Error conectando a IMAP: %s", e)
        return []

    try:
        imap.select("INBOX")

        since_date = (datetime.now() - timedelta(minutes=lookback_minutes)).strftime("%d-%b-%Y")
        search_criteria = f'(FROM "{_IDEALISTA_SENDER}" SINCE "{since_date}" UNSEEN)'

        _, message_numbers = imap.search(None, search_criteria)
        if not message_numbers or not message_numbers[0]:
            logger.info("[gmail] Sin nuevos emails de Idealista en los ultimos %d min", lookback_minutes)
            return []

        ids = message_numbers[0].split()
        logger.info("[gmail] Encontrados %d emails de Idealista", len(ids))

        for msg_id in ids:
            _, msg_data = imap.fetch(msg_id, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            urls = _extract_urls_from_message(msg)
            if urls:
                logger.info("[gmail] Email %s: %d URLs extraidas", msg_id.decode(), len(urls))
                all_urls.extend(urls)

    except Exception as e:
        logger.error("[gmail] Error procesando emails: %s", e)
    finally:
        try:
            imap.close()
            imap.logout()
        except Exception:
            pass

    seen: set[str] = set()
    unique_urls = [u for u in all_urls if not (u in seen or seen.add(u))]
    logger.info("[gmail] Total URLs unicas: %d", len(unique_urls))
    return unique_urls