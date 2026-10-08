"""
Lógica IMAP compartida por los parsers de email de casita (Idealista, Fotocasa).

Reúne el código que estaba duplicado byte a byte entre
``idealista_email_parser`` y ``fotocasa_email_parser``:

  * conexión/autenticación IMAP con App Password de Gmail,
  * decodificación de subjects y extracción del body MIME,
  * patrones de precio / habitaciones / tamaño,
  * recorrido de carpetas (``SEARCH_FOLDERS``) con el trato especial de
    Papelera/Spam (sólo UNSEEN),
  * borrado de los emails procesados con éxito (y marcado \\Seen en las
    carpetas de descarte).

Es un refactor puro: el comportamiento es idéntico al que tenían los parsers
antes de la extracción. Cada parser conserva sus propios dataclasses, sus
regex de URL específicos del portal y su clasificación de subjects.

Los objetos "alert" que se pasan a :func:`delete_processed` sólo necesitan los
atributos ``property_id``, ``email_id`` y ``folder``, que ambos dataclasses
(``IdealistaAlert`` y ``FotocasaAlert``) exponen.
"""

from __future__ import annotations

import contextlib
import email
import email.header
import email.message
import imaplib
import logging
import re

logger = logging.getLogger(__name__)

# --- Conexión --------------------------------------------------------------
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# "Casas" es una etiqueta/carpeta personalizada donde el usuario mueve
# automáticamente los emails de Fotocasa e Idealista con una regla de Gmail.
SEARCH_FOLDERS = [
    "Casas",
    "INBOX",
    "[Gmail]/Todos",
    "[Gmail]/Papelera",
    "[Gmail]/Spam",
]

# Carpetas de descarte: aquí sólo se buscan los no leídos (UNSEEN) para no
# reprocesar, y al "procesar" no se borra el email sino que se marca \\Seen.
TRASH_FOLDERS = {
    "[Gmail]/Papelera",
    "[Gmail]/Spam",
    "[Gmail]/Trash",
    "[Gmail]/Junk",
}

# --- Patrones compartidos --------------------------------------------------
# Precio: "60.000 €", "150.000 &euro;", con separador de miles
PRICE_PATTERN = re.compile(
    r"([\d]{2,3}[.\xa0\s]?\d{3})\s*(?:\u20ac|&euro;|&#8364;|EUR)",
    re.IGNORECASE,
)
ROOMS_PATTERN = re.compile(r"(\d+)\s+hab", re.IGNORECASE)
SIZE_PATTERN = re.compile(r"([\d]+[,.]?\d*)\s*m[\u00b22]", re.IGNORECASE)

# Rango de precios aceptable (filtra basura: números que no son precios de casa)
PRICE_MIN = 10_000
PRICE_MAX = 10_000_000


# ---------------------------------------------------------------------------
# Conexión / lectura
# ---------------------------------------------------------------------------
def connect_imap(
    email_address: str, app_password: str, log_prefix: str = "gmail"
) -> imaplib.IMAP4_SSL:
    """Conecta y autentica contra Gmail por IMAP con un App Password."""
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    imap.login(email_address, app_password)
    logger.info("[%s] Conectado a IMAP como %s", log_prefix, email_address)
    return imap


def decode_subject(subject_raw: str) -> str:
    """Decodifica un header Subject (posiblemente codificado RFC 2047)."""
    parts = email.header.decode_header(subject_raw)
    result = ""
    for part, enc in parts:
        if isinstance(part, bytes):
            result += part.decode(enc or "utf-8", errors="ignore")
        else:
            result += str(part)
    return result


def get_body(msg: email.message.Message) -> str:
    """Devuelve el texto (plain + html) del email, concatenado."""
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                with contextlib.suppress(Exception):
                    parts.append(
                        part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    )
    else:
        try:
            parts.append(msg.get_payload(decode=True).decode("utf-8", errors="ignore"))
        except Exception:
            parts.append(str(msg.get_payload()))
    return "\n".join(parts)


def parse_price_value(raw: str) -> int | None:
    """
    Normaliza un precio en bruto ("205.000", "60 000", "150\xa0000") a int,
    validando el rango razonable de precios de vivienda. Devuelve None si no
    es convertible o cae fuera de rango.
    """
    cleaned = raw.replace(".", "").replace(" ", "").replace("\xa0", "").replace(",", "")
    try:
        val = int(cleaned)
    except ValueError:
        return None
    return val if PRICE_MIN <= val <= PRICE_MAX else None


