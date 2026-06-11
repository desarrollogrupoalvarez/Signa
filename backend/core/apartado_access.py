"""
Apartados efectivos según rol, asignación por área (user_area) y restricción fina (user_apartado).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from models.apartado import Apartado
    from models.user import User


def _is_superadmin(role_name: str | None) -> bool:
    return (role_name or "").strip() == "superadmin"


def effective_apartados_for_user(
    db: "Session", user: "User | None", role_name: str | None
) -> list["Apartado"]:
    from models.apartado import Apartado

    if not user:
        return []
    r = (role_name or (user.role.name if user.role else None) or "").strip()
    if _is_superadmin(r):
        return (
            db.query(Apartado)
            .filter(Apartado.activo.is_(True))
            .order_by(Apartado.orden, Apartado.codigo)
            .all()
        )

    assigned_areas = list(user.areas or [])
    assigned_apartados = [a for a in (user.apartados or []) if a.activo]
    area_ids = {int(a.id) for a in assigned_areas if getattr(a, "id", None)}

    effective_ids: set[int] = set()

    for area in assigned_areas:
        area_aps = (
            db.query(Apartado)
            .filter(Apartado.area_id == area.id, Apartado.activo.is_(True))
            .all()
        )
        explicit = [a for a in assigned_apartados if a.area_id == area.id]
        if explicit:
            effective_ids.update(int(a.id) for a in explicit)
        else:
            effective_ids.update(int(a.id) for a in area_aps)

    for ap in assigned_apartados:
        if ap.area_id is None or int(ap.area_id) not in area_ids:
            effective_ids.add(int(ap.id))

    if not effective_ids:
        return []

    rows = (
        db.query(Apartado)
        .filter(Apartado.id.in_(effective_ids), Apartado.activo.is_(True))
        .all()
    )
    rows.sort(key=lambda a: (
        (a.area.orden if a.area else 9999),
        (a.area.codigo if a.area else ""),
        a.orden,
        a.codigo,
    ))
    return rows


def apartado_codes_for_user(db: "Session", user: "User | None", role_name: str | None) -> set[str]:
    return {a.codigo for a in effective_apartados_for_user(db, user, role_name)}


def area_codes_for_user(db: "Session", user: "User | None", role_name: str | None) -> set[str]:
    if not user:
        return set()
    r = (role_name or (user.role.name if user.role else None) or "").strip()
    if _is_superadmin(r):
        from models.area import Area

        return {a.codigo for a in db.query(Area).filter(Area.activo.is_(True)).all()}
    return {a.codigo for a in (user.areas or []) if a.activo}


def apartado_codes_from_payload(payload: dict | None) -> set[str] | None:
    if not payload:
        return set()
    a = payload.get("apartados")
    if not isinstance(a, list):
        return None
    return {str(x) for x in a if (x and str(x).strip())}


def area_codes_from_payload(payload: dict | None) -> set[str] | None:
    if not payload:
        return set()
    a = payload.get("areas")
    if not isinstance(a, list):
        return None
    return {str(x) for x in a if (x and str(x).strip())}
