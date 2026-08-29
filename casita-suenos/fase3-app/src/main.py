"""
casita-orquestador — Proceso principal de Casita Sueños.

Nombre del proceso: casita-orquestador
Función: orquesta el scraping inmobiliario, la puntuación de propiedades,
         las alertas Telegram y el servidor HTTP de estado.

Responsabilidades:
  - Garantiza ejecución única mediante lockfile (singleton)
  - Arranca y supervisa el CasitaScheduler (scraping lunes/jueves, check Gmail 30min)
  - Expone servidor HTTP en :8001 para el dashboard smart-home
    · GET /health  → {"online": true}
    · GET /status  → estado completo (propiedades, errores scrapers, top casas)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuración desde variables de entorno ─────────────────────────────────

# Telegram
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Apify
APIFY_API_TOKEN = os.environ["APIFY_API_TOKEN"]

# Gmail
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
DATA_DIR = os.environ.get("CASITA_DATA_DIR", "/app/data")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# Base de datos
DB_PATH = os.environ.get("CASITA_DB_PATH", f"{DATA_DIR}/casita.db")

# Apify usage tracker
APIFY_USAGE_PATH = os.environ.get(
    "APIFY_USAGE_PATH", f"{DATA_DIR}/apify_usage.json"
)

# ── Validación ────────────────────────────────────────────────────────────────

def _validate_config() -> None:
    """Valida que las variables críticas tengan valor."""
    errors = []
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN no configurado")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID no configurado")
    if not APIFY_API_TOKEN:
        errors.append("APIFY_API_TOKEN no configurado")
    if not GMAIL_ADDRESS:
        errors.append("GMAIL_ADDRESS no configurado")
    if errors:
        for e in errors:
            logger.error("[main] %s", e)
        sys.exit(1)

    if not GMAIL_APP_PASSWORD:
        logger.warning(
            "[main] GMAIL_APP_PASSWORD no configurado. "
            "El check de alertas de Idealista no funcionará. "
            "Genera una App Password en myaccount.google.com/apppasswords"
        )


# ── Nombre del proceso ────────────────────────────────────────────────────────

PROCESS_NAME = "casita-orquestador"


def _set_process_name() -> None:
    """
    Fija el nombre del proceso a 'casita-orquestador' para que sea
    identificable en ps/top/htop.
    Intenta setproctitle si está disponible; si no, modifica argv[0].
    """
    import sys
    try:
        import setproctitle  # opcional: pip install setproctitle
        setproctitle.setproctitle(PROCESS_NAME)
    except ImportError:
        # Fallback: cambiar argv[0] (visible en ps en la mayoría de sistemas)
        if sys.argv:
            sys.argv[0] = PROCESS_NAME
    # También nombramos el thread principal
    import threading
    threading.current_thread().name = PROCESS_NAME


_scheduler_instance = None  # referencia global para el servidor HTTP


# ── Servidor HTTP de estado ────────────────────────────────────────────────────

class _StatusHandler(BaseHTTPRequestHandler):
    """Handler HTTP minimalista para los endpoints /health y /status."""

    def log_message(self, format, *args):
        pass  # silenciar logs de acceso HTTP

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global _scheduler_instance

        if self.path == "/health":
            self._send_json(200, {"online": True})

        elif self.path == "/status":
            if _scheduler_instance is None:
                self._send_json(503, {"online": False, "error": "Scheduler not ready"})
                return
            status = _scheduler_instance.get_status()
            scraper_errors = [
                {"portal": e.portal, "zone_id": e.zone_id,
                 "error": e.error, "detected_at": e.detected_at.isoformat()}
                for e in status.scraper_errors
            ]
            cfg = _scheduler_instance.get_schedule_config()
            self._send_json(200, {
                "online": True,
                "running": status.running,
                "last_scraping": status.last_scraping.isoformat() if status.last_scraping else None,
                "last_gmail_check": status.last_gmail_check.isoformat() if status.last_gmail_check else None,
                "last_summary": status.last_summary.isoformat() if status.last_summary else None,
                "last_scraping_result": status.last_scraping_result,
                "total_properties": status.total_properties,
                "radar_count": status.radar_count,
                "dismissed_count": status.dismissed_count,
                "scraper_errors": scraper_errors,
                "scraper_errors_count": len(scraper_errors),
                "schedule": cfg,
                "top_properties": [
                    {"uid": p.get("uid",""), "title": p.get("title",""),
                     "price": p.get("price",0), "score": round(p.get("score_total",0),1),
                     "zone_id": p.get("zone_id",""), "url": p.get("url",""),
                     "rooms": p.get("rooms"), "size_m2": p.get("size_m2"),
                     "first_seen": p.get("first_seen","")}
                    for p in status.top_properties
                ],
            })

        elif self.path.startswith("/radar"):
            if _scheduler_instance is None:
                self._send_json(503, {"error": "Not ready"}); return
            # Parsear query params: ?limit=20&offset=0&sort_by=score&sort_dir=desc
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            def _qs(key, default):
                return qs.get(key, [default])[0]
            try:
                limit   = min(int(_qs("limit",   "20")), 100)
                offset  = max(int(_qs("offset",  "0")),  0)
                sort_by = _qs("sort_by", "score")
                sort_dir= _qs("sort_dir", "desc")
            except (ValueError, TypeError):
                limit, offset, sort_by, sort_dir = 20, 0, "score", "desc"
            result = _scheduler_instance.get_radar(
                limit=limit, offset=offset,
                sort_by=sort_by, sort_dir=sort_dir,
            )
            self._send_json(200, result)

        elif self.path == "/dismissed":
            if _scheduler_instance is None:
                self._send_json(503, {"error": "Not ready"}); return
            props = _scheduler_instance.get_dismissed()
            self._send_json(200, {"properties": props})

        elif self.path == "/schedule":
            if _scheduler_instance is None:
                self._send_json(503, {"error": "Not ready"}); return
            self._send_json(200, _scheduler_instance.get_schedule_config())

        elif self.path == "/summary":
            if _scheduler_instance is None:
                self._send_json(503, {"error": "Not ready"}); return
            summary = _scheduler_instance.get_last_summary()
            self._send_json(200, summary or {"content": None, "sent_at": None})

        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        global _scheduler_instance
        if _scheduler_instance is None:
            self._send_json(503, {"error": "Not ready"}); return

        length = int(self.headers.get("Content-Length", 0))
        body = {}
        if length:
            try:
                body = json.loads(self.rfile.read(length))
            except Exception:
                pass

        if self.path == "/dismiss":
            uid = body.get("uid", "")
            ok = _scheduler_instance.dismiss_property(uid)
            self._send_json(200 if ok else 404, {"ok": ok, "uid": uid})

        elif self.path == "/undismiss":
            uid = body.get("uid", "")
            ok = _scheduler_instance.undismiss_property(uid)
            self._send_json(200 if ok else 404, {"ok": ok, "uid": uid})

        elif self.path == "/schedule":
            _scheduler_instance.save_schedule_config(body)
            self._send_json(200, {"ok": True})

        elif self.path == "/run-scraping":
            import threading
            threading.Thread(
                target=_scheduler_instance.run_scraping_now,
                daemon=True, name="manual-scraping"
            ).start()
            self._send_json(202, {"ok": True, "message": "Scraping iniciado"})

        elif self.path == "/telegram-webhook":
            # Recibe updates del bot Telegram (webhook o polling manual)
            # Procesa el comando /start para registrar el chat_id
            try:
                update = body
                message = update.get("message", {})
                chat = message.get("chat", {})
                chat_id = str(chat.get("id", ""))
                text = message.get("text", "")
                username = chat.get("username", "") or chat.get("first_name", "")
                if chat_id and text.startswith("/start"):
                    if _scheduler_instance:
                        _scheduler_instance._notifier.register_chat(chat_id, username)
                    self._send_json(200, {"ok": True, "registered": chat_id})
                else:
                    self._send_json(200, {"ok": True})
            except Exception as e:
                self._send_json(200, {"ok": True, "warn": str(e)})
        elif self.path == "/run-summary":
            import threading
            threading.Thread(
                target=_scheduler_instance.run_summary_now,
                daemon=True, name="manual-summary"
            ).start()
            self._send_json(202, {"ok": True, "message": "Resumen iniciado"})
        elif self.path == "/mark-viewed":
            uid = body.get("uid", "")
            ok = _scheduler_instance.mark_viewed(uid)
            self._send_json(200 if ok else 404, {"ok": ok, "uid": uid})
        elif self.path == "/save-comment":
            uid = body.get("uid", "")
            comment = body.get("comment", "")
            ok = _scheduler_instance.save_comment(uid, comment)
            self._send_json(200 if ok else 404, {"ok": ok, "uid": uid})

        else:
            self._send_json(404, {"error": "Not found"})


def _start_status_server(port: int) -> None:
    """Arranca el servidor HTTP de estado en un thread daemon."""
    server = HTTPServer(("0.0.0.0", port), _StatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="casita-http")
    thread.start()
    logger.info("[main] Servidor HTTP de estado en puerto %d", port)


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def main() -> None:
    _validate_config()
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    # ── Nombre del proceso ───────────────────────────────────────────────────
    _set_process_name()

    # ── Singleton: una sola instancia ────────────────────────────────────────
    from singleton import ensure_singleton
    LOCK_PATH = os.environ.get("CASITA_LOCK_PATH", f"{DATA_DIR}/casita.lock")
    ensure_singleton(LOCK_PATH)

    logger.info("[main] ── Iniciando %s ──────────────────────────", PROCESS_NAME)

    # Puerto del servidor HTTP de estado
    STATUS_PORT = int(os.environ.get("CASITA_STATUS_PORT", "8001"))

    # Importar aquí para que el logging esté configurado antes
    from apify_client_wrapper import ApifyUsageTracker, IdealistaApifyClient
    from casita_scheduler import CasitaScheduler
    from database import Database
    from notifier import TelegramNotifier

    # Instanciar componentes
    db = Database(DB_PATH)
    notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, db=db)
    tracker = ApifyUsageTracker(APIFY_USAGE_PATH)
    apify = IdealistaApifyClient(APIFY_API_TOKEN, tracker)

    scheduler = CasitaScheduler(
        db=db,
        notifier=notifier,
        apify=apify,
        gmail_address=GMAIL_ADDRESS,
        gmail_app_password=GMAIL_APP_PASSWORD,
    )

    # Registrar referencia global para el servidor HTTP
    global _scheduler_instance
    _scheduler_instance = scheduler

    # Arrancar polling de Telegram para registrar nuevos chats (/start)
    def _telegram_polling() -> None:
        import httpx, time as _time
        token = TELEGRAM_BOT_TOKEN
        offset = 0
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        logger.info("[main] Polling Telegram iniciado")
        while True:
            try:
                resp = httpx.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
                updates = resp.json().get("result", [])
                for upd in updates:
                    offset = upd["update_id"] + 1
                    msg = upd.get("message", {})
                    text = msg.get("text", "")
                    chat = msg.get("chat", {})
                    chat_id = str(chat.get("id", ""))
                    username = chat.get("username", "") or chat.get("first_name", "")
                    if chat_id and text.startswith("/start"):
                        db.register_telegram_chat(chat_id, username)
                        logger.info("[main] Nuevo chat registrado via /start: %s (%s)", chat_id, username)
                        # Mensaje de bienvenida
                        httpx.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": chat_id,
                                  "text": "Bienvenido/a a Casita Suenos! Recibiras alertas de nuevas casas en el radar."},
                            timeout=10,
                        )
            except Exception as e:
                logger.debug("[main] Telegram polling error: %s", e)
            _time.sleep(1)

    threading.Thread(target=_telegram_polling, daemon=True, name="telegram-polling").start()

    # Arrancar servidor HTTP de estado (para dashboard)
    _start_status_server(STATUS_PORT)

    # Notificar arranque
    radar_count = len(db.get_radar_properties(min_score=55.0, limit=500).get("items", []))
    notifier.send_status(
        "🚀 Casita Suenos arrancado "
        "· {} casas en el radar".format(radar_count)
    )

    # Arrancar scheduler
    scheduler.start()
    logger.info("[main] Scheduler activo. Ctrl+C para detener.")

    # Graceful shutdown
    def _shutdown(signum, frame):
        logger.info("[main] Señal %s recibida — apagando", signum)
        scheduler.stop()
        db.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Mantener el proceso vivo
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        _shutdown(None, None)


from zones import ZONES

if __name__ == "__main__":
    main()
