"""Autorización de carpetas en la vista Digitalizados."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.permissions import PERM_DIGITALIZADOS_VER_TODO, user_puede_ver_todo_digitalizado
from models.role_digitalizado_carpeta import RoleDigitalizadoCarpeta

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _norm(s: str | None) -> str:
    return (s or "").strip().upper()


def parse_firmado_path(nombre: str) -> tuple[str, str | None]:
    """
    Extrae carpeta (depósito) y categoría de doc.nombre (prefijo/DEPO/CAT/archivo).
    Retorna (carpeta, categoria) con categoria None si el archivo está directo bajo depósito.
    """
    norm = (nombre or "").strip().replace("\\", "/")
    parts = [p for p in norm.split("/") if p]
    if len(parts) < 2:
        return "", None
    rest = parts[1:]
    if len(rest) == 1:
        return rest[0], None
    carpeta = rest[0]
    if len(rest) == 2:
        return carpeta, None
    return carpeta, rest[1]


def carpetas_permitidas(db: "Session", role_id: int) -> list[RoleDigitalizadoCarpeta]:
    return (
        db.query(RoleDigitalizadoCarpeta)
        .filter(RoleDigitalizadoCarpeta.role_id == int(role_id))
        .all()
    )


def _apartado_id_for_doc(doc: dict[str, Any], codigo_to_id: dict[str, int]) -> int | None:
    codigo = (doc.get("apartado_codigo") or doc.get("origen") or "").strip()
    if not codigo:
        return None
    return codigo_to_id.get(codigo)


def doc_en_carpeta_permitida(
    doc: dict[str, Any],
    *,
    role_id: int,
    db: "Session",
    perms: set[str],
    codigo_to_id: dict[str, int] | None = None,
    allowed_rows: list[RoleDigitalizadoCarpeta] | None = None,
) -> bool:
    if user_puede_ver_todo_digitalizado(perms):
        return True
    rows = allowed_rows if allowed_rows is not None else carpetas_permitidas(db, role_id)
    if not rows:
        return False
    if codigo_to_id is None:
        from models.apartado import Apartado

        codigo_to_id = {
            (a.codigo or "").strip(): int(a.id)
            for a in db.query(Apartado).all()
        }
    apartado_id = _apartado_id_for_doc(doc, codigo_to_id)
    if apartado_id is None:
        return False
    carpeta, categoria = parse_firmado_path(doc.get("nombre") or "")
    if not carpeta:
        return False
    cu = _norm(carpeta)
    cat_u = _norm(categoria) if categoria else ""
    for row in rows:
        if int(row.apartado_id) != int(apartado_id):
            continue
        if _norm(row.carpeta) != cu:
            continue
        row_cat = _norm(row.categoria)
        if not row_cat:
            return True
        if cat_u and row_cat == cat_u:
            return True
    return False


def filtrar_firmados_por_carpeta(
    items: list[dict[str, Any]],
    *,
    role_id: int,
    db: "Session",
    perms: set[str],
) -> list[dict[str, Any]]:
    if user_puede_ver_todo_digitalizado(perms):
        return items
    rows = carpetas_permitidas(db, role_id)
    if not rows:
        return []
    from models.apartado import Apartado

    codigo_to_id = {
        (a.codigo or "").strip(): int(a.id)
        for a in db.query(Apartado).all()
    }
    return [
        it
        for it in items
        if doc_en_carpeta_permitida(
            it,
            role_id=role_id,
            db=db,
            perms=perms,
            codigo_to_id=codigo_to_id,
            allowed_rows=rows,
        )
    ]


def nombre_firmado_permitido(
    nombre: str,
    *,
    role_id: int,
    db: "Session",
    perms: set[str],
    apartado_codigo: str | None = None,
) -> bool:
    doc = {"nombre": nombre, "apartado_codigo": apartado_codigo, "origen": apartado_codigo}
    return doc_en_carpeta_permitida(doc, role_id=role_id, db=db, perms=perms)


def listar_carpetas_disponibles(db: "Session") -> list[dict]:
    from models.apartado import Apartado
    from models.area import Area
    from services.apartado_paths import depositos_from_json

    out: list[dict] = []
    rows = (
        db.query(Apartado)
        .outerjoin(Area, Apartado.area_id == Area.id)
        .filter(Apartado.activo.is_(True))
        .order_by(Area.orden, Apartado.orden, Apartado.codigo)
        .all()
    )
    for a in rows:
        deps = depositos_from_json(a.depositos_config)
        depositos = []
        for dep in deps:
            categorias = [{"nombre": c.nombre} for c in (dep.categorias or ())]
            depositos.append({"carpeta": dep.carpeta, "categorias": categorias})
        out.append(
            {
                "apartado_id": a.id,
                "apartado_codigo": a.codigo,
                "apartado_nombre": a.nombre,
                "area_id": a.area_id,
                "area_codigo": a.area.codigo if a.area else None,
                "area_nombre": a.area.nombre if a.area else None,
                "depositos": depositos,
            }
        )
    return out
