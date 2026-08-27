"""
Parser de alertas de Idealista recibidas por Gmail.

Flujo:
  1. Conectar a Gmail via IMAP con OAuth2 (token guardado en /app/data/)
  2. Buscar emails no leídos de noreply@idealista.com en los últimos N minutos
  3. Extraer URLs de anuncios del cuerpo del email
  4. Devolver lista de URLs para scraping posterior via Apify

Por qué IMAP y no Gmail API:
  - IMAP con OAuth2 (XOAUTH2) no requiere habilitar ningún proyecto en Google Cloud
    si se usa con la cuenta personal y el flujo de "app de escritorio".
  - Es más simple de configurar en una Raspberry.
  - La Gmail API tiene límites de quota más complejos de gestionar.

Configuración necesaria:
  - GMAIL_ADDRESS: tu dirección de Gmail
  - GMAIL_TOKEN_PATH: ruta al fichero token.json de OAuth2 (generado en setup)
  - GMAIL_CREDENTIALS_PATH: ruta al credentials.json descargado de Google Cloud

Setup inicial (una vez):
  Ejecutar: python setup_gmail.py
  Esto abrirá el navegador para autorizar y guardará el token.
"""

from __future__ import annotations

import base64
import email
import imaplib
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Scope mínimo: solo lectura del inbox
_GMAIL_SCOPES = ["https://mail.google.com/"]

_IDEALISTA_SENDER = "noreply@idealista.com"
_IMAP_HOST = "imap.gmail.com"
_IMAP_PORT = 993

# Regex para extraer URLs de anuncios de Idealista del cuerpo del email
_URL_PATTERN = re.compile(
    r"https://www\.idealista\.com/inmueble/(\d+)/?",
    re.IGNORECASE,
)


def _load_credentials(credentials_path: str, token_path: str):
    """
    Carga o refresca las credenciales OAuth2.
    Si no existe el token, lanza RuntimeError con instrucciones.
    """
    # Import lazy para no fallar si google-auth no está instalado localmente
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds: Credentials | None = None

    if Path(token_path).exists():
        creds = Credentials.from_authorized_user_file(token_path, _GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("[gmail] Refrescando token OAuth2")
            creds.refresh(Request())
        else:
            if not Path(credentials_path).exists():
                raise RuntimeError(
                    f"No se encontró {credentials_path}. "
                    "Ejecuta 'python setup_gmail.py' para autorizarte."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, _GMAIL_SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Guardar el token para futuras ejecuciones
        Path(token_path).write_text(creds.to_json())
        logger.info("[gmail] Token guardado en %s", token_path)

    return creds


def _build_xoauth2_string(email_address: str, access_token: str) -> str:
    """Construye el string XOAUTH2 para autenticación IMAP."""
    auth_string = f"user={email_address}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(auth_string.encode()).decode()


def _connect_imap(email_address: str, credentials_path: str, token_path: str) -> imaplib.IMAP4_SSL:
    """Abre conexión IMAP autenticada con OAuth2."""
    creds = _load_credentials(credentials_path, token_path)
    auth_string = _build_xoauth2_string(email_address, creds.token)

    imap = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
    imap.authenticate("XOAUTH2", lambda x: auth_string)
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
    credentials_path: str,
    token_path: str,
    lookback_minutes: int = 35,
) -> list[str]:
    """
    Busca emails de alerta de Idealista en los últimos `lookback_minutes` minutos
    y extrae todas las URLs de anuncios.

    Args:
        email_address: Tu dirección de Gmail.
        credentials_path: Ruta a credentials.json de Google Cloud.
        token_path: Ruta donde guardar/leer el token OAuth2.
        lookback_minutes: Ventana de tiempo hacia atrás para buscar emails.

    Returns:
        Lista de URLs únicas de anuncios de Idealista.
    """
    all_urls: list[str] = []

    try:
        imap = _connect_imap(email_address, credentials_path, token_path)
    except RuntimeError as e:
        logger.error("[gmail] %s", e)
        return []
    except Exception as e:
        logger.error("[gmail] Error conectando a IMAP: %s", e)
        return []

    try:
        imap.select("INBOX")

        # Buscar emails de Idealista no leídos
        since_date = (datetime.now() - timedelta(minutes=lookback_minutes)).strftime("%d-%b-%Y")
        search_criteria = f'(FROM "{_IDEALISTA_SENDER}" SINCE "{since_date}" UNSEEN)'

        _, message_numbers = imap.search(None, search_criteria)
        if not message_numbers or not message_numbers[0]:
            logger.info("[gmail] Sin nuevos emails de Idealista en los últimos %d min", lookback_minutes)
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
                logger.info("[gmail] Email %s: %d URLs extraídas", msg_id.decode(), len(urls))
                all_urls.extend(urls)

    except Exception as e:
        logger.error("[gmail] Error procesando emails: %s", e)
    finally:
        try:
            imap.close()
            imap.logout()
        except Exception:
            pass

    # Deduplicar preservando orden
    seen: set[str] = set()
    unique_urls = [u for u in all_urls if not (u in seen or seen.add(u))]
    logger.info("[gmail] Total URLs únicas: %d", len(unique_urls))
    return unique_urls
