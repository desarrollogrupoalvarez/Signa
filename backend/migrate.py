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
        print("Applied: users.email column dropped ✓")
    except Exception:
        # If table doesn't exist yet, ignore.
        pass
    # Drop legacy table: app_settings (replaced by apartados).
    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS app_settings"))
        print("Applied: app_settings table dropped ✓")
    except Exception as ex:
        print(f"Warning: drop app_settings failed: {ex}")

    # Add keywords_importante to apartados (editable per apartado).
    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE apartados ADD COLUMN IF NOT EXISTS keywords_importante VARCHAR(1000) NOT NULL DEFAULT ''"))
        print("Applied: apartados.keywords_importante column added ✓")
    except Exception as ex:
        print(f"Warning: alter apartados.keywords_importante failed: {ex}")

    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE apartados ADD COLUMN IF NOT EXISTS cod_deposito VARCHAR(64) NOT NULL DEFAULT '2'"
                )
            )
        print("Applied: apartados.cod_deposito column added")
    except Exception as ex:
        print(f"Warning: alter apartados.cod_deposito failed: {ex}")

    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE apartados ADD COLUMN IF NOT EXISTS depositos_config TEXT NOT NULL DEFAULT '[]'"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE apartados ADD COLUMN IF NOT EXISTS categorias_destino TEXT NOT NULL DEFAULT '[]'"
                )
            )
        print("Applied: apartados.depositos_config / categorias_destino columns added")
    except Exception as ex:
        print(f"Warning: alter apartados depositos/categorias failed: {ex}")

    from core.database import SessionLocal
    from services.apartados import seed_default_apartados_from_legacy_if_empty
    from services.apartado_paths import migrate_apartados_storage

    _s = SessionLocal()
    try:
        seed_default_apartados_from_legacy_if_empty(_s)
        n = migrate_apartados_storage(_s)
        if n:
            print(f"Applied: migrated depositos/categorias config for {n} apartado(s)")
    except Exception as ex:
        print(f"Warning: seed apartados: {ex}")
    finally:
        _s.close()
    print("Done ✓")


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