# ---------------------------------------------------------------------------
# Recorrido de carpetas
# ---------------------------------------------------------------------------
def collect_messages(
    imap: imaplib.IMAP4_SSL,
    sender: str,
    log_prefix: str = "gmail",
) -> tuple[list[tuple[email.message.Message, str, str]], list[str], set[str]]:
    """
    Recorre ``SEARCH_FOLDERS`` buscando emails de ``sender`` y descarga su
    RFC822. En Papelera/Spam sólo mira los no leídos (UNSEEN).

    Devuelve ``(collected, errors, failed_ids)`` donde:
      * ``collected`` es una lista de ``(msg, email_id, folder)``,
      * ``errors`` son descripciones de fallos de lectura,
      * ``failed_ids`` son los email_id que fallaron (no deben borrarse).
    """
    collected: list[tuple[email.message.Message, str, str]] = []
    errors: list[str] = []
    failed_ids: set[str] = set()

    search_criteria = f'(FROM "{sender}")'

    for folder in SEARCH_FOLDERS:
        try:
            status, _ = imap.select(folder)
            if status != "OK":
                continue
            if folder in TRASH_FOLDERS:
                criteria_folder = f"(UNSEEN {search_criteria[1:-1]})"
            else:
                criteria_folder = search_criteria
            _, message_numbers = imap.search(None, criteria_folder)
            if not message_numbers or not message_numbers[0]:
                logger.info("[%s] %s: 0 emails de %s", log_prefix, folder, sender)
                continue
            ids = message_numbers[0].split()
            logger.info(
                "[%s] %s: %d emails de %s", log_prefix, folder, len(ids), sender
            )
            for msg_id_bytes in ids:
                mid = msg_id_bytes.decode()
                try:
                    _, msg_data = imap.fetch(msg_id_bytes, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    collected.append((msg, mid, folder))
                except Exception as e:
                    err = f"Error leyendo email {mid}: {e}"
                    logger.warning("[%s] %s", log_prefix, err)
                    errors.append(err)
                    failed_ids.add(mid)
        except Exception as e:
            logger.warning("[%s] Error en carpeta %s: %s", log_prefix, folder, e)

    return collected, errors, failed_ids


# ---------------------------------------------------------------------------
# Borrado
# ---------------------------------------------------------------------------
def delete_processed(
    imap: imaplib.IMAP4_SSL | None,
    alerts: list,
    failed_ids: set[str] | None = None,
    log_prefix: str = "gmail",
) -> None:
    """
    Elimina SOLO los emails procesados con éxito. Los emails con error (en
    ``failed_ids``) se conservan. Los de Papelera/Spam no se borran: se marcan
    como leídos (\\Seen) para no reprocesarlos.

    Cada elemento de ``alerts`` debe exponer ``property_id``, ``email_id`` y
    ``folder``. Al final cierra la conexión IMAP.
    """
    if not imap or not alerts:
        return

    by_folder: dict[str, set[str]] = {}
    seen_folder: dict[str, set[str]] = {}
    for a in alerts:
        if not a.property_id:
            continue
        if failed_ids and a.email_id in failed_ids:
            logger.info("[%s] Email %s conservado (tuvo error)", log_prefix, a.email_id)
            continue
        if a.folder in TRASH_FOLDERS:
            seen_folder.setdefault(a.folder, set()).add(a.email_id)
            continue
        by_folder.setdefault(a.folder, set()).add(a.email_id)

    for folder, ids in by_folder.items():
        try:
            imap.select(folder)
            for msg_id in ids:
                imap.store(msg_id.encode(), "+FLAGS", "\\Deleted")
            imap.expunge()
            logger.info("[%s] %d emails eliminados de %s", log_prefix, len(ids), folder)
        except Exception as e:
            logger.warning("[%s] Error eliminando de %s: %s", log_prefix, folder, e)
    for folder, ids in seen_folder.items():
        try:
            imap.select(folder)
            for msg_id in ids:
                imap.store(msg_id.encode(), "+FLAGS", "\\Seen")
            logger.info(
                "[%s] %d emails marcados como leídos en %s",
                log_prefix,
                len(ids),
                folder,
            )
        except Exception as e:
            logger.warning(
                "[%s] Error marcando como leídos en %s: %s", log_prefix, folder, e
            )

    try:
        imap.close()
        imap.logout()
    except Exception:
        logger.debug("[%s] IMAP logout failed", log_prefix)
