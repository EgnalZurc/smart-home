"""
Garantiza que solo corre una instancia del proceso casita-suenos.

Usa un fichero de bloqueo con flock (Linux/Raspberry) o CreateMutex (Windows)
según la plataforma. Si ya hay otra instancia corriendo, termina con código 1.

Por qué no confiamos solo en Docker:
- docker-compose restart puede provocar un overlap breve entre contenedores
- El scheduler tiene jobs largos; un segundo arranque durante un scraping
  duplicaría peticiones y corrompería la DB

Uso:
    from singleton import ensure_singleton
    ensure_singleton("/app/data/casita.lock")
"""

from __future__ import annotations

import logging
import os
import sys
import platform
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_singleton(lock_path: str) -> None:
    """
    Intenta obtener un bloqueo exclusivo sobre `lock_path`.
    Si otra instancia ya tiene el bloqueo, escribe un log de error y termina el proceso.
    El bloqueo se libera automáticamente cuando el proceso termina (incluido kill).
    """
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)

    if platform.system() == "Windows":
        _ensure_singleton_windows(lock_path)
    else:
        _ensure_singleton_unix(lock_path)


def _ensure_singleton_unix(lock_path: str) -> None:
    """Implementación Unix usando fcntl.flock — funciona en Raspberry Pi (Linux)."""
    import fcntl

    try:
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Escribir el PID para diagnóstico
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        # Guardar referencia para que no se cierre (y libere el lock) al GC
        _hold_lock_ref(lock_file)
        logger.info("[singleton] Bloqueo obtenido en %s (PID %d)", lock_path, os.getpid())
    except (IOError, OSError):
        logger.error(
            "[singleton] Ya hay otra instancia de casita-suenos corriendo. "
            "Fichero de bloqueo: %s — terminando.",
            lock_path,
        )
        sys.exit(1)


def _ensure_singleton_windows(lock_path: str) -> None:
    """Implementación Windows usando un fichero con open() exclusivo."""
    try:
        # En Windows, abrir con 'x' falla si el fichero ya existe
        # Alternativa: intentar abrir con O_CREAT | O_EXCL
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        handle = os.fdopen(fd, "w")
        handle.write(str(os.getpid()))
        handle.flush()
        _hold_lock_ref(handle)

        import atexit
        atexit.register(_cleanup_lock_windows, lock_path)
        logger.info("[singleton] Bloqueo obtenido en %s (PID %d)", lock_path, os.getpid())
    except FileExistsError:
        # Comprobar si el proceso aún existe
        try:
            pid = int(Path(lock_path).read_text().strip())
            if not _pid_alive(pid):
                # Proceso muerto — limpiar lock huérfano y reintentar
                os.remove(lock_path)
                _ensure_singleton_windows(lock_path)
                return
        except Exception:
            pass
        logger.error(
            "[singleton] Ya hay otra instancia corriendo (lock: %s). Terminando.",
            lock_path,
        )
        sys.exit(1)


def _cleanup_lock_windows(lock_path: str) -> None:
    try:
        os.remove(lock_path)
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    """Comprueba si un PID sigue vivo."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# Mantiene la referencia al fichero abierto para evitar que el GC lo cierre
_lock_file_handle = None


def _hold_lock_ref(f) -> None:
    global _lock_file_handle
    _lock_file_handle = f
