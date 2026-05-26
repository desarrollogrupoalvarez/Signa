"""
Script de diagnostico para la sincronizacion con Tango.

Uso (desde la carpeta backend):
    python diagnostico_tango.py 2026-05-01
    python diagnostico_tango.py 2026-05-01 transferencias
    python diagnostico_tango.py 2026-05-01 ingresos

Muestra paso a paso cuantos registros retorna cada filtro de la consulta,
para identificar que condicion esta excluyendo los comprobantes esperados.
"""
from __future__ import annotations

import sys
from datetime import date, datetime

# Bootstrap config
try:
    from config import Config
except ImportError:
    import pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from config import Config


def _connect(database: str | None = None):
    from services import tango_connection

    db = (database or Config.tango_default_database() or "").strip()
    return tango_connection.connect(db)


def _query(sql: str, params: list | None = None, *, database: str | None = None) -> list[dict]:
    conn = _connect(database)
    try:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _databases_para_modo(modo: str) -> list[tuple[str, str]]:
    sources = Config.tango_transferencia_sources()
    if modo in ("transferencias", "ingresos"):
        return [(src.id, src.database) for src in sources]
    db = Config.tango_default_database()
    return [("default", db)] if db else []


def _section(title: str) -> None:
    print()
    print("=" * 70)
    print("  " + title)
    print("=" * 70)


