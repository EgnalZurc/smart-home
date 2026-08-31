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
from scorer import ALERT_THRESHOLD as _ALERT_THRESHOLD, MAX_SCORE as _MAX_SCORE

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
from zones import ZONES, ZONE_COORDS

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
    last_fotocasa_check: datetime | None
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
        self._gmail_check_running: bool = False  # evita checks solapados
        self._last_fotocasa_check: datetime | None = None
        self._fotocasa_check_running: bool = False  # evita checks solapados
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
            # ── Check Fotocasa (mismo intervalo que Gmail) ───────────────────
            if cfg.get("gmail_check_enabled", True) and self._should_run_fotocasa_check_interval(gmail_interval):
                self._run_fotocasa_check()
                self._last_fotocasa_check = now

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

    def _should_run_fotocasa_check_interval(self, interval_sec: int) -> bool:
        if self._last_fotocasa_check is None:
            return True
        return (datetime.now() - self._last_fotocasa_check).total_seconds() >= interval_sec

    # ------------------------------------------------------------------
    # Jobs — públicos para llamada manual / tests
    # ------------------------------------------------------------------

    def run_scraping_now(self) -> None:
        """Ejecuta el scraping completo inmediatamente (para testing manual)."""
        self._run_scraping()

    def run_gmail_check_now(self) -> None:
        """Ejecuta el check de Gmail inmediatamente."""
        self._run_gmail_check()

    def run_fotocasa_check_now(self) -> None:
        """Ejecuta el check de correo Fotocasa inmediatamente."""
        self._run_fotocasa_check()

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
            last_fotocasa_check=self._last_fotocasa_check,
            last_summary=self._last_summary_date,
            last_scraping_result=result,
            total_properties=self._db.count_properties(),
            radar_count=self._db.get_radar_properties(min_score=_ALERT_THRESHOLD, limit=1, offset=0).get("total", 0),
            dismissed_count=len(self._db.get_dismissed()),
            scraper_errors=errors,
            top_properties=self._db.get_top_scored(limit=5, min_score=_ALERT_THRESHOLD),
        )

    def get_radar(self, limit: int = 20, offset: int = 0,
                  sort_by: str = "score", sort_dir: str = "desc",
                  filter_by: str | None = None, portal_filter: str | None = None) -> dict:
        result = self._db.get_radar_properties(
            min_score=_ALERT_THRESHOLD, limit=limit, offset=offset,
            sort_by=sort_by, sort_dir=sort_dir, filter_by=filter_by,
            portal_filter=portal_filter,
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
                    if scored.passes_alert_threshold:  # notificar si pasa threshold y no fue alertado (independiente de is_new)
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
        lines.append("https://raspberrypi.tailaa37cd.ts.net/smart-home/casita")
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
        if self._gmail_check_running:
            logger.info("[casita] Gmail check ya en curso, ignorando")
            return
        self._gmail_check_running = True
        try:
            self._do_gmail_check()
        finally:
            self._gmail_check_running = False

    def _do_gmail_check(self) -> None:
        from idealista_email_parser import fetch_new_alerts, delete_processed_emails
        logger.info("[casita] Comprobando alertas Gmail de Idealista")
        try:
            alerts, errors, imap_conn = fetch_new_alerts(
                email_address=self._gmail_address,
                app_password=self._gmail_app_password,
                lookback_days=3,
            )
        except Exception as e:
            logger.error("[casita] Error en check Gmail: %s", e)
            return
        if errors:
            for err in errors:
                logger.warning("[casita] Error parseo Idealista: %s", err)
            self._notifier.send_status(
                "⚠️ Errores procesando correo Idealista:\n" + "\n".join(errors[:3])
            )
        if not alerts:
            if imap_conn:
                try: imap_conn.close(); imap_conn.logout()
                except Exception: pass
            return
        logger.info("[casita] %d anuncios de Idealista desde Gmail", len(alerts))
        processed_email_ids, total_new, new_by_zone = [], 0, {}
        for alert in alerts:
            try:
                zone = self._infer_zone_from_hint(alert.location_hint, alert.url)
                if not zone:
                    processed_email_ids.append(alert.email_id); continue
                prop = self._scrape_idealista_property(alert, zone)
                if not prop:
                    processed_email_ids.append(alert.email_id); continue
                is_new = self._db.is_new(prop)
                price_event = self._db.upsert_property(prop)
                scored = evaluate(prop, zone)
                if scored is None:
                    processed_email_ids.append(alert.email_id); continue
                self._db.upsert_score(scored)
                if scored.passes_alert_threshold:  # notificar si pasa threshold y no fue alertado (independiente de is_new)
                    if not self._db.is_alerted(prop.unique_id):
                        self._db.mark_alerted(prop.unique_id)
                        total_new += 1
                        new_by_zone[zone.id] = new_by_zone.get(zone.id, 0) + 1
                        logger.info("[casita] Idealista ALERTA: %s %.1f pts", prop.unique_id, scored.total_score)
                if price_event and price_event.delta < 0:
                    self._notifier.send_price_drop_alert(
                        event=price_event, title=prop.title, url=prop.url, zone_name=zone.name)
                processed_email_ids.append(alert.email_id)
            except Exception as e:
                logger.error("[casita] Error procesando alerta %s: %s", alert.url, e)
                processed_email_ids.append(alert.email_id)
        # Pasar los alerts procesados (contienen folder) para eliminar correctamente
        processed_alerts = [a for a in alerts if a.email_id in set(processed_email_ids)]
        if processed_alerts and imap_conn:
            delete_processed_emails(imap_conn, processed_alerts)
        elif imap_conn:
            try: imap_conn.close(); imap_conn.logout()
            except Exception: pass
        # Solo notificar si hay casas nuevas en el radar
        if total_new > 0:
            lines = [
                "Correo Idealista procesado",
                "Anuncios analizados: {}".format(len(alerts)),
                "Nuevas en radar: {}".format(total_new),
            ]
            if new_by_zone:
                lines.append("")
                for zid, cnt in sorted(new_by_zone.items(), key=lambda x: -x[1]):
                    zn = ZONES.get(zid)
                    lines.append("  - {}: {}".format(zn.name.split("(")[0].strip() if zn else zid, cnt))
            lines += ["", "https://raspberrypi.tailaa37cd.ts.net/smart-home/casita"]
            self._notifier.send_status("\n".join(lines))
        else:
            logger.info("[casita] Gmail check sin nuevas casas para el radar")


    def _run_fotocasa_check(self) -> None:
        if self._fotocasa_check_running:
            logger.info("[casita] Fotocasa check ya en curso, ignorando")
            return
        self._fotocasa_check_running = True
        try:
            self._do_fotocasa_check()
        finally:
            self._fotocasa_check_running = False

    def _do_fotocasa_check(self) -> None:
        from fotocasa_email_parser import (
            fetch_new_fotocasa_alerts,
            delete_processed_fotocasa_emails,
            FotocasaAlert,
        )
        from models import Property, Portal, Piscina, GarageType, Habitability, Internet
        from scraper_base import (infer_habitable, infer_habitability, infer_has_garage, infer_has_garden, infer_garage_type, infer_ac, infer_ac_type, infer_internet, infer_piscina)
        from datetime import datetime as _dt

        logger.info("[casita] Comprobando alertas Gmail de Fotocasa")
        try:
            alerts, errors, imap_conn = fetch_new_fotocasa_alerts(
                email_address=self._gmail_address,
                app_password=self._gmail_app_password,
            )
        except Exception as e:
            logger.error("[casita] Error en check Fotocasa: %s", e)
            return

        if errors:
            for err in errors:
                logger.warning("[casita] Error parseo Fotocasa: %s", err)
            self._notifier.send_status(
                "⚠️ Errores procesando correo Fotocasa:\n" + "\n".join(errors[:3])
            )

        if not alerts:
            if imap_conn:
                try: imap_conn.close(); imap_conn.logout()
                except Exception: pass
            return

        logger.info("[casita] %d anuncios de Fotocasa desde Gmail", len(alerts))
        processed_email_ids, total_new, new_by_zone = [], 0, {}
        failed_ids: set[str] = set()

        for alert in alerts:
            if alert.parse_error:
                failed_ids.add(alert.email_id)
                continue
            try:
                # Inferir zona desde el municipio en la URL
                zone = self._infer_zone_from_hint(alert.location_hint, alert.url)
                if not zone:
                    logger.warning("[casita] Fotocasa sin zona para %s (%s)", alert.url, alert.location_hint)
                    processed_email_ids.append(alert.email_id)
                    continue

                # Fotocasa bloquea scraping (SPA React) → usar solo datos del email
                if not alert.price:
                    logger.debug("[casita] Fotocasa sin precio para %s, descartando", alert.url)
                    processed_email_ids.append(alert.email_id)
                    continue

                # Los filtros de Fotocasa ya garantizan jardín/garaje si están en la URL
                # Si no están en la URL, asumir True (el usuario ya configuró el filtro)
                has_garden = alert.has_garden or True   # filtro Fotocasa ya aplicado
                has_garage = alert.has_garage or True   # filtro Fotocasa ya aplicado

                # Inferir garage_type desde has_garage del alert
                garage_t = GarageType.EXTERIOR if has_garage else GarageType.NINGUNO
                prop = Property(
                    portal=Portal.FOTOCASA,
                    portal_id=alert.property_id,
                    url=alert.url,
                    zone_id=zone.id,
                    title=f"Fotocasa {alert.property_id}",
                    price=alert.price,
                    size_m2=alert.size_m2,
                    rooms=alert.rooms,
                    has_garage=has_garage,
                    has_garden_or_plot=has_garden,
                    terrain_m2=None,
                    garage_type=garage_t,
                    habitability=Habitability.DESCONOCIDO,
                    internet=Internet.NINGUNO,
                    has_ac=alert.has_ac,
                    has_ac_preinstalled=False,
                    piscina=Piscina.NINGUNA,
                    has_internet_mention=True,
                    habitable=True,
                    description="",
                    source="gmail_fotocasa",
                    first_seen=_dt.now(),
                    last_seen=_dt.now(),
                )

                is_new = self._db.is_new(prop)
                price_event = self._db.upsert_property(prop)
                scored = evaluate(prop, zone)
                if scored is None:
                    processed_email_ids.append(alert.email_id)
                    continue
                self._db.upsert_score(scored)

                if scored.passes_alert_threshold:  # notificar si pasa threshold y no fue alertado (independiente de is_new)
                    if not self._db.is_alerted(prop.unique_id):
                        self._db.mark_alerted(prop.unique_id)
                        total_new += 1
                        new_by_zone[zone.id] = new_by_zone.get(zone.id, 0) + 1
                        logger.info("[casita] Fotocasa ALERTA: %s %.1f pts", prop.unique_id, scored.total_score)

                if price_event and price_event.delta < 0:
                    self._notifier.send_price_drop_alert(
                        event=price_event, title=prop.title, url=prop.url, zone_name=zone.name)

                processed_email_ids.append(alert.email_id)

            except Exception as e:
                err_msg = f"Error procesando alerta Fotocasa {alert.url}: {type(e).__name__}: {e}"
                logger.error("[casita] %s", err_msg)
                failed_ids.add(alert.email_id)
                self._notifier.send_status(f"⚠️ {err_msg}")

        processed_alerts = [a for a in alerts if a.email_id in set(processed_email_ids)]
        if (processed_alerts or alerts) and imap_conn:
            delete_processed_fotocasa_emails(imap_conn, processed_alerts, failed_ids=failed_ids)
        elif imap_conn:
            try: imap_conn.close(); imap_conn.logout()
            except Exception: pass

        if total_new > 0:
            lines = [
                "Correo Fotocasa procesado",
                "Anuncios analizados: {}".format(len(alerts)),
                "Nuevas en radar: {}".format(total_new),
            ]
            if new_by_zone:
                lines.append("")
                for zid, cnt in sorted(new_by_zone.items(), key=lambda x: -x[1]):
                    zn = ZONES.get(zid)
                    lines.append("  - {}: {}".format(zn.name.split("(")[0].strip() if zn else zid, cnt))
            lines += ["", "https://raspberrypi.tailaa37cd.ts.net/smart-home/casita"]
            self._notifier.send_status("\n".join(lines))
        else:
            logger.info("[casita] Fotocasa check sin nuevas casas para el radar")

    def _infer_zone_from_hint(self, hint, url):
        if hint:
            hl = hint.lower().strip()
            # 1. Buscar en fotocasa_municipios (match exacto del municipio)
            for zone in ZONES.values():
                if hasattr(zone, "fotocasa_municipios") and zone.fotocasa_municipios:
                    if any(m.lower().replace("-", " ") == hl.replace("-", " ")
                           for m in zone.fotocasa_municipios):
                        return zone
            # 2. Buscar en idealista_alert_keywords
            for zone in ZONES.values():
                if any(kw.lower() in hl for kw in zone.idealista_alert_keywords):
                    return zone
                if any(w in hl for w in zone.name.lower().split() if len(w) > 4):
                    return zone
            # 3. Buscar municipio de Fotocasa como substring
            for zone in ZONES.values():
                if hasattr(zone, "fotocasa_municipios") and zone.fotocasa_municipios:
                    if any(m.lower().replace("-", " ") in hl for m in zone.fotocasa_municipios):
                        return zone
        ul = url.lower()
        for zone in ZONES.values():
            if any(kw.lower().replace(" ", "-") in ul for kw in zone.idealista_alert_keywords):
                return zone
            if hasattr(zone, "fotocasa_municipios") and zone.fotocasa_municipios:
                if any(m.lower() in ul for m in zone.fotocasa_municipios):
                    return zone
        # 4. Fallback geográfico: Nominatim → zona más cercana
        if hint:
            zone = self._infer_zone_nominatim(hint)
            if zone:
                return zone
        return None

    def _infer_zone_nominatim(self, hint: str):
        """
        Fallback: usa Nominatim (OSM) para obtener coordenadas del municipio,
        luego devuelve la zona más cercana geográficamente.
        Solo se invoca cuando el mapeo por keywords falla.
        Máx distancia: 200 km. Si está más lejos de todas las zonas → None.
        """
        import math
        import json
        import urllib.request
        import urllib.parse
        try:
            q = urllib.parse.urlencode({
                "q": hint.replace("-", " ") + ", España",
                "format": "json",
                "limit": "1",
                "countrycodes": "es",
            })
            req = urllib.request.Request(
                f"https://nominatim.openstreetmap.org/search?{q}",
                headers={"User-Agent": "casita-suenos/1.0 (raspberrypi)"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode())
            if not data:
                logger.info("[casita] Nominatim: sin resultados para '%s'", hint)
                return None
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            logger.info("[casita] Nominatim '%s' → (%.3f, %.3f) tipo=%s",
                        hint, lat, lon, data[0].get("type", "?"))

            def _haversine(lat1, lon1, lat2, lon2):
                R = 6371.0
                dlat = math.radians(lat2 - lat1)
                dlon = math.radians(lon2 - lon1)
                a = (math.sin(dlat / 2) ** 2
                     + math.cos(math.radians(lat1))
                     * math.cos(math.radians(lat2))
                     * math.sin(dlon / 2) ** 2)
                return R * 2 * math.asin(math.sqrt(a))

            best_zone = None
            best_dist = float("inf")
            for zone in ZONES.values():
                coords = ZONE_COORDS.get(zone.id)
                if not coords:
                    continue
                d = _haversine(lat, lon, coords[0], coords[1])
                if d < best_dist:
                    best_dist = d
                    best_zone = zone

            MAX_DIST_KM = 200.0
            if best_zone and best_dist <= MAX_DIST_KM:
                logger.info("[casita] Nominatim fallback: '%s' → %s (%.0f km)",
                            hint, best_zone.id, best_dist)
                return best_zone
            elif best_zone:
                logger.info("[casita] Nominatim '%s' demasiado lejos: %.0f km (zona más cercana: %s)",
                            hint, best_dist, best_zone.id)
                return None
        except Exception as e:
            logger.warning("[casita] Nominatim fallback falló para '%s': %s", hint, e)
        return None

    def _scrape_idealista_property(self, alert, zone):
        import httpx
        from bs4 import BeautifulSoup
        from models import Property, Portal, Piscina, GarageType, Habitability, Internet
        from scraper_base import (infer_habitable, infer_habitability, infer_has_garage, infer_has_garden, infer_garage_type, infer_piscina, infer_ac, infer_ac_type, infer_internet, infer_terrain_m2, parse_price, parse_rooms, parse_size)
        from datetime import datetime as _dt
        title, price, rooms, size_m2, desc = alert.title, alert.price, alert.rooms, alert.size_m2, ""
        has_garage, has_garden, has_ac_v, piscina = False, False, False, Piscina.NINGUNA
        try:
            hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept-Language": "es-ES,es;q=0.9"}
            with httpx.Client(headers=hdrs, follow_redirects=True, timeout=15) as client:
                r = client.get(alert.url)
                if r.status_code == 200 and len(r.text) > 5000:
                    soup = BeautifulSoup(r.text, "html.parser")
                    h1 = soup.select_one("h1 .main-info__title-main, h1")
                    if h1: title = h1.get_text(strip=True)
                    pe = soup.select_one(".info-data-price span, [class*=info-data-price]")
                    if pe:
                        pp = parse_price(pe.get_text(strip=True))
                        if pp: price = pp
                    de = soup.select_one("div.comment, .adCommentsLanguage")
                    if de: desc = de.get_text(" ", strip=True)
                    feats = [f.get_text(strip=True) for f in soup.select(".details-property-feature li, .feature-details li")]
                    ft = desc + " " + " ".join(feats)
                    r2 = parse_rooms(ft)
                    if r2: rooms = r2
                    s2 = parse_size(ft)
                    if s2: size_m2 = s2
                    has_garage = infer_has_garage(ft, feats)
                    has_garden = infer_has_garden(ft, feats)
                    has_ac_v   = infer_ac(ft, feats)
                    piscina    = Piscina(infer_piscina(ft, feats))
                    logger.info("[casita] Ficha Idealista OK: %s", alert.url)
                else:
                    logger.warning("[casita] Idealista bloqueo status=%d: %s", r.status_code, alert.url)
        except Exception as e:
            logger.warning("[casita] Error scraping %s: %s", alert.url, e)
        # Fallback al precio del email si el scraping fue bloqueado (403)
        if not price and alert.price:
            price = alert.price
            logger.info("[casita] Precio del email como fallback: %d EUR", price)
        if not rooms and alert.rooms:
            rooms = alert.rooms
        if not size_m2 and alert.size_m2:
            size_m2 = alert.size_m2
        if not price:
            logger.debug("[casita] Sin precio para %s, descartando", alert.url)
            return None
        if not has_garden: has_garden = True  # Idealista ya filtro jardin
        if not has_garage: has_garage = True  # Idealista ya filtro garaje
        return Property(
            portal=Portal.IDEALISTA, portal_id=alert.property_id, url=alert.url,
            zone_id=zone.id, title=title or "Idealista {}".format(alert.property_id),
            price=price, size_m2=size_m2, rooms=rooms,
            has_garage=has_garage,
            has_garden_or_plot=has_garden,
            terrain_m2=infer_terrain_m2(desc, feats) if desc else None,
            garage_type=infer_garage_type(desc, feats) if desc else (
                "edificio" if has_garage else "ninguno"),
            habitability=infer_habitability(desc, title or "") if desc else None,
            internet=infer_internet(desc, feats) if desc else None,
            has_ac=(lambda t: t[0])(infer_ac_type(desc, feats)) if desc else has_ac_v,
            has_ac_preinstalled=(lambda t: t[1])(infer_ac_type(desc, feats)) if desc else False,
            piscina=piscina,
            has_internet_mention=True,
            habitable=infer_habitable(desc, title or "") if desc else True,
            description=desc, source="gmail_idealista",
            first_seen=_dt.now(), last_seen=_dt.now(),
        )

    def _run_weekly_summary(self) -> None:
        """Envía el resumen semanal por Telegram y lo guarda en DB."""
        logger.info("[casita] Enviando resumen semanal")
        try:
            top = self._db.get_top_scored(limit=5, min_score=_ALERT_THRESHOLD)
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
