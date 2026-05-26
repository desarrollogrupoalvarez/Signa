"""
Códigos de apartado permitidos según rol y asignación en `user_apartado`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from models.user import User


def apartado_codes_for_user(db: "Session", user: "User | None", role_name: str | None) -> set[str]:
    from models.apartado import Apartado

    if not user:
        return set()
    r = (role_name or (user.role.name if user.role else None) or "").strip()
    if r == "superadmin":
        q = db.query(Apartado).filter(Apartado.activo.is_(True))
        return {a.codigo for a in q.all()}
    if not user.apartados:
        return set()
    return {a.codigo for a in user.apartados if a.activo}


def apartado_codes_from_payload(payload: dict | None) -> set[str] | None:
    """
    Si el token incluye `apartados` (lista de códigos), devuelve un set; si no, None
    (el caller deberá resolver desde BD).
    """
    if not payload:
        return set()
    a = payload.get("apartados")
    if not isinstance(a, list):
        return None
    return {str(x) for x in a if (x and str(x).strip())}
