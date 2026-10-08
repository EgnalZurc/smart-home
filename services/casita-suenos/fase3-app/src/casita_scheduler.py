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
from datetime import datetime
from typing import TYPE_CHECKING

import fotocasa_scraper
import habitaclia_scraper
import pisos_scraper
from scheduler import formatters, zone_inference
from scheduler.config import GMAIL_CHECK_INTERVAL_SEC as _GMAIL_CHECK_INTERVAL_SEC
from scheduler.config import LOOP_TICK_SEC as _LOOP_TICK_SEC
from scheduler.config import SCRAPING_DAYS as _SCRAPING_DAYS
from scheduler.config import SCRAPING_HOUR as _SCRAPING_HOUR
from scheduler.config import SUMMARY_DAY as _SUMMARY_DAY
from scheduler.config import SUMMARY_HOUR as _SUMMARY_HOUR
from scheduler.config import TOP_ZONES_FOR_APIFY as _TOP_ZONES_FOR_APIFY
from scheduler.idealista import scrape_idealista_property as _scrape_idealista_property
from scheduler.models import SchedulerStatus, ScraperError
from scorer import ALERT_THRESHOLD as _ALERT_THRESHOLD
from scorer import evaluate, evaluate_from_email
from zones import ZONES

if TYPE_CHECKING:
    from apify_client_wrapper import IdealistaApifyClient
    from database import Database
    from notifier import TelegramNotifier
    from zones import Zone

logger = logging.getLogger(__name__)

# Re-exportados desde scheduler.models para no romper los imports existentes
# (``from casita_scheduler import ScraperError, SchedulerStatus``).
__all__ = ["CasitaScheduler", "ScraperError", "SchedulerStatus"]


