"""Compat: delegación a apartado_paths (rutas legacy + inferencia)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from services.apartado_paths import (
    bandeja_sin_firmar,
    destino_deposito_root,
    deposito_por_fuente,
    resolve_deposito_carpeta,
)

if TYPE_CHECKING:
    from models.apartado import Apartado


def bandeja_dir_for_fuente(bandeja_root: Path, tango_fuente: str | None, apartado: "Apartado") -> Path:
    """Bandeja pendiente: {deposito}/Sin Firmar según config del apartado."""
    dep = deposito_por_fuente(apartado, tango_fuente)
    carpeta = dep.carpeta if dep else resolve_deposito_carpeta(apartado, ruta=None, tango_fuente=tango_fuente)
    return bandeja_sin_firmar(bandeja_root, carpeta)


def transferencias_segment_root(
    destino_root: Path,
    apartado: "Apartado",
    tango_fuente: str | None = None,
    *,
    ruta_pendiente: str | Path | None = None,
) -> Path:
    """Raíz bajo destino para un depósito (antes TRANSFERENCIAS_*)."""
    carpeta = resolve_deposito_carpeta(
        apartado,
        ruta=ruta_pendiente,
        tango_fuente=tango_fuente,
    )
    return destino_deposito_root(destino_root, carpeta)
