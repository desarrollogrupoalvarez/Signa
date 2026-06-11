"""
Rutas efectivas: apartados por modo_flujo o, si faltan, variables de entorno como fallback.

NOTA: `app_settings` fue eliminado por decision de diseno.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from config import Config

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_lock = threading.RLock()
_cache: dict[str, str] | None = None


def invalidate_cache() -> None:
    with _lock:
        global _cache
        _cache = None


def _norm_ruta(s: str) -> str:
    t = (s or "").strip()
    return os.path.normpath(t) if t else t


def _is_unc_path(path: Path | str) -> bool:
    s = str(path).replace("/", "\\")
    return s.startswith("\\\\")


def resolve_storage_path(path_str: str | None) -> Path:
    """
    Ruta absoluta para bandeja/destino.
    Relativas: primero respecto al cwd del proceso (p. ej. backend/ al usar server.py),
    luego raiz del proyecto — debe coincidir con donde el watcher ya encuentra pendientes.

    Rutas UNC (\\\\servidor\\share): no usa resolve()/exists() para evitar cuelgues en red.
    """
    from config import Config

    raw = (path_str or "").strip()
    if not raw:
        return Path()
    p = Path(raw)
    if p.is_absolute():
        if _is_unc_path(p):
            return Path(os.path.normpath(str(p)))
        try:
            return p.resolve()
        except OSError:
            return p
    cand_cwd = Path.cwd() / p
    cand_base = Config.BASE_DIR / p
    if _is_unc_path(cand_cwd):
        return Path(os.path.normpath(str(cand_cwd)))
    try:
        cand_cwd_res = cand_cwd.resolve()
    except OSError:
        cand_cwd_res = cand_cwd
    try:
        cand_base_res = cand_base.resolve()
    except OSError:
        cand_base_res = cand_base
    try:
        if cand_cwd_res.exists():
            return cand_cwd_res
    except OSError:
        pass
    try:
        if cand_base_res.exists():
            return cand_base_res
    except OSError:
        pass
    return cand_cwd_res


def get_legacy_merged(db: "Session | None" = None) -> dict[str, str]:
    """
    Fallback legacy: solo env (sin pasar por tablas `apartados`).
    Util para el seed inicial si la BD aun no tiene apartados creados.
    """
    bandeja = (Config.BANDEJA_ENTRADA or "").strip()
    trans_root = (Config.TRANSFERENCIAS_ROOT or "").strip()
    b_ing = (Config.BANDEJA_INGRESOS or "").strip()
    d_ing = (Config.DESTINO_INGRESOS or "").strip()

    return {
        "bandeja_entrada": _norm_ruta(bandeja),
        "transferencias_root": _norm_ruta(trans_root),
        "bandeja_ingresos": _norm_ruta(b_ing),
        "destino_ingresos": _norm_ruta(d_ing),
    }


def _default_apartado_for_modo(db: "Session", modo_flujo: str):
    from models.apartado import Apartado
    from models.area import Area

    return (
        db.query(Apartado)
        .outerjoin(Area, Apartado.area_id == Area.id)
        .filter(Apartado.modo_flujo == modo_flujo, Apartado.activo.is_(True))
        .order_by(Area.orden, Apartado.orden, Apartado.codigo)
        .first()
    )


def get_resolved_paths(db: "Session | None" = None) -> dict[str, str]:
    """
    bandeja (TRA), transferencias, bandeja IN y destino IN.
    Usa el primer apartado activo por modo_flujo (ordenado por area); si no, env.
    """
    global _cache
    with _lock:
        if db is None and _cache is not None:
            return dict(_cache)

        if db is not None:
            t = _default_apartado_for_modo(db, "transferencia")
            i = _default_apartado_for_modo(db, "ingreso")
            if t and i:
                result = {
                    "bandeja_entrada": _norm_ruta(t.bandeja_path),
                    "transferencias_root": _norm_ruta(t.destino_path),
                    "bandeja_ingresos": _norm_ruta(i.bandeja_path),
                    "destino_ingresos": _norm_ruta(i.destino_path),
                }
                _cache = result
                return result

        result = get_legacy_merged(db)
        if db is not None:
            _cache = result
        return result


def scan_roots_for_apartado(apartado) -> list[Path]:
    """Carpetas de destino (firmados). No escanea bandeja para no mezclar con pendientes."""
    from services.apartado_paths import destino_deposito_root, parse_depositos

    seen: set[str] = set()
    roots: list[Path] = []

    def add(path: Path | None) -> None:
        if not path:
            return
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            return
        seen.add(key)
        roots.append(path)

    dest = resolve_storage_path(getattr(apartado, "destino_path", None))
    add(dest)
    for dep in parse_depositos(apartado):
        if dest:
            add(destino_deposito_root(dest, dep.carpeta))
    return roots