class CasitaScheduler:
    """
    Orquesta todos los jobs periódicos de Casita Sueños.
    Compatible con el patrón de scheduler del proyecto smart-home.
    """

    def __init__(
        self,
        db: Database,
        notifier: TelegramNotifier,
        apify: IdealistaApifyClient,
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
        self._last_scraping_result: str = (
            "never"  # "never"|"ok"|"ok_with_errors"|"error"
        )

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
            if (
                cfg.get("scraping_enabled", True)
                and now.weekday() in scraping_days
                and now.hour == scraping_hour
                and now.minute == 0
                and (
                    not self._last_scraping_date
                    or self._last_scraping_date.date() != now.date()
                )
            ):
                self._run_scraping()
                self._last_scraping_date = now

            # ── Check Gmail ──────────────────────────────────────────────────
            gmail_interval = int(cfg.get("gmail_interval_min", 30)) * 60
            if cfg.get(
                "gmail_check_enabled", True
            ) and self._should_run_gmail_check_interval(gmail_interval):
                self._run_gmail_check()
                self._last_gmail_check = now
            # ── Check Fotocasa (mismo intervalo que Gmail) ───────────────────
            if cfg.get(
                "gmail_check_enabled", True
            ) and self._should_run_fotocasa_check_interval(gmail_interval):
                self._run_fotocasa_check()
                self._last_fotocasa_check = now

            # ── Resumen semanal ──────────────────────────────────────────────
            summary_day = int(cfg.get("summary_day", 6))
            summary_hour = int(cfg.get("summary_hour", 9))
            if (
                cfg.get("summary_enabled", True)
                and now.weekday() == summary_day
                and now.hour == summary_hour
                and now.minute == 0
                and (
                    not self._last_summary_date
                    or self._last_summary_date.date() != now.date()
                )
            ):
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
        return not (
            self._last_scraping_date and self._last_scraping_date.date() == now.date()
        )

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
        return not (
            self._last_summary_date and self._last_summary_date.date() == now.date()
        )

    def _should_run_gmail_check_interval(self, interval_sec: int) -> bool:
        if self._last_gmail_check is None:
            return True
        return (datetime.now() - self._last_gmail_check).total_seconds() >= interval_sec

    def _should_run_fotocasa_check_interval(self, interval_sec: int) -> bool:
        if self._last_fotocasa_check is None:
            return True
        return (
            datetime.now() - self._last_fotocasa_check
        ).total_seconds() >= interval_sec

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
            radar_count=self._db.get_radar_properties(
                min_score=_ALERT_THRESHOLD, limit=1, offset=0
            ).get("total", 0),
            dismissed_count=len(self._db.get_dismissed()),
            scraper_errors=errors,
            top_properties=self._db.get_top_scored(limit=5, min_score=_ALERT_THRESHOLD),
        )

    def get_radar(
        self,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "score",
        sort_dir: str = "desc",
        filter_by: str | None = None,
        portal_filter: str | None = None,
    ) -> dict:
        result = self._db.get_radar_properties(
            min_score=_ALERT_THRESHOLD,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_by=filter_by,
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
                    logger.debug(
                        "[casita] %s/%s: %d propiedades",
                        portal_name,
                        zone_id,
                        len(props),
                    )
                except Exception as e:
                    err_msg = str(e)
                    logger.error(
                        "[casita] Error %s zona %s: %s", portal_name, zone_id, err_msg
                    )
                    error = ScraperError(
                        portal=portal_name, zone_id=zone_id, error=err_msg
                    )
                    new_errors.append(error)

            # ── Apify — solo las 8 zonas top ───────────────────────────────
            if zone_id in _TOP_ZONES_FOR_APIFY:
                try:
                    props = self._apify.scrape_zone(zone)
                    all_props += props
                except Exception as e:
                    err_msg = str(e)
                    logger.error("[casita] Error apify zona %s: %s", zone_id, err_msg)
                    new_errors.append(
                        ScraperError(
                            portal="idealista_apify", zone_id=zone_id, error=err_msg
                        )
                    )

            # ── Procesar propiedades obtenidas ─────────────────────────────
            for prop in all_props:
                try:
                    self._db.is_new(prop)
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
            result = (
                "ok_with_errors" if total_new > 0 or total_price_drops > 0 else "error"
            )
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
        elapsed_str = f"{int(elapsed.total_seconds() // 60)}m {int(elapsed.total_seconds() % 60)}s"
        logger.info(
            "[casita] Scraping completado [%s] %s | %d alertas | %d en radar | %d errores",
            result,
            elapsed_str,
            total_new,
            total_scored,
            len(new_errors),
        )
        self._send_scraping_summary(
            result=result,
            elapsed_str=elapsed_str,
            total_new=total_new,
            total_price_drops=total_price_drops,
            total_scored=total_scored,
            portals_active=portals_active,
            new_by_zone=new_by_zone,
            errors_count=len(new_errors),
        )

    def _send_scraping_summary(
        self,
        result,
        elapsed_str,
        total_new,
        total_price_drops,
        total_scored,
        portals_active,
        new_by_zone,
        errors_count,
    ):
        """Envia resumen del scraping por Telegram al finalizar."""
        self._notifier.send_status(
            formatters.build_scraping_summary(
                result=result,
                elapsed_str=elapsed_str,
                total_new=total_new,
                total_price_drops=total_price_drops,
                portals_active=portals_active,
                new_by_zone=new_by_zone,
                errors_count=errors_count,
            )
        )

    def _notify_scraper_errors(self, errors: list[ScraperError]) -> None:
        """Envía una notificación por Telegram para cada scraper que ha fallado."""
        self._notifier.send_status(formatters.build_scraper_errors_message(errors))

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
        from idealista_email_parser import delete_processed_emails, fetch_new_alerts

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
                try:
                    imap_conn.close()
                    imap_conn.logout()
                except Exception:
                    logger.debug(
                        "[casita] IMAP logout failed (connection may be stale)"
                    )
            return
        logger.info("[casita] %d anuncios de Idealista desde Gmail", len(alerts))
        processed_email_ids, total_new, new_by_zone = [], 0, {}
        for alert in alerts:
            try:
                zone = self._infer_zone_from_hint(alert.location_hint, alert.url)
                if not zone:
                    processed_email_ids.append(alert.email_id)
                    continue
                prop = self._scrape_idealista_property(alert, zone)
                if not prop:
                    processed_email_ids.append(alert.email_id)
                    continue
                self._db.is_new(prop)
                price_event = self._db.upsert_property(prop)
                scored = evaluate_from_email(
                    prop, zone
                )  # bonus email: defaults garantizados por filtros del portal
                if scored is None:
                    processed_email_ids.append(alert.email_id)
                    continue
                self._db.upsert_score(scored)
                if scored.passes_alert_threshold:  # notificar si pasa threshold y no fue alertado (independiente de is_new)
                    if not self._db.is_alerted(prop.unique_id):
                        self._db.mark_alerted(prop.unique_id)
                        total_new += 1
                        new_by_zone[zone.id] = new_by_zone.get(zone.id, 0) + 1
                        logger.info(
                            "[casita] Idealista ALERTA: %s %.1f pts",
                            prop.unique_id,
                            scored.total_score,
                        )
                if price_event and price_event.delta < 0:
                    self._notifier.send_price_drop_alert(
                        event=price_event,
                        title=prop.title,
                        url=prop.url,
                        zone_name=zone.name,
                    )
                processed_email_ids.append(alert.email_id)
            except Exception as e:
                logger.error("[casita] Error procesando alerta %s: %s", alert.url, e)
                processed_email_ids.append(alert.email_id)
        # Pasar los alerts procesados (contienen folder) para eliminar correctamente
        processed_alerts = [a for a in alerts if a.email_id in set(processed_email_ids)]
        if processed_alerts and imap_conn:
            delete_processed_emails(imap_conn, processed_alerts)
        elif imap_conn:
            try:
                imap_conn.close()
                imap_conn.logout()
            except Exception:
                logger.debug("[casita] IMAP logout failed (connection may be stale)")
        # Solo notificar si hay casas nuevas en el radar
        if total_new > 0:
            self._notifier.send_status(
                formatters.build_email_check_summary(
                    portal_label="Idealista",
                    total_alerts=len(alerts),
                    total_new=total_new,
                    new_by_zone=new_by_zone,
                )
            )
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
        from datetime import datetime as _dt

        from fotocasa_email_parser import (
            delete_processed_fotocasa_emails,
            fetch_new_fotocasa_alerts,
        )
        from models import GarageType, Habitability, Internet, Piscina, Portal, Property

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
                try:
                    imap_conn.close()
                    imap_conn.logout()
                except Exception:
                    logger.debug(
                        "[casita] IMAP logout failed (connection may be stale)"
                    )
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
                    logger.warning(
                        "[casita] Fotocasa sin zona para %s (%s)",
                        alert.url,
                        alert.location_hint,
                    )
                    processed_email_ids.append(alert.email_id)
                    continue

                # Fotocasa bloquea scraping (SPA React) → usar solo datos del email
                if not alert.price:
                    logger.debug(
                        "[casita] Fotocasa sin precio para %s, descartando", alert.url
                    )
                    processed_email_ids.append(alert.email_id)
                    continue

                # Los filtros de Fotocasa que aparecen en la URL ya han sido
                # inferidos por el parser (has_garden/has_garage). Usamos esos
                # valores reales en lugar de forzarlos a True, que inflaba el score.
                has_garden = alert.has_garden
                has_garage = alert.has_garage

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

                self._db.is_new(prop)
                price_event = self._db.upsert_property(prop)
                scored = evaluate_from_email(prop, zone)  # bonus email
                if scored is None:
                    processed_email_ids.append(alert.email_id)
                    continue
                self._db.upsert_score(scored)

                if scored.passes_alert_threshold:  # notificar si pasa threshold y no fue alertado (independiente de is_new)
                    if not self._db.is_alerted(prop.unique_id):
                        self._db.mark_alerted(prop.unique_id)
                        total_new += 1
                        new_by_zone[zone.id] = new_by_zone.get(zone.id, 0) + 1
                        logger.info(
                            "[casita] Fotocasa ALERTA: %s %.1f pts",
                            prop.unique_id,
                            scored.total_score,
                        )

                if price_event and price_event.delta < 0:
                    self._notifier.send_price_drop_alert(
                        event=price_event,
                        title=prop.title,
                        url=prop.url,
                        zone_name=zone.name,
                    )

                processed_email_ids.append(alert.email_id)

            except Exception as e:
                err_msg = f"Error procesando alerta Fotocasa {alert.url}: {type(e).__name__}: {e}"
                logger.error("[casita] %s", err_msg)
                failed_ids.add(alert.email_id)
                self._notifier.send_status(f"⚠️ {err_msg}")

        processed_alerts = [a for a in alerts if a.email_id in set(processed_email_ids)]
        if (processed_alerts or alerts) and imap_conn:
            delete_processed_fotocasa_emails(
                imap_conn, processed_alerts, failed_ids=failed_ids
            )
        elif imap_conn:
            try:
                imap_conn.close()
                imap_conn.logout()
            except Exception:
                logger.debug("[casita] IMAP logout failed (connection may be stale)")

        if total_new > 0:
            self._notifier.send_status(
                formatters.build_email_check_summary(
                    portal_label="Fotocasa",
                    total_alerts=len(alerts),
                    total_new=total_new,
                    new_by_zone=new_by_zone,
                )
            )
        else:
            logger.info("[casita] Fotocasa check sin nuevas casas para el radar")

    def _infer_zone_from_hint(self, hint, url):
        """Delegado en :func:`scheduler.zone_inference.infer_zone_from_hint`."""
        return zone_inference.infer_zone_from_hint(
            hint, url, nominatim_fallback=self._infer_zone_nominatim
        )

    def _infer_zone_nominatim(self, hint: str):
        """Delegado en :func:`scheduler.zone_inference.infer_zone_nominatim`."""
        return zone_inference.infer_zone_nominatim(hint)

    def _scrape_idealista_property(self, alert, zone):
        """Delegado en :func:`scheduler.idealista.scrape_idealista_property`."""
        return _scrape_idealista_property(alert, zone)

    def _run_weekly_summary(self) -> None:
        """Envía el resumen semanal por Telegram y lo guarda en DB."""
        logger.info("[casita] Enviando resumen semanal")
        try:
            top = self._db.get_top_scored(limit=5, min_score=_ALERT_THRESHOLD)
            self._notifier.send_weekly_summary(top)
            stats = self._db.count_by_zone()
            total = self._db.count_properties()
            status_msg = f"📊 Total propiedades monitorizadas: {total}\n" + "\n".join(
                f"  • {z}: {n}" for z, n in stats.items()
            )
            self._notifier.send_status(status_msg)

            # Guardar resumen en DB para mostrarlo en la UI
            summary_lines = ["📋 Resumen semanal — Casita Sueños", ""]
            for i, p in enumerate(top, 1):
                summary_lines.append(
                    f"{i}. {p.get('score_total', 0):.1f}pts — "
                    f"{p.get('price', 0):,}€ — "
                    f"{p.get('zone_id', '').replace('_', ' ').title()}"
                )
                summary_lines.append(f"   {p.get('url', '')}")
            summary_lines.append("")
            summary_lines.append(status_msg)
            self._db.save_weekly_summary("\n".join(summary_lines))
        except Exception as e:
            logger.error("[casita] Error en resumen semanal: %s", e)

    # ------------------------------------------------------------------
    # Utilidades internas
    # ------------------------------------------------------------------

    def _infer_zone_from_url(self, url: str) -> Zone | None:
        """Delegado en :func:`scheduler.zone_inference.infer_zone_from_url`."""
        return zone_inference.infer_zone_from_url(url)
