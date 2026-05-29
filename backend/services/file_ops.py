"""Operaciones de archivo con reintentos (carpetas compartidas / SMB)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger("remitos")

_RETRYABLE = frozenset({13, 16, 22, 26, 32})  # EACCES, EBUSY, EINVAL, ETXTBSY, EPIPE (platform-dependent)


def safe_unlink(path: Path, *, retries: int = 3, delay: float = 0.35) -> bool:
    """Elimina un archivo con reintentos breves ante bloqueos de red."""
    for attempt in range(retries):
        try:
            if path.is_file():
                path.unlink()
            return True
        except OSError as ex:
            err = getattr(ex, "errno", None)
            if attempt < retries - 1 and err in _RETRYABLE:
                time.sleep(delay * (attempt + 1))
                continue
            logger.warning("safe_unlink falló | %s | %s", path, ex)
            return False
    return False


def safe_copy2(src: Path, dst: Path, *, retries: int = 3, delay: float = 0.35) -> bool:
    import shutil

    for attempt in range(retries):
        try:
            shutil.copy2(src, dst)
            return True
        except OSError as ex:
            err = getattr(ex, "errno", None)
            if attempt < retries - 1 and err in _RETRYABLE:
                time.sleep(delay * (attempt + 1))
                continue
            logger.warning("safe_copy2 falló | %s -> %s | %s", src, dst, ex)
            return False
    return False
