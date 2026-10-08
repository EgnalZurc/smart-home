"""Atomic JSON file persistence helpers.

Writing JSON state with a plain ``open(path, "w")`` / ``json.dump`` (or
``Path.write_text``) is not crash-safe: a process that dies mid-write leaves a
truncated, unparseable file on disk and the previous good state is lost.

``atomic_write_json`` avoids this by writing to a temporary file in the SAME
directory as the target, flushing it to disk, and then renaming it over the
target with ``os.replace()``. ``os.replace`` is atomic on both POSIX and
Windows, so a crash at any point leaves either the old complete file or the new
complete file -- never a half-written one. The temp file must live on the same
filesystem as the target for the rename to be atomic, hence ``dir=target.parent``.

This generalizes the pattern hardened for vacaciones-service in PR #82 so every
service can share one implementation instead of re-deriving it.
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["atomic_write_json", "atomic_read_json"]


def atomic_write_json(
    path: str | os.PathLike[str],
    data: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
    sort_keys: bool = False,
) -> None:
    """Serialize ``data`` as JSON and write it to ``path`` atomically.

    Writes to a temporary file in the target's directory, fsyncs it, then
    atomically renames it over the target. The parent directory is created if
    missing. On any error the stray temp file is removed and the exception
    propagates, leaving the previous file (if any) untouched.

    Args:
        path: Destination file path.
        data: Any JSON-serializable object.
        indent: ``json.dump`` indent (``None`` for the most compact form).
        ensure_ascii: Passed through to ``json.dump``. Defaults to ``False`` so
            non-ASCII text (e.g. Spanish accents) is written verbatim.
        sort_keys: Passed through to ``json.dump``.

    Raises:
        OSError: If the directory cannot be created or the file cannot be
            written/renamed.
        TypeError / ValueError: If ``data`` is not JSON-serializable.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            temp_path = f.name
            json.dump(
                data,
                f,
                ensure_ascii=ensure_ascii,
                indent=indent,
                sort_keys=sort_keys,
            )
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, target)  # atomic on POSIX and Windows
        temp_path = None
    finally:
        # If replace never ran (exception during write), drop the stray temp file.
        if temp_path is not None and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as e:
                logger.warning("Could not remove temp file %s: %s", temp_path, e)


def atomic_read_json(
    path: str | os.PathLike[str],
    *,
    default: Any = None,
) -> Any:
    """Read and parse a JSON file written by :func:`atomic_write_json`.

    Args:
        path: Source file path.
        default: Value returned when the file does not exist. If left as the
            sentinel ``None`` and the file is missing, ``None`` is returned.

    Returns:
        The parsed JSON content, or ``default`` when the file is absent.

    Raises:
        json.JSONDecodeError: If the file exists but is not valid JSON.
        OSError: If the file exists but cannot be read.
    """
    source = Path(path)
    if not source.exists():
        return default
    return json.loads(source.read_text(encoding="utf-8"))
