#!/usr/bin/env python
"""
Seed script — inserts default permissions, roles and a superadmin user.

Usage:
  python seed.py

The superadmin password is read from SUPERADMIN_PASSWORD env var or defaults to Admin1234!
Run AFTER migrate.py.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.database import db_session
from core.permissions import PERMISSIONS
from core.security import hash_password
from models.apartado import Apartado
from models.permission import Permission
from models.role import Role, role_permissions
from models.user import User

# ── Role catalogue ────────────────────────────────────────────────────────────
ROLES = [
    (
        "superadmin",
        "Super administrador — acceso total al sistema",
        [p[0] for p in PERMISSIONS],
    ),
    (
        "firmante",
        "Operador de firma — gestiona y firma remitos",
        [
            "pendientes:ver",
            "pendientes:firmar",
            "digitalizados:ver",
            "digitalizados:ver_todo",
            "digitalizados:ver_archivo",
        ],
    ),
    (
        "consulta",
        "Solo lectura — visualiza remitos sin poder firmar",
        [
            "pendientes:ver",
            "digitalizados:ver",
            "digitalizados:ver_todo",
            "digitalizados:ver_archivo",
        ],
    ),
    (
        "administrador",
        "Administra apartados asignados; ve y busca pendientes/firmados del apartado",
        [
            "apartados:editar",
            "pendientes:ver",
            "pendientes:ver_todos",
            "digitalizados:ver",
            "digitalizados:ver_todo",
            "digitalizados:ver_archivo",
            "registros:ver",
        ],
    ),
]


def seed():
    with db_session() as db:
        from services.apartados import seed_default_apartados_from_legacy_if_empty

        seed_default_apartados_from_legacy_if_empty(db)
        perm_map: dict[str, Permission] = {}
        for name, desc, resource, action in PERMISSIONS:
            perm = db.query(Permission).filter(Permission.name == name).first()
            if not perm:
                perm = Permission(name=name, description=desc, resource=resource, action=action)
                db.add(perm)
                print(f"  + permission: {name}")
            else:
                perm.description = desc
                perm.resource = resource
                perm.action = action
            perm_map[name] = perm
        db.flush()

        role_map: dict[str, Role] = {}
        for role_name, role_desc, perm_names in ROLES:
            role = db.query(Role).filter(Role.name == role_name).first()
            if not role:
                role = Role(name=role_name, description=role_desc)
                db.add(role)
                print(f"  + role: {role_name}")
            role.permissions = [perm_map[n] for n in perm_names if n in perm_map]
            role_map[role_name] = role
        db.flush()

        superadmin_password = os.environ.get("SUPERADMIN_PASSWORD", "Admin1234!")

        existing = db.query(User).filter(User.username == "superadmin").first()
        if not existing:
            user = User(
                username="superadmin",
                password_hash=hash_password(superadmin_password),
                role_id=role_map["superadmin"].id,
                is_active=True,
            )
            db.add(user)
            print(f"  + user: superadmin  (password: {superadmin_password})")
        else:
            print("  · user superadmin already exists — skipped")

        aps = db.query(Apartado).order_by(Apartado.orden, Apartado.codigo).all()
        from models.area import Area

        default_area = db.query(Area).filter(Area.codigo == "daudet").first()
        if aps and default_area:
            for u in db.query(User).all():
                if u.role and u.role.name == "superadmin":
                    continue
                u.areas = [default_area]
                u.apartados = []
            print(f"  · user_area: asignada area daudet a usuarios (excepto superadmin)")

    print("\nSeed completed OK")


if __name__ == "__main__":
    print("Seeding database…")
    seed()
