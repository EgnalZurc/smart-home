"""
Scheduler principal de Casita Sueños.

Siguiendo el patrón del proyecto: threading.Thread daemon + _loop + _run_once.

Jobs programados:
  - Lunes 07:00 — scraping completo (todos los portales, todas las zonas)
  - Jueves 07:00 — scraping completo
  - Cada 30 min — check inbox Gmail (alertas Idealista)
  - Domingo 09:00 — resumen semanal por Telegram

El scheduler expone run_scraping_now() y run_gmail_check_now() para
poder ejecutarlos manualmente o desde tests sin esperar al cron.

También expone get_status() para el endpoint HTTP del dashboard.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import TYPE_CHECKING

import fotocasa_scraper
import habitaclia_scraper
import pisos_scraper
from scraper_base import ScraperResult
from scorer import evaluate
from zones import ZONES

if TYPE_CHECKING:
    from apify_client_wrapper import IdealistaApifyClient
    from database import Database
    from notifier import TelegramNotifier

logger = logging.getLogger(__name__)

# Zonas top 8 por puntuación — para el scraping semanal de Apify (free tier)
_TOP_ZONES_FOR_APIFY = [
    "zamora_meseta",
    "castellon_costa_norte",
    "salamanca_alrededores",
    "la_rioja_valle",
    "valencia_costa_norte",
    "palencia_alrededores",
    "navarra_ribera",
    "burgos_sur",
]

# Días de la semana para scraping completo (0=lunes, 3=jueves)
_SCRAPING_DAYS = {0, 3}
_SCRAPING_HOUR = dtime(7, 0)

# Día del resumen semanal (6=domingo)
_SUMMARY_DAY = 6
_SUMMARY_HOUR = dtime(9, 0)

# Intervalo del check de Gmail (segundos)
_GMAIL_CHECK_INTERVAL_SEC = 30 * 60  # 30 minutos

# Intervalo del loop principal (segundos) — cada minuto comprueba si toca algo
_LOOP_TICK_SEC = 60


@dataclass
class ScraperError:
    """Registro de un fallo de scraper para el estado del dashboard."""
    portal: str
    zone_id: str
    error: str
    detected_at: datetime = field(default_factory=datetime.now)


@dataclass
class SchedulerStatus:
    """Estado del scheduler para el endpoint del dashboard."""
    running: bool
    last_scraping: datetime | None
    last_gmail_check: datetime | None
    last_summary: datetime | None
    last_scraping_result: str        # "ok", "ok_with_errors", "error", "never"
    total_properties: int
    radar_count: int
    dismissed_count: int
    scraper_errors: list[ScraperError]
    top_properties: list[dict]


class CasitaScheduler:
    """
    Orquesta todos los jobs periódicos de Casita Sueños.
    Compatible con el patrón de scheduler del proyecto smart-home.
    """

    def __init__(
        self,
        db: "Database",
        notifier: "TelegramNotifier",
        apify: "IdealistaApifyClient",
        gmail_address: str,
        gmail_app_password: str,
    ) -> None:
        self._db = db
        self._notifier = notifier
        self._apify = apify
        self._gmail_address = gmail_address
        self._gmail_app_password = gmail_app_password

        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Tracking de cuándo se ejecutó cada job por última vez
        self._last_scraping_date: datetime | None = None
        self._last_gmail_check: datetime | None = None
        self._last_summary_date: datetime | None = None

        # Resultado del último scraping
        self._last_scraping_result: str = "never"  # "never"|"ok"|"ok_with_errors"|"error"

        # Registro de errores de scrapers (se limpia al resolver)
        self._scraper_errors: list[ScraperError] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="casita-orquestador-scheduler",
        )
        self._thread.start()
        logger.info("[casita] Scheduler iniciado")

    def stop(self) -> None:
        self._running = False
        logger.info("[casita] Scheduler detenido")

    # ------------------------------------------------------------------
    # Loop principal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        """Loop principal que comprueba cada minuto si toca ejecutar algún job."""
        # Grace period inicial de 10s para que el resto del sistema arranque
        time.sleep(10)

        while self._running:
            now = datetime.now()
            cfg = self._db.get_schedule_config()

            # ── Scraping completo ────────────────────────────────────────────
            scraping_days = set(cfg.get("scraping_days", [0, 3]))
            scraping_hour = int(cfg.get("scraping_hour", 7))
            if (cfg.get("scraping_enabled", True)
                    and now.weekday() in scraping_days
                    and now.hour == scraping_hour
                    and now.minute == 0
                    and (not self._last_scraping_date
                         or self._last_scraping_date.date() != now.date())):
                self._run_scraping()
                self._last_scraping_date = now

            # ── Check Gmail ──────────────────────────────────────────────────
            gmail_interval = int(cfg.get("gmail_interval_min", 30)) * 60
            if cfg.get("gmail_check_enabled", True) and self._should_run_gmail_check_interval(gmail_interval):
                self._run_gmail_check()
                self._last_gmail_check = now

            # ── Resumen semanal ──────────────────────────────────────────────
            summary_day  = int(cfg.get("summary_day", 6))
            summary_hour = int(cfg.get("summary_hour", 9))
            if (cfg.get("summary_enabled", True)
                    and now.weekday() == summary_day
                    and now.hour == summary_hour
                    and now.minute == 0
                    and (not self._last_summary_date
                         or self._last_summary_date.date() != now.date())):
                self._run_weekly_summary()
                self._last_summary_date = now

            time.sleep(_LOOP_TICK_SEC)

    # ------------------------------------------------------------------
    # Condiciones de ejecución
    # ------------------------------------------------------------------

    def _should_run_scraping(self, now: datetime) -> bool:
        if now.weekday() not in _SCRAPING_DAYS:
            return False
        if now.hour != _SCRAPING_HOUR.hour or now.minute != _SCRAPING_HOUR.minute:
            return False
        if self._last_scraping_date and self._last_scraping_date.date() == now.date():
            return False
        return True

    def _should_run_gmail_check(self, now: datetime) -> bool:
        if self._last_gmail_check is None:
            return True
        elapsed = (now - self._last_gmail_check).total_seconds()
        return elapsed >= _GMAIL_CHECK_INTERVAL_SEC

    def _should_run_summary(self, now: datetime) -> bool:
        if now.weekday() != _SUMMARY_DAY:
            return False
        if now.hour != _SUMMARY_HOUR.hour or now.minute != _SUMMARY_HOUR.minute:
            return False
        if self._last_summary_date and self._last_summary_date.date() == now.date():
            return False
        return True

    def _should_run_gmail_check_interval(self, interval_sec: int) -> bool:
        if self._last_gmail_check is None:
            return True
        return (datetime.now() - self._last_gmail_check).total_seconds() >= interval_sec

    # ------------------------------------------------------------------
    # Jobs — públicos para llamada manual / tests
    # ------------------------------------------------------------------

    def run_scraping_now(self) -> None:
        """Ejecuta el scraping completo inmediatamente (para testing manual)."""
        self._run_scraping()

    def run_gmail_check_now(self) -> None:
        """Ejecuta el check de Gmail inmediatamente."""
        self._run_gmail_check()

    def run_summary_now(self) -> None:
        """Envía el resumen semanal inmediatamente."""
        self._run_weekly_summary()

    def get_status(self) -> SchedulerStatus:
        """Devuelve el estado actual para el endpoint del dashboard."""
        with self._lock:
            errors = list(self._scraper_errors)
            result = self._last_scraping_result
        return SchedulerStatus(
            running=self._running,
            last_scraping=self._last_scraping_date,
            last_gmail_check=self._last_gmail_check,
            last_summary=self._last_summary_date,
            last_scraping_result=result,
            total_properties=self._db.count_properties(),
            radar_count=self._db.get_radar_properties(min_score=55.0, limit=1, offset=0).get("total", 0),
            dismissed_count=len(self._db.get_dismissed()),
            scraper_errors=errors,
            top_properties=self._db.get_top_scored(limit=5, min_score=50.0),
        )

    def get_radar(self, limit: int = 20, offset: int = 0,
                  sort_by: str = "score", sort_dir: str = "desc") -> dict:
        result = self._db.get_radar_properties(
            min_score=55.0, limit=limit, offset=offset,
            sort_by=sort_by, sort_dir=sort_dir,
        )
        # Enriquecer cada item con distance_madrid_min de la zona
        for p in result["items"]:
            zone = ZONES.get(p.get("zone_id", ""))
            p["distance_madrid_min"] = zone.distance_madrid_min if zone else None
        return result
    def get_dismissed(self) -> list[dict]:
        """Propiedades descartadas."""
        return self._db.get_dismissed()

    def dismiss_property(self, uid: str) -> bool:
        return self._db.dismiss(uid)

    def undismiss_property(self, uid: str) -> bool:
        return self._db.undismiss(uid)

    def mark_viewed(self, uid: str) -> bool:
        """Marca una propiedad como vista."""
        return self._db.mark_viewed(uid)

    def save_comment(self, uid: str, comment: str) -> bool:
        """Guarda un comentario para una propiedad."""
        return self._db.save_comment(uid, comment)

    def get_schedule_config(self) -> dict:
        return self._db.get_schedule_config()

    def save_schedule_config(self, config: dict) -> None:
        self._db.save_schedule_config(config)

    def get_last_summary(self) -> dict | None:
        return self._db.get_last_weekly_summary()

    # ------------------------------------------------------------------
    # Implementación de jobs
    # ------------------------------------------------------------------

    def _run_scraping(self) -> None:
        """
        Scraping completo de todos los portales y zonas.
        Para Apify: solo las 8 zonas top.
        Para scrapers propios: todas las zonas.
        Notifica por Telegram si un scraper falla para permitir corrección manual.
        """
        logger.info("[casita] ── Iniciando scraping completo ──────────────")
        start_time = datetime.now()
        total_new = 0
        total_price_drops = 0
        total_scored = 0
        new_errors: list[ScraperError] = []
        portals_active: set[str] = set()
        new_by_zone: dict[str, int] = {}

        for zone_id, zone in ZONES.items():
            logger.info("[casita] Procesando zona: %s", zone.name)
            all_props = []

            # ── Scrapers gratuitos ──────────────────────────────────────────
            for scraper_fn, portal_name in [
                (pisos_scraper.scrape_zone, "pisos"),
                (fotocasa_scraper.scrape_zone, "fotocasa"),
                (habitaclia_scraper.scrape_zone, "habitaclia"),
            ]:
                try:
                    props = scraper_fn(zone)
                    all_props += props
                    if props:
                        portals_active.add(portal_name)
                    logger.debug("[casita] %s/%s: %d propiedades", portal_name, zone_id, len(props))
                except Exception as e:
                    err_msg = str(e)
                    logger.error("[casita] Error %s zona %s: %s", portal_name, zone_id, err_msg)
                    error = ScraperError(portal=portal_name, zone_id=zone_id, error=err_msg)
                    new_errors.append(error)

            # ── Apify — solo las 8 zonas top ───────────────────────────────
            if zone_id in _TOP_ZONES_FOR_APIFY:
                try:
                    props = self._apify.scrape_zone(zone)
                    all_props += props
                except Exception as e:
                    err_msg = str(e)
                    logger.error("[casita] Error apify zona %s: %s", zone_id, err_msg)
                    new_errors.append(ScraperError(portal="idealista_apify", zone_id=zone_id, error=err_msg))

            # ── Procesar propiedades obtenidas ─────────────────────────────
            for prop in all_props:
                try:
                    is_new = self._db.is_new(prop)
                    price_event = self._db.upsert_property(prop)
                    scored = evaluate(prop, zone)
                    if scored is None:
                        continue
                    self._db.upsert_score(scored)
                    total_scored += 1
                    if is_new and scored.passes_alert_threshold:
                        if not self._db.is_alerted(prop.unique_id):
                            # No enviamos alerta individual ? solo el resumen al final
                            self._db.mark_alerted(prop.unique_id)
                            total_new += 1
                            new_by_zone[zone_id] = new_by_zone.get(zone_id, 0) + 1
                    if price_event and price_event.delta < 0:
                        self._notifier.send_price_drop_alert(
                            event=price_event,
                            title=prop.title,
                            url=prop.url,
                            zone_name=zone.name,
                        )
                        total_price_drops += 1
                except Exception as e:
                    logger.error("[casita] Error procesando %s: %s", prop.unique_id, e)

        # ── Notificar errores de scraper nuevos ────────────────────────────
        if new_errors:
            self._notify_scraper_errors(new_errors)
            with self._lock:
                existing_keys = {(e.portal, e.zone_id) for e in self._scraper_errors}
                for err in new_errors:
                    key = (err.portal, err.zone_id)
                    if key not in existing_keys:
                        self._scraper_errors.append(err)
            result = "ok_with_errors" if total_new > 0 or total_price_drops > 0 else "error"
        else:
            with self._lock:
                self._scraper_errors.clear()
            # Sin errores tecnicos, pero si 0 propiedades llegaron al radar
            # el scraping es funcionalmente inutil: marcamos como error
            if total_scored == 0:
                result = "error"
                logger.warning(
                    "[casita] 0 propiedades pasaron los limitantes ? marcando como error."
                )
                self._notifier.send_status(
                    "Scraping sin errores tecnicos pero 0 propiedades pasaron los filtros.\n"
                    "Revisa scrapers y limitantes en el dashboard."
                )
            else:
                result = "ok"

        with self._lock:
            self._last_scraping_result = result
        elapsed = datetime.now() - start_time
        elapsed_str = "{}m {}s".format(int(elapsed.total_seconds() // 60), int(elapsed.total_seconds() % 60))
        logger.info(
            "[casita] Scraping completado [%s] %s | %d alertas | %d en radar | %d errores",
            result, elapsed_str, total_new, total_scored, len(new_errors),
        )
        self._send_scraping_summary(
            result=result, elapsed_str=elapsed_str, total_new=total_new,
            total_price_drops=total_price_drops, total_scored=total_scored,
            portals_active=portals_active, new_by_zone=new_by_zone,
            errors_count=len(new_errors),
        )

    def _send_scraping_summary(self, result, elapsed_str, total_new,
                               total_price_drops, total_scored,
                               portals_active, new_by_zone, errors_count):
        """Envia resumen del scraping por Telegram al finalizar."""
        result_emoji = {"ok": "✅", "ok_with_errors": "⚠️", "error": "❌"}.get(result, "ℹ️")
        portal_labels = {"pisos": "Pisos.com", "habitaclia": "Habitaclia",
                         "fotocasa": "Fotocasa", "idealista": "Idealista"}
        if portals_active:
            portals_str = ", ".join(portal_labels.get(p, p) for p in sorted(portals_active))
        else:
            portals_str = "ninguno"
        lines = [
            "{} *Scraping completado*".format(result_emoji),
            "⏱ Tiempo: {}".format(elapsed_str),
            "📡 Portales: {}".format(portals_str),
            "🏠 Nuevas en radar: *{}*".format(total_new),
        ]
        if new_by_zone:
            lines.append("")
            lines.append("*Por zona:*")
            for zid, count in sorted(new_by_zone.items(), key=lambda x: -x[1]):
                zone = ZONES.get(zid)
                zname = zone.name.split("(")[0].strip() if zone else zid
                lines.append("  • {}: {}".format(zname, count))
        if total_price_drops > 0:
            lines.append("")
            lines.append("📉 Bajadas de precio: {}".format(total_price_drops))
        if errors_count > 0:
            lines.append("")
            lines.append("🔧 Errores de scraper: {} (ver dashboard)".format(errors_count))
        if total_new == 0 and result == "ok":
            lines.append("")
            lines.append("_Sin casas nuevas por encima del umbral de 50 pts._")
        lines.append("")
        lines.append("https://smart-home.local/smart-home/casita")
        self._notifier.send_status("\n".join(lines))

    def _notify_scraper_errors(self, errors: list[ScraperError]) -> None:
        """Envía una notificación por Telegram para cada scraper que ha fallado."""
        lines = ["🔧 *Errores de scraper detectados*", ""]
        for err in errors:
            lines.append(f"• *{err.portal}* / {err.zone_id}")
            # Acortar el mensaje de error para que no sea enorme
            short_err = err.error[:120] + "..." if len(err.error) > 120 else err.error
            lines.append(f"  `{short_err}`")
            lines.append("")
        lines.append("_Revisa los scrapers correspondientes y actualiza los selectores si es necesario._")
        self._notifier.send_status("\n".join(lines))

    def _run_gmail_check(self) -> None:
        """
        Comprueba el inbox de Gmail en busca de alertas de Idealista.
        Por cada URL nueva encontrada, la scrape con Apify y la evalúa.
        """
        # Import lazy para no requerir google-auth en tests sin Gmail
        from idealista_email_parser import fetch_new_alert_urls

        logger.info("[casita] Comprobando alertas Gmail de Idealista")

        try:
            urls = fetch_new_alert_urls(
                email_address=self._gmail_address,
                app_password=self._gmail_app_password,
                lookback_minutes=35,
            )
        except Exception as e:
            logger.error("[casita] Error en check Gmail: %s", e)
            return

        if not urls:
            return

        logger.info("[casita] %d URLs de Idealista desde Gmail", len(urls))

        for url in urls:
            # Intentar inferir la zona por la URL (búsqueda simple de keywords)
            zone = self._infer_zone_from_url(url)
            if not zone:
                logger.debug("[casita] No se pudo inferir zona para %s", url)
                continue

            try:
                prop = self._apify.scrape_property_url(url, zone)
                if not prop:
                    continue

                is_new = self._db.is_new(prop)
                price_event = self._db.upsert_property(prop)

                scored = evaluate(prop, zone)
                if scored is None:
                    continue

                self._db.upsert_score(scored)

                if scored.passes_alert_threshold and not self._db.is_alerted(prop.unique_id):
                    self._notifier.send_new_property_alert(scored)
                    self._db.mark_alerted(prop.unique_id)

                if price_event and price_event.delta < 0:
                    self._notifier.send_price_drop_alert(
                        event=price_event,
                        title=prop.title,
                        url=prop.url,
                        zone_name=zone.name,
                    )

            except Exception as e:
                logger.error("[casita] Error procesando URL de Gmail %s: %s", url, e)

    def _run_weekly_summary(self) -> None:
        """Envía el resumen semanal por Telegram y lo guarda en DB."""
        logger.info("[casita] Enviando resumen semanal")
        try:
            top = self._db.get_top_scored(limit=5, min_score=50.0)
            self._notifier.send_weekly_summary(top)
            stats = self._db.count_by_zone()
            total = self._db.count_properties()
            status_msg = (
                f"📊 Total propiedades monitorizadas: {total}\n"
                + "\n".join(f"  • {z}: {n}" for z, n in stats.items())
            )
            self._notifier.send_status(status_msg)

            # Guardar resumen en DB para mostrarlo en la UI
            summary_lines = ["📋 Resumen semanal — Casita Sueños", ""]
            for i, p in enumerate(top, 1):
                summary_lines.append(
                    f"{i}. {p.get('score_total',0):.1f}pts — "
                    f"{p.get('price',0):,}€ — "
                    f"{p.get('zone_id','').replace('_',' ').title()}"
                )
                summary_lines.append(f"   {p.get('url','')}")
            summary_lines.append("")
            summary_lines.append(status_msg)
            self._db.save_weekly_summary("\n".join(summary_lines))
        except Exception as e:
            logger.error("[casita] Error en resumen semanal: %s", e)

    # ------------------------------------------------------------------
    # Utilidades internas
    # ------------------------------------------------------------------

    def _infer_zone_from_url(self, url: str) -> "Zone | None":
        """
        Intenta inferir a qué zona pertenece una URL de Idealista
        buscando keywords de cada zona en la URL.
        """
        url_lower = url.lower()
        for zone in ZONES.values():
            for keyword in zone.idealista_alert_keywords:
                if keyword.lower().replace(" ", "-") in url_lower:
                    return zone
        # Si no se puede inferir, usar la zona con más propiedades como fallback
        return ZONES.get("zamora_meseta")
