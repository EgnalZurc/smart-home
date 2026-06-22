"""Limpieza automática de datos innecesarios.

Se ejecuta como tarea periódica diaria dentro del backend.
Elimina:
- Logs antiguos de Zigbee2MQTT (> 3 días)
- Cualquier archivo temporal en /app/data que no sea necesario
"""

import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Directorio de logs de Zigbee2MQTT (dentro del contenedor si se monta, o accesible vía volumen)
Z2M_LOG_DIR = os.environ.get("Z2M_LOG_DIR", "/app/data/log")
# Días de retención de logs
LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", "3"))
# Intervalo de ejecución (24h en segundos)
CLEANUP_INTERVAL = 86400


def cleanup_old_logs(log_dir: str, max_age_days: int) -> int:
    """Elimina directorios/archivos de log más antiguos que max_age_days.

    Zigbee2MQTT crea carpetas con formato YYYY-MM-DD.HH-MM-SS/ con un log.log dentro.
    """
    removed = 0
    log_path = Path(log_dir)

    if not log_path.exists():
        logger.debug("Directorio de logs no encontrado: %s", log_dir)
        return 0

    max_age_seconds = max_age_days * 86400
    now = time.time()

    for entry in log_path.iterdir():
        try:
            # Comprobar edad por fecha de modificación
            entry_mtime = entry.stat().st_mtime
            age = now - entry_mtime

            if age > max_age_seconds:
                if entry.is_dir():
                    # Borrar directorio de log completo
                    for file in entry.iterdir():
                        file.unlink()
                    entry.rmdir()
                else:
                    entry.unlink()
                removed += 1
                logger.info("Eliminado log antiguo: %s (%.0f días)", entry.name, age / 86400)
        except Exception as e:
            logger.warning("Error eliminando %s: %s", entry, e)

    return removed


def run_cleanup():
    """Ejecuta todas las tareas de limpieza."""
    logger.info("=== Ejecutando limpieza diaria ===")

    # 1. Logs de Zigbee2MQTT
    removed = cleanup_old_logs(Z2M_LOG_DIR, LOG_RETENTION_DAYS)
    logger.info("Zigbee2MQTT: %d logs antiguos eliminados (retención: %d días)", removed, LOG_RETENTION_DAYS)

    logger.info("=== Limpieza diaria completada ===")


class CleanupScheduler:
    """Ejecuta la limpieza periódicamente en un thread."""

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        """Inicia el scheduler de limpieza."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler de limpieza iniciado (cada %dh, retención %d días)",
                    CLEANUP_INTERVAL // 3600, LOG_RETENTION_DAYS)

    def stop(self):
        """Detiene el scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        """Loop que ejecuta limpieza cada 24h. Ejecuta una vez al arrancar."""
        # Ejecutar limpieza al arrancar (tras 60s de gracia)
        time.sleep(60)
        if self._running:
            run_cleanup()

        # Luego cada 24h
        while self._running:
            time.sleep(CLEANUP_INTERVAL)
            if self._running:
                run_cleanup()
