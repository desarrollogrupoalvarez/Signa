#!/usr/bin/env python
"""
Database migration script.

Usage:
  python migrate.py           # Create / update all tables (SQLAlchemy create_all)
  python migrate.py alembic   # Run: alembic upgrade head (incremental migrations)
  python migrate.py drop      # ⚠ Drop ALL tables (destructive, dev only)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def run_create_all() -> None:
    from core.database import engine
    import models  # noqa — ensures all models are registered on Base.metadata

    from models.base import Base

    print(f"Target DB: {engine.url}")
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    # Compat migration: drop users.email (ya no se usa).
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS email"))
        print("Applied: users.email column dropped OK")
    except Exception:
        # If table doesn't exist yet, ignore.
        pass
    # Drop legacy table: app_settings (replaced by apartados).
    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS app_settings"))
        print("Applied: app_settings table dropped OK")
    except Exception as ex:
        print(f"Warning: drop app_settings failed: {ex}")

    def _ddl(conn, sql: str, label: str) -> None:
        from sqlalchemy import text

        conn.execute(text("SET lock_timeout = '15s'"))
        conn.execute(text(sql))
        print(f"Applied: {label}")

    # DDL apartados/comprobante_tango antes de abrir SessionLocal (evita bloqueos).
    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            _ddl(
                conn,
                "ALTER TABLE apartados ADD COLUMN IF NOT EXISTS keywords_importante "
                "VARCHAR(1000) NOT NULL DEFAULT ''",
                "apartados.keywords_importante column added OK",
            )
            _ddl(
                conn,
                "ALTER TABLE apartados ADD COLUMN IF NOT EXISTS cod_deposito "
                "VARCHAR(64) NOT NULL DEFAULT '2'",
                "apartados.cod_deposito column added",
            )
            _ddl(
                conn,
                "ALTER TABLE apartados ADD COLUMN IF NOT EXISTS depositos_config "
                "TEXT NOT NULL DEFAULT '[]'",
                "apartados.depositos_config column added",
            )
            _ddl(
                conn,
                "ALTER TABLE apartados ADD COLUMN IF NOT EXISTS categorias_destino "
                "TEXT NOT NULL DEFAULT '[]'",
                "apartados.categorias_destino column added",
            )
    except Exception as ex:
        print(f"Warning: alter apartados failed: {ex}")

    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            _ddl(
                conn,
                "ALTER TABLE comprobante_tango ADD COLUMN IF NOT EXISTS texto_contenido TEXT",
                "comprobante_tango.texto_contenido",
            )
            _ddl(
                conn,
                "ALTER TABLE comprobante_tango ADD COLUMN IF NOT EXISTS texto_search TSVECTOR "
                "GENERATED ALWAYS AS (to_tsvector('spanish', coalesce(texto_contenido, ''))) STORED",
                "comprobante_tango.texto_search",
            )
            conn.execute(text("SET lock_timeout = '15s'"))
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_comprobante_tango_texto_search "
                    "ON comprobante_tango USING GIN (texto_search)"
                )
            )
            print("Applied: idx_comprobante_tango_texto_search OK")
    except Exception as ex:
        print(f"Warning: alter comprobante_tango fulltext failed: {ex}")

    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            _ddl(
                conn,
                "ALTER TABLE comprobante_tango ADD COLUMN IF NOT EXISTS ruta TEXT",
                "comprobante_tango.ruta column added",
            )
    except Exception as ex:
        print(f"Warning: alter comprobante_tango.ruta failed: {ex}")

    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(
                text("UPDATE comprobante_tango SET ruta = NULL WHERE estado = 'pendiente'")
            )
        print("Applied: comprobante_tango.ruta limpiada en pendientes")
    except Exception as ex:
        print(f"Warning: cleanup pendiente ruta failed: {ex}")

    _migrate_permisos_por_vista()
    _migrate_areas()

    from core.database import db_session
    from services.apartados import seed_default_apartados_from_legacy_if_empty
    from services.apartado_paths import migrate_apartados_storage

    try:
        with db_session() as _s:
            seed_default_apartados_from_legacy_if_empty(_s)
            n = migrate_apartados_storage(_s)
            if n:
                print(f"Applied: migrated depositos/categorias config for {n} apartado(s)")
    except Exception as ex:
        print(f"Warning: seed apartados: {ex}")

    print("Done OK")


def _migrate_permisos_por_vista() -> None:
    """Migración 003: permisos por vista + tabla role_digitalizado_carpetas."""
    from pathlib import Path

    from sqlalchemy import text

    from core.database import db_session, engine
    from core.permissions import (
        OLD_TO_NEW_PERMISSION,
        PERM_DIGITALIZADOS_VER_TODO,
        PERM_PENDIENTES_VER_TODOS,
        PERM_ROLES_ELIMINAR,
        PERMISSIONS,
    )
    from models.permission import Permission
    from models.role import Role

    sql_path = Path(__file__).parent / "migrations" / "003_permisos_por_vista.sql"
    try:
        if sql_path.is_file():
            with engine.begin() as conn:
                conn.execute(text("SET lock_timeout = '15s'"))
                conn.execute(text(sql_path.read_text(encoding="utf-8")))
            print("Applied: 003_permisos_por_vista.sql OK")
    except Exception as ex:
        print(f"Warning: 003_permisos_por_vista.sql failed: {ex}")

    try:
        with db_session() as db:
            perm_map: dict[str, Permission] = {}
            for name, desc, resource, action in PERMISSIONS:
                perm = db.query(Permission).filter(Permission.name == name).first()
                if not perm:
                    perm = Permission(name=name, description=desc, resource=resource, action=action)
                    db.add(perm)
                else:
                    perm.description = desc
                    perm.resource = resource
                    perm.action = action
                perm_map[name] = perm
            db.flush()

            for old_name, new_name in OLD_TO_NEW_PERMISSION.items():
                old_perm = db.query(Permission).filter(Permission.name == old_name).first()
                new_perm = perm_map.get(new_name)
                if not old_perm or not new_perm:
                    continue
                rows = db.execute(
                    text(
                        "SELECT role_id FROM role_permissions WHERE permission_id = :old_id"
                    ),
                    {"old_id": old_perm.id},
                ).fetchall()
                for (role_id,) in rows:
                    exists = db.execute(
                        text(
                            "SELECT 1 FROM role_permissions "
                            "WHERE role_id = :rid AND permission_id = :pid"
                        ),
                        {"rid": role_id, "pid": new_perm.id},
                    ).first()
                    if not exists:
                        db.execute(
                            text(
                                "INSERT INTO role_permissions (role_id, permission_id) "
                                "VALUES (:rid, :pid) ON CONFLICT DO NOTHING"
                            ),
                            {"rid": role_id, "pid": new_perm.id},
                        )

            extra_by_role = {
                "administrador": [PERM_PENDIENTES_VER_TODOS, PERM_DIGITALIZADOS_VER_TODO],
                "firmante": [PERM_DIGITALIZADOS_VER_TODO],
                "consulta": [PERM_DIGITALIZADOS_VER_TODO],
                "superadmin": [PERM_ROLES_ELIMINAR],
            }
            for role_name, extra_names in extra_by_role.items():
                role = db.query(Role).filter(Role.name == role_name).first()
                if not role:
                    continue
                current = {p.name for p in role.permissions}
                for n in extra_names:
                    if n in perm_map and n not in current:
                        role.permissions.append(perm_map[n])

            superadmin = db.query(Role).filter(Role.name == "superadmin").first()
            if superadmin:
                existing_ids = {p.id for p in superadmin.permissions}
                for p in perm_map.values():
                    if p.id not in existing_ids:
                        superadmin.permissions.append(p)

            for legacy_name in OLD_TO_NEW_PERMISSION:
                legacy_perm = db.query(Permission).filter(Permission.name == legacy_name).first()
                if legacy_perm:
                    db.execute(
                        text("DELETE FROM role_permissions WHERE permission_id = :pid"),
                        {"pid": legacy_perm.id},
                    )

        print("Applied: permisos por vista (data migration) OK")
    except Exception as ex:
        print(f"Warning: permisos por vista data migration failed: {ex}")


def _migrate_areas() -> None:
    """Migracion 004: areas, user_area, apartados.area_id y backfill Deposito Daudet."""
    from pathlib import Path

    from sqlalchemy import text

    from core.database import db_session, engine

    sql_path = Path(__file__).parent / "migrations" / "004_areas.sql"
    try:
        if sql_path.is_file():
            with engine.begin() as conn:
                conn.execute(text("SET lock_timeout = '15s'"))
                conn.execute(text(sql_path.read_text(encoding="utf-8")))
            print("Applied: 004_areas.sql OK")
    except Exception as ex:
        print(f"Warning: 004_areas.sql failed: {ex}")

    try:
        with db_session() as db:
            from models.apartado import Apartado, user_apartado
            from models.area import Area, user_area
            from models.user import User
            from sqlalchemy.orm import joinedload

            area = db.query(Area).filter(Area.codigo == "daudet").first()
            if not area:
                area = Area(codigo="daudet", nombre="Depósito Daudet", activo=True, orden=0)
                db.add(area)
                db.flush()
                print("Applied: area daudet creada")

            def _norm_codigo(c: str) -> str:
                return (c or "").strip().lower().replace(" ", "_")

            daudet_codes = {
                "transferencias_daudet",
                "ingresos_daudet",
                "transferencias",
                "ingresos",
            }
            for ap in db.query(Apartado).all():
                if ap.area_id:
                    continue
                nc = _norm_codigo(ap.codigo)
                if nc in daudet_codes or "daudet" in nc:
                    ap.area_id = area.id

            orphan = db.query(Apartado).filter(Apartado.area_id.is_(None)).count()
            if orphan:
                db.query(Apartado).filter(Apartado.area_id.is_(None)).update(
                    {Apartado.area_id: area.id}, synchronize_session=False
                )
                print(f"Applied: {orphan} apartado(s) sin area asignados a daudet")

            area_children: dict[int, list[int]] = {}
            for ap in db.query(Apartado).filter(Apartado.activo.is_(True)).all():
                if ap.area_id:
                    area_children.setdefault(int(ap.area_id), []).append(int(ap.id))

            for user in db.query(User).options(joinedload(User.apartados)).all():
                if user.role and user.role.name == "superadmin":
                    continue
                user_ap_ids = {int(a.id) for a in (user.apartados or [])}
                if not user_ap_ids:
                    continue
                by_area: dict[int, set[int]] = {}
                for ap in user.apartados or []:
                    if ap.area_id:
                        by_area.setdefault(int(ap.area_id), set()).add(int(ap.id))
                current_area_ids = {int(a.id) for a in (user.areas or [])}
                for aid, explicit in by_area.items():
                    all_children = set(area_children.get(aid, []))
                    if all_children and explicit >= all_children:
                        current_area_ids.add(aid)
                if current_area_ids:
                    user.areas = db.query(Area).filter(Area.id.in_(current_area_ids)).all()

            try:
                with engine.begin() as conn:
                    conn.execute(text("SET lock_timeout = '15s'"))
                    conn.execute(
                        text(
                            "ALTER TABLE apartados ALTER COLUMN area_id SET NOT NULL"
                        )
                    )
                print("Applied: apartados.area_id NOT NULL")
            except Exception as ex2:
                print(f"Warning: area_id NOT NULL skipped: {ex2}")

        print("Applied: areas data migration OK")
    except Exception as ex:
        print(f"Warning: areas data migration failed: {ex}")


def run_alembic() -> None:
    import subprocess
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(Path(__file__).parent),
    )
    sys.exit(result.returncode)


def run_drop() -> None:
    confirm = input("⚠  This will DROP ALL TABLES. Type 'yes' to confirm: ")
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        return
    from core.database import engine
    import models  # noqa
    from models.base import Base
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("Done ✓")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "create"
    if cmd == "alembic":
        run_alembic()
    elif cmd == "drop":
        run_drop()
    else:
        run_create_all()
