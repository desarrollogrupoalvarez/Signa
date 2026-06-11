"""CRUD y helpers de áreas operativas (Depósitos)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from models.area import Area

_CODIGO_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


def get_by_id(db: "Session", area_id: int) -> "Area | None":
    from models.area import Area

    return db.query(Area).filter(Area.id == int(area_id)).first()


def get_by_codigo(db: "Session", codigo: str, *, active_only: bool = True) -> "Area | None":
    from models.area import Area

    c = (codigo or "").strip()
    if not c:
        return None
    q = db.query(Area).filter(Area.codigo == c)
    if active_only:
        q = q.filter(Area.activo.is_(True))
    return q.first()


def list_areas(db: "Session", *, active_only: bool = False) -> list:
    from models.area import Area

    q = db.query(Area).order_by(Area.orden, Area.codigo)
    if active_only:
        q = q.filter(Area.activo.is_(True))
    return q.all()


def validate_codigo(codigo: str) -> str:
    c = (codigo or "").strip()
    if not c or len(c) < 2:
        raise ValueError("codigo de área requerido (mínimo 2 caracteres)")
    if not _CODIGO_RE.match(c):
        raise ValueError("codigo inválido: solo letras, números, _, . y -")
    return c


def create_area(
    db: "Session",
    *,
    codigo: str,
    nombre: str,
    activo: bool = True,
    orden: int | None = None,
) -> "Area":
    from models.area import Area

    c = validate_codigo(codigo)
    if db.query(Area).filter(Area.codigo == c).first():
        raise ValueError(f"El código de área '{c}' ya existe")
    n = (nombre or c).strip() or c
    o = orden if orden is not None else (db.query(Area).count() + 1)
    area = Area(codigo=c, nombre=n, activo=activo, orden=o)
    db.add(area)
    db.flush()
    return area


def update_area(db: "Session", area: "Area", data: dict) -> "Area":
    if "codigo" in data and data["codigo"]:
        c = validate_codigo(data["codigo"])
        from models.area import Area

        existing = db.query(Area).filter(Area.codigo == c, Area.id != area.id).first()
        if existing:
            raise ValueError(f"El código de área '{c}' ya existe")
        area.codigo = c
    if "nombre" in data and data["nombre"] is not None:
        n = str(data["nombre"]).strip()
        if not n:
            raise ValueError("nombre requerido")
        area.nombre = n
    if "activo" in data:
        area.activo = bool(data["activo"])
    if "orden" in data and data["orden"] is not None:
        area.orden = int(data["orden"])
    db.flush()
    return area


def delete_area(db: "Session", area: "Area") -> None:
    from models.apartado import Apartado

    n = db.query(Apartado).filter(Apartado.area_id == area.id).count()
    if n:
        raise ValueError("No se puede eliminar un área con apartados asignados")
    db.delete(area)


def asignables_tree(db: "Session", apartados: list) -> list[dict]:
    """Agrupa apartados asignables por área para UI de usuarios."""
    from models.area import Area

    by_area: dict[int | None, list] = {}
    for ap in apartados:
        aid = getattr(ap, "area_id", None)
        by_area.setdefault(aid, []).append(ap.to_brief() if hasattr(ap, "to_brief") else ap)

    areas = list_areas(db)
    area_map = {a.id: a for a in areas}
    out: list[dict] = []
    seen_area_ids: set[int] = set()

    for area in areas:
        aps = by_area.get(area.id, [])
        if not aps:
            continue
        seen_area_ids.add(area.id)
        out.append({**area.to_brief(), "apartados": sorted(aps, key=lambda x: (x.get("orden", 0), x.get("codigo", "")))})

    orphan = by_area.get(None, [])
    if orphan:
        out.append(
            {
                "id": None,
                "codigo": "_sin_area",
                "nombre": "Sin área",
                "activo": True,
                "orden": 9999,
                "apartados": sorted(orphan, key=lambda x: (x.get("orden", 0), x.get("codigo", ""))),
            }
        )

    for aid, aps in by_area.items():
        if aid is None or aid in seen_area_ids:
            continue
        area = area_map.get(aid)
        if not area:
            continue
        out.append({**area.to_brief(), "apartados": sorted(aps, key=lambda x: (x.get("orden", 0), x.get("codigo", "")))})

    out.sort(key=lambda x: (x.get("orden", 0), x.get("codigo", "")))
    return out
