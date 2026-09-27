"""
Parser de alertas de Fotocasa recibidas por Gmail.
Autenticacion: IMAP con App Password de Google.

Tipos de email de Fotocasa España manejados:
  1. ALERTA_ZONA:   "Tienes N anuncio(s) en tu zona personalizada de Vivienda en Venta,
                     que no se te adelanten"
                    → 1 o varios anuncios, municipio en la URL, precio en el body

Formato de URL de anuncio:
  https://www.fotocasa.es/es/comprar/vivienda/{municipio}/{filtros}/{ID}/d?stc=...
  Ejemplo:
    .../fuentespina/jardin-patio-no-amueblado/188996167/d?stc=...
    .../santa-barbara/calefaccion-parking-terraza/190533055/d?stc=...
    .../amposta/grau-quintanes/190533053/d?stc=...

Extracción de datos:
  - property_id: dígitos antes de /d? en la URL
  - municipio:   segmento antes de los filtros y el ID
  - filtros:     segmento entre municipio e ID (infieren garage/jardin/ac)
  - precio:      en el body, formato "60.000 €", contexto ±600 chars alrededor de la URL
  - habitaciones: "N hab" en el body
  - tamaño:      "N m²" en el body

Inferencia has_garden / has_garage / has_ac desde filtros en la URL:
  jardin, patio, terraza → has_garden=True
  parking, garaje, cochera → has_garage=True
  calefaccion, aire → has_ac=True (calor/frío infieren climatización)

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
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

_FOTOCASA_SENDER  = "enviosfotocasa@fotocasa.es"
_IMAP_HOST        = "imap.gmail.com"
_IMAP_PORT        = 993
_SEARCH_FOLDERS   = ["INBOX", "[Gmail]/Todos", "[Gmail]/Papelera", "[Gmail]/Spam"]

# URL completa de anuncio:  /es/comprar/vivienda/{municipio}/{filtros}/{ID}/d
_URL_PATTERN = re.compile(
    r"https://www\.fotocasa\.es/es/comprar/vivienda/"
    r"([\w\-]+)"          # grupo 1: municipio
    r"/([\w\-]+)"         # grupo 2: filtros
    r"/(\d{7,})/d",       # grupo 3: property_id
    re.IGNORECASE,
)

# Precio: "60.000 €", "150.000 &euro;", con separador de miles
_PRICE_PATTERN = re.compile(
    r"([\d]{2,3}[.\xa0\s]?\d{3})\s*(?:\u20ac|&euro;|&#8364;|EUR)",
    re.IGNORECASE,
)

_ROOMS_PATTERN = re.compile(r"(\d+)\s+hab", re.IGNORECASE)
_SIZE_PATTERN  = re.compile(r"([\d]+[,.]?\d*)\s*m[\u00b22]", re.IGNORECASE)

# Palabras en el segmento de filtros de la URL que indican características
_GARDEN_KEYWORDS  = {"jardin", "patio", "terraza", "finca", "huerto", "parcela"}
_GARAGE_KEYWORDS  = {"parking", "garaje", "cochera", "garage"}
_AC_KEYWORDS      = {"calefaccion", "aire", "climatizacion", "ac", "aerotermia"}


class FotocasaEmailType(str, Enum):
    # "Tienes N anuncio(s) en tu zona personalizada de Vivienda en Venta, que no se te adelanten"
    ALERTA_ZONA    = "alerta_zona"
    # "¡Precio reducido! Tu alerta de..." (bajada de precio en alerta)
    BAJADA_PRECIO  = "bajada_precio"
    # "Novedades de tus búsquedas guardadas" / "Nuevos anuncios en tu zona"
    RESUMEN        = "resumen"
    # "¡Nuevo anuncio que coincide con tu búsqueda!"  (anuncio individual directo)
    NUEVO_ANUNCIO  = "nuevo_anuncio"
    # "Tu búsqueda guardada tiene actividad" / notificación genérica
    OTRO           = "otro"


@dataclass
class FotocasaAlert:
    url: str
    property_id: str
    email_id: str
    folder: str
    # Municipio extraído de la URL — se usa para inferir zona con _infer_zone_from_hint
    location_hint: str
    email_type: FotocasaEmailType = FotocasaEmailType.OTRO
    price: int | None = None
    rooms: int | None = None
    size_m2: float | None = None
    has_garden: bool = False
    has_garage: bool = False
    has_ac: bool = False
    is_price_drop: bool = False
    # Control de errores
    parse_error: str | None = None


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _connect_imap(email_address: str, app_password: str) -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
    imap.login(email_address, app_password)
    logger.info("[fotocasa] Conectado a IMAP como %s", email_address)
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


def _classify_fotocasa_email(subject: str) -> FotocasaEmailType:
    """
    Clasifica el tipo de email de Fotocasa por su subject.

    Tipos conocidos de Fotocasa España (a partir de casos reales):
      1. ALERTA_ZONA:   "Tienes N anuncio(s) en tu zona personalizada de Vivienda en Venta,
                         que no se te adelanten"
      2. BAJADA_PRECIO: "¡Precio reducido! Tu alerta de Vivienda en Venta..."
                        "Bajada de precio en tu alerta"
      3. RESUMEN:       "Novedades de tus búsquedas guardadas"
                        "Nuevos anuncios en tu zona personalizada"
                        "Resumen de tus alertas"
      4. NUEVO_ANUNCIO: "¡Nuevo anuncio que coincide con tu búsqueda!"
                        "Nuevo inmueble en tu búsqueda guardada"
      5. OTRO:          Bienvenida, confirmación de alerta, marketing, etc.
    """
    sl = subject.lower()
    # Bajada de precio — más específico primero
    if ("precio reducido" in sl or "bajada de precio" in sl
            or "precio rebajado" in sl or "precio ha bajado" in sl
            or "rebaja" in sl):
        return FotocasaEmailType.BAJADA_PRECIO
    # Alerta de zona — formato principal que llega
    if "zona personalizada" in sl and ("anuncio" in sl or "inmueble" in sl):
        return FotocasaEmailType.ALERTA_ZONA
    # Resumen / múltiples anuncios
    if ("novedades" in sl or "resumen" in sl or "nuevos anuncios" in sl
            or "busquedas guardadas" in sl or "búsquedas guardadas" in sl):
        return FotocasaEmailType.RESUMEN
    # Nuevo anuncio individual
    if ("nuevo anuncio" in sl or "nuevo inmueble" in sl
            or "coincide con tu busqueda" in sl or "coincide con tu búsqueda" in sl):
        return FotocasaEmailType.NUEVO_ANUNCIO
    # Fallback — si tiene URLs de anuncio se procesará igual
    if "anuncio" in sl or "inmueble" in sl or "venta" in sl or "alerta" in sl:
        return FotocasaEmailType.ALERTA_ZONA
    return FotocasaEmailType.OTRO


def _infer_features_from_url(filtros_segment: str) -> tuple[bool, bool, bool]:
    """
    Infiere has_garden, has_garage, has_ac desde el segmento de filtros de la URL.
    Ejemplo: 'jardin-patio-no-amueblado' → has_garden=True
             'calefaccion-parking-terraza' → has_ac=True, has_garage=True, has_garden=True
    """
    tokens = set(filtros_segment.lower().replace("-", " ").split())
    has_garden = bool(tokens & _GARDEN_KEYWORDS)
    has_garage = bool(tokens & _GARAGE_KEYWORDS)
    has_ac     = bool(tokens & _AC_KEYWORDS)
    return has_garden, has_garage, has_ac


def _extract_price_near_url(body: str, url_match_start: int, url_match_end: int) -> tuple[int | None, int | None, float | None]:
    """Extrae precio, habitaciones y m² del body en contexto ±600 chars alrededor de la URL."""
    start = max(0, url_match_start - 600)
    end   = min(len(body), url_match_end + 600)
    ctx   = body[start:end]

    price_m = _PRICE_PATTERN.search(ctx)
    rooms_m = _ROOMS_PATTERN.search(ctx)
    size_m  = _SIZE_PATTERN.search(ctx)

    price = None
    if price_m:
        raw = price_m.group(1).replace(".", "").replace(" ", "").replace("\xa0", "").replace(",", "")
        try:
            val = int(raw)
            price = val if 10_000 <= val <= 10_000_000 else None
        except ValueError:
            pass

    # Fallback: buscar precio en todo el body si no está cerca de la URL
    if not price:
        price_m2 = _PRICE_PATTERN.search(body)
        if price_m2:
            raw = price_m2.group(1).replace(".", "").replace(" ", "").replace("\xa0", "").replace(",", "")
            try:
                val = int(raw)
                price = val if 10_000 <= val <= 10_000_000 else None
            except ValueError:
                pass
            if price:
                logger.debug("[fotocasa] Precio no en contexto de URL, hallado en body completo: %s", price)

    rooms = int(rooms_m.group(1)) if rooms_m else None
    size  = float(size_m.group(1).replace(",", ".")) if size_m else None
    return price, rooms, size


def _extract_alerts_from_email(
    msg: email.message.Message,
    msg_id: str,
    folder: str,
) -> tuple[list[FotocasaAlert], str | None]:
    """
    Extrae alertas de un email de Fotocasa.
    Retorna (lista_alertas, error_str_o_None).
    """
    try:
        subject_raw = msg.get("Subject", "")
        subject     = _decode_subject(subject_raw)
        body        = _get_body(msg)
        email_type  = _classify_fotocasa_email(subject)

        seen_ids: set[str] = set()
        alerts:   list[FotocasaAlert] = []

        for match in _URL_PATTERN.finditer(body):
            municipio = match.group(1)   # ej: "fuentespina"
            filtros   = match.group(2)   # ej: "jardin-patio-no-amueblado"
            pid       = match.group(3)   # ej: "188996167"

            if pid in seen_ids:
                continue
            seen_ids.add(pid)

            has_garden, has_garage, has_ac = _infer_features_from_url(filtros)
            price, rooms, size_m2 = _extract_price_near_url(body, match.start(), match.end())

            # URL canónica sin tracking params
            url = f"https://www.fotocasa.es/es/comprar/vivienda/{municipio}/{filtros}/{pid}/d"

            alerts.append(FotocasaAlert(
                url=url,
                property_id=pid,
                email_id=msg_id,
                folder=folder,
                location_hint=municipio,
                email_type=email_type,
                price=price,
                rooms=rooms,
                size_m2=size_m2,
                has_garden=has_garden,
                has_garage=has_garage,
                has_ac=has_ac,
                is_price_drop=(email_type == FotocasaEmailType.BAJADA_PRECIO),
            ))

        if not alerts:
            logger.info(
                "[fotocasa] Email %s sin URLs de anuncios (tipo: %s, subject: %.60s)",
                msg_id, email_type.value, subject,
            )

        return alerts, None

    except Exception as e:
        error_msg = f"Error parseando email Fotocasa {msg_id}: {type(e).__name__}: {e}"
        logger.error("[fotocasa] %s", error_msg)
        return [], error_msg


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def fetch_new_fotocasa_alerts(
    email_address: str,
    app_password: str,
) -> tuple[list[FotocasaAlert], list[str], imaplib.IMAP4_SSL | None]:
    """
    Busca emails de Fotocasa en Gmail (INBOX y Todos).
    Sin filtro UNSEEN — igual que Idealista, para no perder emails ya leídos.
    Devuelve (alertas_ok, errores_list, imap_conn).
    Los emails con error NO se eliminan.
    """
    try:
        imap = _connect_imap(email_address, app_password)
    except Exception as e:
        logger.error("[fotocasa] Error conectando a IMAP: %s", e)
        return [], [str(e)], None

    all_alerts:  list[FotocasaAlert] = []
    all_errors:  list[str]           = []
    seen_pids:   set[str]            = set()
    failed_ids:  set[str]            = set()

    search_criteria = f'(FROM "{_FOTOCASA_SENDER}")'

    collected: list[tuple[email.message.Message, str, str]] = []

    for folder in _SEARCH_FOLDERS:
        try:
            status, _ = imap.select(folder)
            if status != "OK":
                continue
            # Para Papelera/Spam: solo emails no leídos (evita reprocesar)
            trash_folders = {"[Gmail]/Papelera", "[Gmail]/Spam",
                             "[Gmail]/Trash", "[Gmail]/Junk"}
            if folder in trash_folders:
                criteria_folder = f"(UNSEEN {search_criteria[1:-1]})"
            else:
                criteria_folder = search_criteria
            _, message_numbers = imap.search(None, criteria_folder)
            if not message_numbers or not message_numbers[0]:
                logger.info("[fotocasa] %s: 0 emails de Fotocasa", folder)
                continue
            ids = message_numbers[0].split()
            logger.info("[fotocasa] %s: %d emails de Fotocasa", folder, len(ids))
            for msg_id_bytes in ids:
                mid = msg_id_bytes.decode()
                try:
                    _, msg_data = imap.fetch(msg_id_bytes, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    collected.append((msg, mid, folder))
                except Exception as e:
                    err = f"Error leyendo email Fotocasa {mid}: {e}"
                    logger.warning("[fotocasa] %s", err)
                    all_errors.append(err)
                    failed_ids.add(mid)
        except Exception as e:
            logger.warning("[fotocasa] Error en carpeta %s: %s", folder, e)

    for msg, mid, folder in collected:
        alerts, error = _extract_alerts_from_email(msg, mid, folder)
        if error:
            all_errors.append(error)
            failed_ids.add(mid)
            continue
        for a in alerts:
            if a.property_id and a.property_id not in seen_pids:
                seen_pids.add(a.property_id)
                all_alerts.append(a)

    logger.info("[fotocasa] Total: %d anuncios, %d errores", len(all_alerts), len(all_errors))
    return all_alerts, all_errors, imap


def delete_processed_fotocasa_emails(
    imap: imaplib.IMAP4_SSL,
    alerts: list[FotocasaAlert],
    failed_ids: set[str] | None = None,
) -> None:
    """
    Elimina SOLO los emails de Fotocasa procesados con éxito.
    Los emails con error (en failed_ids) se conservan.
    """
    if not imap or not alerts:
        return

    by_folder: dict[str, set[str]] = {}
    seen_folder: dict[str, set[str]] = {}
    for a in alerts:
        if not a.property_id:
            continue
        if failed_ids and a.email_id in failed_ids:
            logger.info("[fotocasa] Email %s conservado (tuvo error)", a.email_id)
            continue
        # No eliminar emails de Papelera/Spam — ya están descartados.
        # Los marcamos como leídos (\Seen) para no reprocesarlos.
        if a.folder in ("[Gmail]/Papelera", "[Gmail]/Spam",
                        "[Gmail]/Trash", "[Gmail]/Junk"):
            seen_folder.setdefault(a.folder, set()).add(a.email_id)
            continue
        by_folder.setdefault(a.folder, set()).add(a.email_id)

    for folder, ids in by_folder.items():
        try:
            imap.select(folder)
            for msg_id in ids:
                imap.store(msg_id.encode(), "+FLAGS", "\\Deleted")
            imap.expunge()
            logger.info("[fotocasa] %d emails eliminados de %s", len(ids), folder)
        except Exception as e:
            logger.warning("[fotocasa] Error eliminando de %s: %s", folder, e)
    for folder, ids in seen_folder.items():
        try:
            imap.select(folder)
            for msg_id in ids:
                imap.store(msg_id.encode(), "+FLAGS", "\\Seen")
            logger.info("[fotocasa] %d emails marcados como leídos en %s", len(ids), folder)
        except Exception as e:
            logger.warning("[fotocasa] Error marcando como leídos en %s: %s", folder, e)

    try:
        imap.close()
        imap.logout()
    except Exception:
        pass
