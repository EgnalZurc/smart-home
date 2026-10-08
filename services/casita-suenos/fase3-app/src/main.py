"""
casita-orquestador — Proceso principal de Casita Sueños.

Nombre del proceso: casita-orquestador
Función: orquesta el scraping inmobiliario, la puntuación de propiedades,
         las alertas Telegram y el servidor HTTP de estado.

Responsabilidades:
  - Garantiza ejecución única mediante lockfile (singleton)
  - Arranca y supervisa el CasitaScheduler (scraping lunes/jueves, check Gmail 30min)
  - Expone servidor HTTP con FastAPI en :8001 para el dashboard smart-home
    · GET /health  → {"online": true}
    · GET /status  → estado completo (propiedades, errores scrapers, top casas)
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from scorer import ALERT_THRESHOLD as _ALERT_THRESHOLD

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuración desde variables de entorno ─────────────────────────────────

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
# Notificación de arranque en Telegram: desactivada por defecto para evitar spam
# en cada reinicio del contenedor. Las alertas reales de propiedades no se ven
# afectadas. Pon CASITA_NOTIFY_ON_STARTUP=true para reactivarla.
NOTIFY_ON_STARTUP = os.environ.get("CASITA_NOTIFY_ON_STARTUP", "false").lower() in (
    "1",
    "true",
    "yes",
)

# Apify
APIFY_API_TOKEN = os.environ.get("APIFY_API_TOKEN", "")

# Gmail
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
DATA_DIR = os.environ.get("CASITA_DATA_DIR", "/app/data")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# Base de datos
DB_PATH = os.environ.get("CASITA_DB_PATH", f"{DATA_DIR}/casita.db")

# Apify usage tracker
APIFY_USAGE_PATH = os.environ.get("APIFY_USAGE_PATH", f"{DATA_DIR}/apify_usage.json")

# Puerto
STATUS_PORT = int(os.environ.get("CASITA_STATUS_PORT", "8001"))

# ── Validación ────────────────────────────────────────────────────────────────


def _validate_config() -> None:
    """Valida que las variables críticas tengan valor."""
    errors = []
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN no configurado")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID no configurado")
    if not GMAIL_ADDRESS:
        errors.append("GMAIL_ADDRESS no configurado")
    if errors:
        for e in errors:
            logger.error("[main] %s", e)
        sys.exit(1)

    # APIFY_API_TOKEN es opcional: el módulo Idealista/Apify está deshabilitado
    # (DataDome bloquea el scraping). Sin token el servicio funciona igual, así que
    # no debe provocar un crashloop — solo avisamos.
    if not APIFY_API_TOKEN:
        logger.warning(
            "[main] APIFY_API_TOKEN no configurado. "
            "El scraping de Idealista está deshabilitado de todas formas; "
            "se continúa sin él."
        )

    if not GMAIL_APP_PASSWORD:
        logger.warning(
            "[main] GMAIL_APP_PASSWORD no configurado. "
            "El check de alertas de Idealista no funcionará. "
            "Genera una App Password en myaccount.google.com/apppasswords"
        )


# ── Nombre del proceso ────────────────────────────────────────────────────────

PROCESS_NAME = "casita-orquestador"


def _set_process_name() -> None:
    """Fija el nombre del proceso para identificarlo en ps/top/htop."""
    try:
        import setproctitle

        setproctitle.setproctitle(PROCESS_NAME)
    except ImportError:
        if sys.argv:
            sys.argv[0] = PROCESS_NAME
    threading.current_thread().name = PROCESS_NAME


# ── Instancia global del scheduler ────────────────────────────────────────────
_scheduler_instance = None
_db_instance = None

# ── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Casita Sueños",
    description="Orquestador de búsqueda inmobiliaria",
    version="2.0.0",
    docs_url=None,  # Deshabilitar docs en producción
    redoc_url=None,
)


# ── Pydantic Models ───────────────────────────────────────────────────────────


class PropertyUid(BaseModel):
    uid: str


class CommentRequest(BaseModel):
    uid: str
    comment: str


class ScheduleConfig(BaseModel):
    scraping_enabled: bool | None = None
    scraping_days: list[int] | None = None
    scraping_hour: int | None = None
    gmail_check_enabled: bool | None = None
    gmail_interval_min: int | None = None
    summary_enabled: bool | None = None
    summary_day: int | None = None
    summary_hour: int | None = None


# ── Middleware de errores ─────────────────────────────────────────────────────


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("[http] Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


# ── Static files ──────────────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static/casita", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── API Router con prefijo /api/casita ────────────────────────────────────────
# El frontend espera las rutas en /api/casita/status, /api/casita/radar, etc.
# nginx hace proxy de /api/casita/* a casita-suenos:8001/api/casita/*

api = APIRouter(prefix="/api/casita")


# ── Health endpoint (sin prefijo, para Docker healthcheck) ────────────────────


@app.get("/health")
async def health():
    return {"online": True}


# ── Status endpoint ───────────────────────────────────────────────────────────


@api.get("/status")
async def status():
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Scheduler not ready")

    import scorer

    status_obj = _scheduler_instance.get_status()
    scraper_errors = [
        {
            "portal": e.portal,
            "zone_id": e.zone_id,
            "error": e.error,
            "detected_at": e.detected_at.isoformat(),
        }
        for e in status_obj.scraper_errors
    ]
    cfg = _scheduler_instance.get_schedule_config()

    return {
        "online": True,
        "running": status_obj.running,
        "last_scraping": status_obj.last_scraping.isoformat()
        if status_obj.last_scraping
        else None,
        "last_gmail_check": status_obj.last_gmail_check.isoformat()
        if status_obj.last_gmail_check
        else None,
        "last_summary": status_obj.last_summary.isoformat()
        if status_obj.last_summary
        else None,
        "last_scraping_result": status_obj.last_scraping_result,
        "total_properties": status_obj.total_properties,
        "radar_count": status_obj.radar_count,
        "dismissed_count": status_obj.dismissed_count,
        "scraper_errors": scraper_errors,
        "scraper_errors_count": len(scraper_errors),
        "score_max": scorer.MAX_SCORE,
        "alert_threshold": scorer.ALERT_THRESHOLD,
        "alert_threshold_pct": round(scorer.ALERT_THRESHOLD / scorer.MAX_SCORE * 100),
        "schedule": cfg,
        "top_properties": [
            {
                "uid": p.get("uid", ""),
                "title": p.get("title", ""),
                "price": p.get("price", 0),
                "score": round(p.get("score_total", 0), 1),
                "zone_id": p.get("zone_id", ""),
                "url": p.get("url", ""),
                "rooms": p.get("rooms"),
                "size_m2": p.get("size_m2"),
                "first_seen": p.get("first_seen", ""),
            }
            for p in status_obj.top_properties
        ],
    }


# ── Radar & Properties endpoints ──────────────────────────────────────────────


@api.get("/radar")
async def get_radar(
    limit: int = 20,
    offset: int = 0,
    sort_by: str = "score",
    sort_dir: str = "desc",
    filter: str | None = None,
    portal: str | None = None,
):
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")

    limit = min(limit, 100)
    offset = max(offset, 0)

    return _scheduler_instance.get_radar(
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_dir=sort_dir,
        filter_by=filter,
        portal_filter=portal,
    )


@api.get("/dismissed")
async def get_dismissed():
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")
    return {"properties": _scheduler_instance.get_dismissed()}


@api.post("/dismiss")
async def dismiss_property(req: PropertyUid):
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")
    ok = _scheduler_instance.dismiss_property(req.uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Property not found")
    return {"ok": True, "uid": req.uid}


@api.post("/undismiss")
async def undismiss_property(req: PropertyUid):
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")
    ok = _scheduler_instance.undismiss_property(req.uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Property not found")
    return {"ok": True, "uid": req.uid}


@api.post("/mark-viewed")
async def mark_viewed(req: PropertyUid):
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")
    ok = _scheduler_instance.mark_viewed(req.uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Property not found")
    return {"ok": True, "uid": req.uid}


@api.post("/save-comment")
async def save_comment(req: CommentRequest):
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")
    ok = _scheduler_instance.save_comment(req.uid, req.comment)
    if not ok:
        raise HTTPException(status_code=404, detail="Property not found")
    return {"ok": True, "uid": req.uid}


# ── Schedule endpoints ────────────────────────────────────────────────────────


@api.get("/schedule")
async def get_schedule():
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")
    return _scheduler_instance.get_schedule_config()


@api.post("/schedule")
async def save_schedule(config: ScheduleConfig):
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")

    # Only save non-None fields
    validated = {k: v for k, v in config.model_dump().items() if v is not None}
    if validated:
        _scheduler_instance.save_schedule_config(validated)
    return {"ok": True}


@api.get("/summary")
async def get_summary():
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")
    summary = _scheduler_instance.get_last_summary()
    return summary or {"content": None, "sent_at": None}


# ── Manual trigger endpoints ──────────────────────────────────────────────────


@api.post("/run-scraping")
async def run_scraping():
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")
    threading.Thread(
        target=_scheduler_instance.run_scraping_now,
        daemon=True,
        name="manual-scraping",
    ).start()
    return {"ok": True, "message": "Scraping iniciado"}


@api.post("/run-gmail-check")
async def run_gmail_check():
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")
    threading.Thread(
        target=_scheduler_instance.run_gmail_check_now,
        daemon=True,
        name="manual-gmail",
    ).start()
    return {"ok": True, "message": "Gmail check iniciado"}


@api.post("/run-fotocasa-check")
async def run_fotocasa_check():
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")
    threading.Thread(
        target=_scheduler_instance.run_fotocasa_check_now,
        daemon=True,
        name="manual-fotocasa",
    ).start()
    return {"ok": True, "message": "Fotocasa check iniciado"}


@api.post("/run-summary")
async def run_summary():
    if _scheduler_instance is None:
        raise HTTPException(status_code=503, detail="Not ready")
    threading.Thread(
        target=_scheduler_instance.run_summary_now,
        daemon=True,
        name="manual-summary",
    ).start()
    return {"ok": True, "message": "Resumen iniciado"}


# ── Telegram webhook ──────────────────────────────────────────────────────────


@api.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    if _scheduler_instance is None:
        return {"ok": True}

    try:
        body = await request.json()
        message = body.get("message", {})
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = message.get("text", "")
        username = chat.get("username", "") or chat.get("first_name", "")

        if chat_id and text.startswith("/start"):
            _scheduler_instance._notifier.register_chat(chat_id, username)
            return {"ok": True, "registered": chat_id}
    except Exception as e:
        logger.debug("[telegram] Webhook error: %s", e)

    return {"ok": True}


# ── Incluir router API ────────────────────────────────────────────────────────
app.include_router(api)


# ── Frontend routes ───────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
@app.get("/smart-home/casita", response_class=HTMLResponse)
@app.get("/smart-home/casita/", response_class=HTMLResponse)
async def serve_frontend():
    html_path = STATIC_DIR / "casita.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(html_path, media_type="text/html")


# ── Telegram polling (background thread) ──────────────────────────────────────


def _telegram_polling() -> None:
    """Background thread that polls Telegram for /start commands."""
    import httpx

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

                if chat_id and text.startswith("/start") and _db_instance:
                    _db_instance.register_telegram_chat(chat_id, username)
                    logger.info(
                        "[main] Nuevo chat registrado via /start: %s (%s)",
                        chat_id,
                        username,
                    )
                    # Mensaje de bienvenida
                    httpx.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": "Bienvenido/a a Casita Sueños! Recibirás alertas de nuevas casas en el radar.",
                        },
                        timeout=10,
                    )
        except Exception as e:
            logger.debug("[main] Telegram polling error: %s", e)
        time.sleep(1)


# ── Bootstrap ─────────────────────────────────────────────────────────────────


def _init_scheduler():
    """Initialize scheduler and related components."""
    global _scheduler_instance, _db_instance

    from apify_client_wrapper import ApifyUsageTracker, IdealistaApifyClient
    from casita_scheduler import CasitaScheduler
    from database import Database
    from notifier import TelegramNotifier

    # Instanciar componentes
    db = Database(DB_PATH)
    _db_instance = db
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

    _scheduler_instance = scheduler

    # Notificar arranque (opt-in; desactivado por defecto para no spamear Telegram
    # en cada reinicio del contenedor)
    if NOTIFY_ON_STARTUP:
        radar_count = len(
            db.get_radar_properties(min_score=_ALERT_THRESHOLD, limit=500).get(
                "items", []
            )
        )
        notifier.send_status(
            f"🚀 Casita Sueños arrancado · {radar_count} casas en el radar"
        )
    else:
        logger.info(
            "[main] Notificación de arranque Telegram omitida "
            "(CASITA_NOTIFY_ON_STARTUP no activado)"
        )

    # Arrancar scheduler
    scheduler.start()
    logger.info("[main] Scheduler activo")

    return db


def main() -> None:
    _validate_config()
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    # ── Nombre del proceso ───────────────────────────────────────────────────
    _set_process_name()

    # ── Singleton: una sola instancia ────────────────────────────────────────
    from smart_home_common.singleton import ensure_singleton

    LOCK_PATH = os.environ.get("CASITA_LOCK_PATH", f"{DATA_DIR}/casita.lock")
    ensure_singleton(LOCK_PATH)

    logger.info("[main] ── Iniciando %s ──────────────────────────", PROCESS_NAME)

    # Inicializar scheduler en background
    db = _init_scheduler()

    # Arrancar polling de Telegram
    threading.Thread(
        target=_telegram_polling, daemon=True, name="telegram-polling"
    ).start()

    # Graceful shutdown
    def _shutdown(signum, frame):
        logger.info("[main] Señal %s recibida — apagando", signum)
        if _scheduler_instance:
            _scheduler_instance.stop()
        if db:
            db.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Arrancar servidor con uvicorn
    logger.info("[main] Servidor HTTP en puerto %d", STATUS_PORT)
    uvicorn.run(
        app,
        host="0.0.0.0",  # nosec B104 - internal container network
        port=STATUS_PORT,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