def _tabla(rows: list[dict], max_rows: int = 30) -> None:
    if not rows:
        print("  (sin resultados)")
        return
    cols = list(rows[0].keys())
    widths = {c: max(len(str(c)), max((len(str(r.get(c, ""))) for r in rows[:max_rows]), default=0)) for c in cols}
    header = " | ".join(str(c).ljust(widths[c]) for c in cols)
    sep = "-+-".join("-" * widths[c] for c in cols)
    print("  " + header)
    print("  " + sep)
    for r in rows[:max_rows]:
        print("  " + " | ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))
    if len(rows) > max_rows:
        print("  ... ({} filas mas ocultas)".format(len(rows) - max_rows))


def _run_diagnostico_database(
    fecha: date,
    modo: str,
    database: str,
    label: str,
    *,
    deps_app: list[str],
    usrs_app: list[str],
) -> None:
    sch = "{}.dbo".format(database)
    es_tra = modo == "transferencias"
    t_comp = "TRA" if es_tra else "REM"
    tipo_mov = "S" if es_tra else "E"

    print()
    print("#" * 70)
    print("  BASE: {}  ({})".format(label, database))
    print("#" * 70)

    # 2. Tipo de dato de FECHA_MOV
    _section("2. TIPO DE DATO DE STA14.FECHA_MOV [{}]".format(label))
    try:
        info = _query(
            "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_CATALOG = '{}' AND TABLE_NAME = 'STA14' AND COLUMN_NAME = 'FECHA_MOV'".format(
                database
            ),
            database=database,
        )
        _tabla(info)
    except Exception as ex:
        print("  ERROR consultando INFORMATION_SCHEMA: {}".format(ex))

    # 3. Ultimas 10 fechas con TRA/REM (sin filtros de usuario/deposito)
    _section("3. ULTIMAS 10 FECHAS CON T_COMP='{}' [{}]".format(t_comp, label))
    try:
        rows = _query(
            "SELECT TOP 10 "
            "  S14.FECHA_MOV, "
            "  TRY_CAST(S14.FECHA_MOV AS DATE) AS fecha_cast, "
            "  S14.T_COMP, "
            "  COUNT(*) AS cant_filas "
            "FROM {sch}.STA14 S14 "
            "INNER JOIN {sch}.STA20 S20 ON S14.ID_STA14 = S20.ID_STA14 "
            "WHERE S14.T_COMP = '{t}' "
            "  AND S20.TIPO_MOV = '{m}' "
            "GROUP BY S14.FECHA_MOV, S14.T_COMP "
            "ORDER BY S14.FECHA_MOV DESC".format(sch=sch, t=t_comp, m=tipo_mov),
            database=database,
        )
        _tabla(rows)
        if rows:
            fechas_db = [str(r.get("fecha_cast") or r.get("FECHA_MOV") or "")[:10] for r in rows]
            if fecha.isoformat() in fechas_db:
                print("\n  [OK] La fecha {} SI aparece en Tango.".format(fecha))
            else:
                print("\n  [AVISO] La fecha {} NO aparece entre las ultimas 10 en Tango.".format(fecha))
                print("          Ultima fecha encontrada: {}".format(fechas_db[0] if fechas_db else "(ninguna)"))
    except Exception as ex:
        print("  ERROR: {}".format(ex))

    # 4. Usuarios y depositos para esa fecha (sin filtros de app)
    _section("4. USUARIOS Y DEPOSITOS [{}] T_COMP='{}' {}".format(label, t_comp, fecha))
    try:
        rows = _query(
            "SELECT "
            "  S14.USUARIO, "
            "  S20.COD_DEPOSI, "
            "  CAST(S20.COD_DEPOSI AS VARCHAR(20)) AS cod_dep_varchar, "
            "  LEN(RTRIM(S14.USUARIO)) AS len_usuario, "
            "  COUNT(*) AS filas "
            "FROM {sch}.STA14 S14 "
            "INNER JOIN {sch}.STA20 S20 ON S14.ID_STA14 = S20.ID_STA14 "
            "WHERE S14.T_COMP = '{t}' "
            "  AND S20.TIPO_MOV = '{m}' "
            "  AND TRY_CAST(S14.FECHA_MOV AS DATE) = ? "
            "GROUP BY S14.USUARIO, S20.COD_DEPOSI "
            "ORDER BY S14.USUARIO".format(sch=sch, t=t_comp, m=tipo_mov),
            [fecha.isoformat()],
            database=database,
        )
        _tabla(rows)
        if not rows:
            print("\n  [PROBLEMA] No hay registros para {} con T_COMP='{}' y TIPO_MOV='{}'.".format(
                fecha, t_comp, tipo_mov))
            print("  Verificar si la fecha es correcta (feriado, fin de semana, etc.)")
    except Exception as ex:
        print("  ERROR: {}".format(ex))

    # 6. Cruce filtros app vs datos en Tango
    if deps_app or usrs_app:
        _section("6. CRUCE APP vs TANGO [{}]".format(label))
        try:
            rows_tango = _query(
                "SELECT DISTINCT "
                "  S14.USUARIO, "
                "  S20.COD_DEPOSI, "
                "  CAST(S20.COD_DEPOSI AS VARCHAR(20)) AS cod_dep_varchar "
                "FROM {sch}.STA14 S14 "
                "INNER JOIN {sch}.STA20 S20 ON S14.ID_STA14 = S20.ID_STA14 "
                "WHERE S14.T_COMP = '{t}' "
                "  AND S20.TIPO_MOV = '{m}' "
                "  AND TRY_CAST(S14.FECHA_MOV AS DATE) = ?".format(sch=sch, t=t_comp, m=tipo_mov),
                [fecha.isoformat()],
                database=database,
            )

            if rows_tango:
                tango_deps = {str(r.get("cod_dep_varchar") or r.get("COD_DEPOSI") or "").strip() for r in rows_tango}
                tango_usrs = {str(r.get("USUARIO") or "").strip().upper() for r in rows_tango if r.get("USUARIO")}

                print("  Depositos en Tango para esa fecha : {}".format(sorted(tango_deps)))
                print("  Depositos configurados en la app  : {}".format(sorted(deps_app)))
                deps_match = set(deps_app) & tango_deps
                deps_miss  = set(deps_app) - tango_deps
                print("  [OK] Coinciden   : {}".format(sorted(deps_match)))
                if deps_miss:
                    print("  [ERROR] NO matchean: {}".format(sorted(deps_miss)))
                    print("  -> Revisar el valor de cod_deposito en el apartado.")
                    print("     Los valores validos son: {}".format(sorted(tango_deps)))

                print()
                print("  Usuarios en Tango para esa fecha  : {}".format(sorted(tango_usrs)))
                print("  Usuarios configurados en la app   : {}".format(sorted(usrs_app)))
                usrs_match = set(usrs_app) & tango_usrs
                usrs_miss  = set(usrs_app) - tango_usrs
                usrs_extra = tango_usrs - set(usrs_app)
                print("  [OK] Coinciden   : {}".format(sorted(usrs_match)))
                if usrs_miss:
                    print("  [ERROR] NO matchean (en app pero no en Tango): {}".format(sorted(usrs_miss)))
                    print("  -> Verificar que el username en la app sea identico al de Tango.")
                if usrs_extra:
                    print("  [AVISO] En Tango pero NO en la app (no se importaran): {}".format(sorted(usrs_extra)))
                    print("  -> Si queres importarlos, agregar esos usuarios al apartado.")
            else:
                print("  (No hay datos en Tango para {} con ese T_COMP/TIPO_MOV)".format(fecha))
        except Exception as ex:
            print("  ERROR en cruce: {}".format(ex))

    # 7. Query exacta del app con todos los filtros
    if deps_app and usrs_app:
        _section("7. QUERY EXACTA DEL APP [{}]".format(label))
        try:
            from services.tango_queries import _in_placeholders
            deps_ph = _in_placeholders(len(deps_app))
            usrs_ph = _in_placeholders(len(usrs_app))

            if es_tra:
                sql_count = (
                    "SELECT COUNT(*) AS total_filas, COUNT(DISTINCT S14.ID_STA14) AS total_comprobantes "
                    "FROM {sch}.STA14 S14 "
                    "INNER JOIN {sch}.STA20 S20 ON S14.ID_STA14 = S20.ID_STA14 "
                    "INNER JOIN {sch}.STA11 S11 ON S20.ID_STA11 = S11.ID_STA11 "
                    "WHERE S14.T_COMP LIKE 'TRA' "
                    "  AND S20.TIPO_MOV LIKE 'S' "
                    "  AND CAST(S20.COD_DEPOSI AS VARCHAR(20)) IN ({deps}) "
                    "  AND S14.USUARIO IN ({usrs}) "
                    "  AND CAST(S14.FECHA_MOV AS DATE) = ?"
                ).format(sch=sch, deps=deps_ph, usrs=usrs_ph)
            else:
                sql_count = (
                    "SELECT COUNT(*) AS total_filas, COUNT(DISTINCT S14.ID_STA14) AS total_comprobantes "
                    "FROM {sch}.STA14 S14 "
                    "INNER JOIN {sch}.STA20 S20 ON S14.ID_STA14 = S20.ID_STA14 "
                    "INNER JOIN {sch}.STA11 S11 ON S20.ID_STA11 = S11.ID_STA11 "
                    "WHERE S14.T_COMP LIKE 'REM' "
                    "  AND S20.TIPO_MOV LIKE 'E' "
                    "  AND CAST(S20.COD_DEPOSI AS VARCHAR(20)) IN ({deps}) "
                    "  AND S14.USUARIO IN ({usrs}) "
                    "  AND CAST(S14.FECHA_MOV AS DATE) = ?"
                ).format(sch=sch, deps=deps_ph, usrs=usrs_ph)

            params = list(deps_app) + list(usrs_app) + [fecha.isoformat()]
            rows = _query(sql_count, params, database=database)
            _tabla(rows)
            total = rows[0].get("total_filas", 0) if rows else 0
            if total == 0:
                print("\n  [PROBLEMA] La query exacta del app retorna 0 filas.")
                print("  Revisar secciones 4 y 6 para identificar la causa.")
            else:
                print("\n  [OK] La query retorna {} filas. El sync deberia funcionar.".format(total))
        except Exception as ex:
            print("  ERROR ejecutando query del app: {}".format(ex))

    # 8. Verificar CAST de FECHA_MOV
    _section("8. MUESTRA CAST FECHA_MOV [{}]".format(label))
    try:
        sample = _query(
            "SELECT TOP 5 "
            "  S14.FECHA_MOV AS valor_crudo, "
            "  CAST(S14.FECHA_MOV AS DATE) AS cast_date, "
            "  TRY_CAST(S14.FECHA_MOV AS DATE) AS try_cast_date "
            "FROM {sch}.STA14 S14 "
            "WHERE S14.T_COMP = '{t}' "
            "ORDER BY S14.ID_STA14 DESC".format(sch=sch, t=t_comp),
            database=database,
        )
        _tabla(sample)
        if sample:
            nulls = sum(1 for r in sample if r.get("try_cast_date") is None)
            if nulls > 0:
                print("\n  [PROBLEMA] {}/{} filas tienen TRY_CAST NULL.".format(nulls, len(sample)))
                print("  El tipo de FECHA_MOV no se convierte bien a DATE. Ver seccion 2.")
            else:
                print("\n  [OK] CAST(FECHA_MOV AS DATE) funciona correctamente.")
    except Exception as ex:
        print("  ERROR: {}".format(ex))


def run_diagnostico(fecha_str: str, modo: str = "transferencias") -> None:
    try:
        fecha = datetime.strptime(fecha_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        print("ERROR: fecha invalida '{}'. Use formato YYYY-MM-DD.".format(fecha_str))
        sys.exit(1)

    dbs = _databases_para_modo(modo)
    if not dbs:
        print("ERROR: no hay bases Tango configuradas para modo {}".format(modo))
        sys.exit(1)

    print()
    print("-" * 70)
    print("  DIAGNOSTICO TANGO  |  modo={}  |  fecha={}".format(modo, fecha))
    print("  HOST: {}  |  bases: {}".format(Config.TANGO_HOST, ", ".join(d[1] for d in dbs)))
    print("-" * 70)

    _section("1. VERIFICACION DE CONEXION (todas las bases)")
    try:
        from services.tango_connection import ping_all_sources

        ping_res = ping_all_sources()
        for sid, info in (ping_res.get("sources") or {}).items():
            st = "[OK]" if info.get("ok") else "[ERROR]"
            print("  {} {} ({})".format(st, sid, info.get("database", "")))
            if info.get("error"):
                print("       {}".format(info["error"]))
        if not ping_res.get("ok"):
            print("  [AVISO] Ninguna base respondio correctamente.")
    except Exception as ex:
        print("  [ERROR] Ping: {}".format(ex))

    codigo_apartado = "transferencias" if modo == "transferencias" else "ingresos"
    deps_app: list[str] = []
    usrs_app: list[str] = []
    _section("5. CONFIGURACION DEL APARTADO EN LA APP")
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from models.apartado import Apartado

        engine = create_engine(Config.DATABASE_URL)
        with Session(engine) as db:
            ap = db.query(Apartado).filter(Apartado.codigo == codigo_apartado).first()
            if not ap:
                print("  [ERROR] No existe apartado con codigo '{}'".format(codigo_apartado))
            else:
                cod_raw = (ap.cod_deposito or "").strip()
                deps_app = [x.strip() for x in cod_raw.replace(";", ",").split(",") if x.strip()]
                print("  cod_deposito raw  : '{}'".format(cod_raw))
                print("  deps parseados    : {}".format(deps_app))
                print("  bandeja_path      : '{}'".format(ap.bandeja_path))
                print("  destino_path      : '{}'".format(ap.destino_path))

                from services.apartados import tango_usernames_for_apartado

                usrs_app = tango_usernames_for_apartado(db, ap)
                print("  usuarios Tango    : {}".format(usrs_app))

                if not deps_app:
                    print("\n  [PROBLEMA] El apartado no tiene cod_deposito configurado.")
                if not usrs_app:
                    print("\n  [PROBLEMA] No hay usuarios activos asignados al apartado.")
    except Exception as ex:
        print("  ERROR leyendo app DB: {}".format(ex))

    for label, database in dbs:
        try:
            _run_diagnostico_database(
                fecha, modo, database, label, deps_app=deps_app, usrs_app=usrs_app
            )
        except Exception as ex:
            print("  [ERROR] Diagnostico para {}: {}".format(label, ex))

    print()
    print("=" * 70)
    print("  FIN DEL DIAGNOSTICO")
    print("=" * 70)
    print()


if __name__ == "__main__":
    args = sys.argv[1:]
    fecha_arg = args[0] if args else date.today().isoformat()
    modo_arg  = args[1] if len(args) > 1 else "transferencias"
    if modo_arg not in ("transferencias", "ingresos"):
        print("modo invalido: '{}'. Usar 'transferencias' o 'ingresos'.".format(modo_arg))
        sys.exit(1)
    run_diagnostico(fecha_arg, modo_arg)
