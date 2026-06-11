"""Permisos de gestión de apartados (crear vs editar con alcance)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, Query
    from models.apartado import Apartado
    from models.user import User

PERM_GESTIONAR = "apartados:gestionar"
PERM_CREAR = "apartados:crear"
PERM_EDITAR = "apartados:editar"
PERM_RUTAS_LEGACY = "configuracion:rutas"


def user_puede_ver_todos_pendientes(perms: set[str]) -> bool:
    from core.permissions import user_puede_ver_todos_pendientes as _fn

    return _fn(perms)


def permissions_from_payload(payload: dict | None) -> set[str]:
    return set((payload or {}).get("permissions") or [])


def is_superadmin(role_name: str | None) -> bool:
    return (role_name or "").strip() == "superadmin"


def can_reveal_file_location(role_name: str | None) -> bool:
    r = (role_name or "").strip()
    return r in ("superadmin", "administrador")


def can_gestionar_todos(perms: set[str], role_name: str | None) -> bool:
    return is_superadmin(role_name) or PERM_GESTIONAR in perms


def can_crear_apartados(perms: set[str], role_name: str | None) -> bool:
    return can_gestionar_todos(perms, role_name) or PERM_CREAR in perms


def can_editar_apartados(perms: set[str], role_name: str | None) -> bool:
    return (
        can_gestionar_todos(perms, role_name)
        or PERM_EDITAR in perms
        or PERM_RUTAS_LEGACY in perms
    )


def can_list_apartados_admin(perms: set[str], role_name: str | None) -> bool:
    return can_editar_apartados(perms, role_name) or PERM_CREAR in perms


def apartado_ids_asignados(user: "User | None") -> set[int]:
    if not user:
        return set()
    try:
        return {int(a.id) for a in (user.apartados or []) if getattr(a, "id", None)}
    except (TypeError, ValueError):
        return set()


def user_puede_editar_apartado(
    db: "Session",
    user: "User",
    role_name: str | None,
    perms: set[str],
    apartado_id: int,
) -> bool:
    if can_gestionar_todos(perms, role_name) or PERM_RUTAS_LEGACY in perms:
        return True
    if PERM_EDITAR not in perms:
        return False
    return int(apartado_id) in apartado_ids_asignados(user)


def query_apartados_admin(
    db: "Session",
    user: "User",
    role_name: str | None,
    perms: set[str],
) -> "Query":
    from models.apartado import Apartado
    from models.area import Area

    q = (
        db.query(Apartado)
        .outerjoin(Area, Apartado.area_id == Area.id)
        .order_by(Area.orden, Apartado.orden, Apartado.codigo)
    )
    if (
        can_gestionar_todos(perms, role_name)
        or PERM_CREAR in perms
        or PERM_RUTAS_LEGACY in perms
    ):
        return q
    if PERM_EDITAR in perms:
        ids = apartado_ids_asignados(user)
        if not ids:
            return q.filter(Apartado.id < 0)
        return q.filter(Apartado.id.in_(ids))
    return q.filter(Apartado.id < 0)


def query_apartados_asignables(
    db: "Session",
    user: "User",
    role_name: str | None,
    perms: set[str],
) -> "Query":
    """Lista para asignar apartados a usuarios (checkboxes en admin)."""
    from models.apartado import Apartado
    from models.area import Area

    q = (
        db.query(Apartado)
        .outerjoin(Area, Apartado.area_id == Area.id)
        .filter(Apartado.activo.is_(True))
        .order_by(Area.orden, Apartado.orden, Apartado.codigo)
    )
    if can_gestionar_todos(perms, role_name):
        return q
    if PERM_EDITAR in perms:
        ids = apartado_ids_asignados(user)
        if not ids:
            return q.filter(Apartado.id < 0)
        return q.filter(Apartado.id.in_(ids))
    return q
