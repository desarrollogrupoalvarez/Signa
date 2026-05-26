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
from core.security import hash_password
from models.apartado import Apartado
from models.permission import Permission
from models.role import Role, role_permissions
from models.user import User

# ── Permission catalogue ──────────────────────────────────────────────────────
#  (name, description, resource, action)
PERMISSIONS = [
    ("documentos:listar",  "Listar remitos pendientes",          "documentos", "listar"),
    ("documentos:ver",     "Ver / descargar remito PDF",         "documentos", "ver"),
    ("documentos:firmar",  "Firmar un remito",                   "documentos", "firmar"),
    ("firmados:listar",    "Listar remitos firmados",            "firmados",   "listar"),
    ("firmados:ver",       "Ver / descargar remito firmado",     "firmados",   "ver"),
    ("usuarios:listar",    "Listar usuarios del sistema",        "usuarios",   "listar"),
    ("usuarios:crear",     "Crear un nuevo usuario",             "usuarios",   "crear"),
    ("usuarios:editar",    "Editar datos de un usuario",         "usuarios",   "editar"),
    ("usuarios:eliminar",  "Desactivar un usuario",              "usuarios",   "eliminar"),
    ("roles:listar",       "Listar roles disponibles",           "roles",      "listar"),
    ("roles:gestionar",    "Crear / editar / asignar roles",     "roles",      "gestionar"),
    ("configuracion:rutas", "Gestionar rutas de archivos (bandeja, transferencias)", "configuracion", "rutas"),
    ("apartados:gestionar", "Acceso total a apartados (crear, editar todos, eliminar)", "apartados", "gestionar"),
    ("apartados:crear", "Dar de alta apartados nuevos", "apartados", "crear"),
    ("apartados:editar", "Editar configuración de apartados asignados al usuario", "apartados", "editar"),
    ("metricas:ver",       "Ver métricas de ingresos/OC",          "metricas",   "ver"),
]

# ── Role catalogue ────────────────────────────────────────────────────────────
#  (name, description, list_of_permission_names)
ROLES = [
    (
        "superadmin",
        "Super administrador — acceso total al sistema",
        [p[0] for p in PERMISSIONS],          # all permissions
    ),
    (
        "firmante",
        "Operador de firma — gestiona y firma remitos",
        ["documentos:listar", "documentos:ver", "documentos:firmar",
         "firmados:listar", "firmados:ver"],
    ),
    (
        "consulta",
        "Solo lectura — visualiza remitos sin poder firmar",
        ["documentos:listar", "documentos:ver",
         "firmados:listar", "firmados:ver"],
    ),
    (
        "administrador",
        "Administra apartados asignados (rutas y configuración, sin crear ni eliminar)",
        ["apartados:editar"],
    ),
]


def seed():
    with db_session() as db:
        from services.apartados import seed_default_apartados_from_legacy_if_empty

        seed_default_apartados_from_legacy_if_empty(db)
        # ── Permissions ───────────────────────────────────────────────────────
        perm_map: dict[str, Permission] = {}
        for name, desc, resource, action in PERMISSIONS:
            perm = db.query(Permission).filter(Permission.name == name).first()
            if not perm:
                perm = Permission(name=name, description=desc, resource=resource, action=action)
                db.add(perm)
                print(f"  + permission: {name}")
            perm_map[name] = perm
        db.flush()

        # ── Roles ─────────────────────────────────────────────────────────────
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

        # ── Superadmin user ───────────────────────────────────────────────────
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

        # Asignar todos los apartados a usuarios no superadmin (comportamiento previo: acceso a ambas bandejas)
        aps = db.query(Apartado).order_by(Apartado.orden, Apartado.codigo).all()
        if aps:
            for u in db.query(User).all():
                if u.role and u.role.name == "superadmin":
                    continue
                u.apartados = list(aps)
            print(f"  · user_apartado: asignados {len(aps)} apartado(s) a usuarios (excepto superadmin)")

    print("\nSeed completed OK")


if __name__ == "__main__":
    print("Seeding database…")
    seed()
