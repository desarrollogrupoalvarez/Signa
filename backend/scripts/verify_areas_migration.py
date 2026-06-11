#!/usr/bin/env python
"""Verifica estado de migracion 004 (areas)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from core.database import engine


def main() -> int:
    queries = {
        "areas": """
            SELECT id, codigo, nombre, activo, orden FROM areas
            ORDER BY orden, codigo
        """,
        "apartados": """
            SELECT a.id, a.codigo, a.nombre, a.modo_flujo, a.area_id,
                   ar.codigo AS area_codigo, ar.nombre AS area_nombre
            FROM apartados a
            LEFT JOIN areas ar ON ar.id = a.area_id
            ORDER BY ar.orden, a.orden, a.codigo
        """,
        "apartados_sin_area": """
            SELECT COUNT(*) AS n FROM apartados WHERE area_id IS NULL
        """,
        "area_id_nullable": """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'apartados'
              AND column_name = 'area_id'
        """,
        "user_area": """
            SELECT u.username, ar.codigo AS area_codigo, ar.nombre AS area_nombre
            FROM user_area ua
            JOIN users u ON u.id = ua.user_id
            JOIN areas ar ON ar.id = ua.area_id
            ORDER BY u.username, ar.codigo
        """,
        "user_apartado": """
            SELECT u.username, a.codigo AS apartado_codigo, a.nombre AS apartado_nombre
            FROM user_apartado ua
            JOIN users u ON u.id = ua.user_id
            JOIN apartados a ON a.id = ua.apartado_id
            ORDER BY u.username, a.codigo
        """,
    }

    ok = True
    with engine.connect() as conn:
        for label, sql in queries.items():
            print(f"=== {label} ===")
            try:
                rows = conn.execute(text(sql)).mappings().all()
                if not rows:
                    print("(sin filas)")
                for row in rows:
                    print(dict(row))
            except Exception as ex:
                ok = False
                print(f"ERROR: {ex}")
            print()

        # Intentar NOT NULL si corresponde
        nullable = conn.execute(text(queries["area_id_nullable"])).scalar()
        orphans = conn.execute(text(queries["apartados_sin_area"])).scalar() or 0
        print("=== accion NOT NULL ===")
        if nullable == "NO":
            print("area_id ya es NOT NULL - nada que hacer")
        elif orphans:
            ok = False
            print(f"BLOQUEADO: hay {orphans} apartado(s) sin area_id")
        else:
            try:
                with engine.begin() as tx:
                    tx.execute(text("SET lock_timeout = '60s'"))
                    tx.execute(text("ALTER TABLE apartados ALTER COLUMN area_id SET NOT NULL"))
                print("APLICADO: area_id SET NOT NULL")
                nullable = conn.execute(text(queries["area_id_nullable"])).scalar()
                print(f"is_nullable ahora: {nullable}")
            except Exception as ex:
                ok = False
                print(f"FALLO al aplicar NOT NULL: {ex}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
