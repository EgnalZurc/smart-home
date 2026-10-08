"""
Ensure only a single instance of a process runs at a time.

Uses a lock file via flock (Linux/Raspberry) or an exclusive open (Windows)
depending on the platform. If another instance already holds the lock, the
current process exits with code 1.

Why not rely on Docker alone:
- docker-compose restart can cause a brief overlap between containers
- A scheduler with long-running jobs would, on a second startup during a
  scraping run, duplicate requests and corrupt the DB

Usage:
    from smart_home_common.singleton import ensure_singleton

    ensure_singleton("/app/data/casita.lock")
"""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_singleton(lock_path: str) -> None:
    """
    Acquire an exclusive lock on `lock_path`.

    If another instance already holds the lock, log an error and terminate the
    process. The lock is released automatically when the process exits
    (including on kill).
    """
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)

    if platform.system() == "Windows":
        _ensure_singleton_windows(lock_path)
    else:
        _ensure_singleton_unix(lock_path)


def _ensure_singleton_unix(lock_path: str) -> None:
    """Unix implementation using fcntl.flock — works on the Raspberry Pi (Linux)."""
    import fcntl

    try:
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Write the PID for diagnostics
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        # Keep a reference so the GC does not close the file (and release the lock)
        _hold_lock_ref(lock_file)
        logger.info("[singleton] Lock acquired on %s (PID %d)", lock_path, os.getpid())
    except OSError:
        logger.error(
            "[singleton] Another instance is already running. Lock file: %s — terminating.",
            lock_path,
        )
        sys.exit(1)


def _ensure_singleton_windows(lock_path: str) -> None:
    """Windows implementation using an exclusive open()."""
    try:
        # On Windows, opening with O_CREAT | O_EXCL fails if the file already exists
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        handle = os.fdopen(fd, "w")
        handle.write(str(os.getpid()))
        handle.flush()
        _hold_lock_ref(handle)

        import atexit

        atexit.register(_cleanup_lock_windows, lock_path)
        logger.info("[singleton] Lock acquired on %s (PID %d)", lock_path, os.getpid())
    except FileExistsError:
        # Check whether the process still exists
        try:
            pid = int(Path(lock_path).read_text().strip())
            if not _pid_alive(pid):
                # Dead process — clean the orphaned lock and retry
                os.remove(lock_path)
                _ensure_singleton_windows(lock_path)
                return
        except Exception:
            logger.debug("[singleton] Could not read/validate existing lock file")
        logger.error(
            "[singleton] Another instance is already running (lock: %s). Terminating.",
            lock_path,
        )
        sys.exit(1)


def _cleanup_lock_windows(lock_path: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(lock_path)


def _pid_alive(pid: int) -> bool:
    """Return True if the given PID is still alive."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# Keeps a reference to the open lock file so the GC does not close it
_lock_file_handle = None


def _hold_lock_ref(f) -> None:
    global _lock_file_handle
    _lock_file_handle = f
