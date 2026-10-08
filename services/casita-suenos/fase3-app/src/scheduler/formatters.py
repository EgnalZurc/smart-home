"""
Construcción de los mensajes de Telegram del scheduler.

Funciones puras: reciben datos y devuelven el texto del mensaje. El orquestador
se encarga de enviarlo con el notifier. Extraídas de ``casita_scheduler.py``
(``_send_scraping_summary`` y ``_notify_scraper_errors``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zones import ZONES

if TYPE_CHECKING:
    from scheduler.models import ScraperError

CASITA_DASHBOARD_URL = "https://raspberrypi.tailaa37cd.ts.net/smart-home/casita"

_RESULT_EMOJI = {"ok": "✅", "ok_with_errors": "⚠️", "error": "❌"}
_PORTAL_LABELS = {
    "pisos": "Pisos.com",
    "habitaclia": "Habitaclia",
    "fotocasa": "Fotocasa",
    "idealista": "Idealista",
}


def build_scraping_summary(
    *,
    result: str,
    elapsed_str: str,
    total_new: int,
    total_price_drops: int,
    portals_active: set[str],
    new_by_zone: dict[str, int],
    errors_count: int,
) -> str:
    """Construye el texto del resumen de scraping para Telegram."""
    result_emoji = _RESULT_EMOJI.get(result, "ℹ️")
    if portals_active:
        portals_str = ", ".join(
            _PORTAL_LABELS.get(p, p) for p in sorted(portals_active)
        )
    else:
        portals_str = "ninguno"
    lines = [
        f"{result_emoji} *Scraping completado*",
        f"⏱ Tiempo: {elapsed_str}",
        f"📡 Portales: {portals_str}",
        f"🏠 Nuevas en radar: *{total_new}*",
    ]
    if new_by_zone:
        lines.append("")
        lines.append("*Por zona:*")
        for zid, count in sorted(new_by_zone.items(), key=lambda x: -x[1]):
            zone = ZONES.get(zid)
            zname = zone.name.split("(")[0].strip() if zone else zid
            lines.append(f"  • {zname}: {count}")
    if total_price_drops > 0:
        lines.append("")
        lines.append(f"📉 Bajadas de precio: {total_price_drops}")
    if errors_count > 0:
        lines.append("")
        lines.append(f"🔧 Errores de scraper: {errors_count} (ver dashboard)")
    if total_new == 0 and result == "ok":
        lines.append("")
        lines.append("_Sin casas nuevas por encima del umbral de 50 pts._")
    lines.append("")
    lines.append(CASITA_DASHBOARD_URL)
    return "\n".join(lines)


def build_scraper_errors_message(errors: list[ScraperError]) -> str:
    """Construye el texto de la notificación de errores de scraper."""
    lines = ["🔧 *Errores de scraper detectados*", ""]
    for err in errors:
        lines.append(f"• *{err.portal}* / {err.zone_id}")
        # Acortar el mensaje de error para que no sea enorme
        short_err = err.error[:120] + "..." if len(err.error) > 120 else err.error
        lines.append(f"  `{short_err}`")
        lines.append("")
    lines.append(
        "_Revisa los scrapers correspondientes y actualiza los selectores si es necesario._"
    )
    return "\n".join(lines)


def build_email_check_summary(
    *,
    portal_label: str,
    total_alerts: int,
    total_new: int,
    new_by_zone: dict[str, int],
) -> str:
    """
    Construye el texto del resumen de un check de correo (Idealista/Fotocasa).
    Reproduce el formato previamente inline en los jobs de Gmail/Fotocasa.
    """
    lines = [
        f"Correo {portal_label} procesado",
        f"Anuncios analizados: {total_alerts}",
        f"Nuevas en radar: {total_new}",
    ]
    if new_by_zone:
        lines.append("")
        for zid, cnt in sorted(new_by_zone.items(), key=lambda x: -x[1]):
            zn = ZONES.get(zid)
            lines.append(
                "  - {}: {}".format(zn.name.split("(")[0].strip() if zn else zid, cnt)
            )
    lines += ["", CASITA_DASHBOARD_URL]
    return "\n".join(lines)
