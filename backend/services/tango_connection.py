"""Conexion pyodbc a SQL Server (Tango)."""

from __future__ import annotations

import logging
from typing import Any

from config import Config

logger = logging.getLogger("remitos")

_DRIVERS = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server",
)


def connect(database: str | None = None):
    if not Config.tango_configured():
        raise RuntimeError("Tango no configurado (TANGO_HOST, TANGO_USERNAME, base de datos)")
    db = (database or Config.tango_default_database() or "").strip()
    if not db:
        raise RuntimeError("Nombre de base Tango no indicado")
    last_err = None
    for driver in _DRIVERS:
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={Config.TANGO_HOST},{Config.TANGO_PORT};"
            f"DATABASE={db};"
            f"UID={Config.TANGO_USERNAME};"
            f"PWD={Config.TANGO_PASSWORD};"
            "TrustServerCertificate=yes;"
        )
        try:
            import pyodbc

            return pyodbc.connect(conn_str, timeout=Config.TANGO_QUERY_TIMEOUT)
        except Exception as ex:
            last_err = ex
            logger.debug("pyodbc driver %s failed: %s", driver, ex)
    raise RuntimeError(f"No se pudo conectar a Tango ({db}): {last_err}")


def ping(database: str | None = None) -> dict[str, Any]:
    db = (database or Config.tango_default_database() or "").strip()
    conn = connect(db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 AS ok")
        row = cur.fetchone()
        return {"ok": bool(row and row[0] == 1), "database": db}
    finally:
        conn.close()


def ping_all_sources() -> dict[str, Any]:
    """Prueba conexión a cada base configurada para transferencias."""
    results: dict[str, dict[str, Any]] = {}
    any_ok = False
    for src in Config.tango_transferencia_sources():
        try:
            r = ping(src.database)
            results[src.id] = r
            any_ok = any_ok or r.get("ok")
        except Exception as ex:
            results[src.id] = {"ok": False, "database": src.database, "error": str(ex)}
    if not results and Config.TANGO_DB_NAME:
        try:
            r = ping(Config.TANGO_DB_NAME)
            results["default"] = r
            any_ok = r.get("ok", False)
        except Exception as ex:
            results["default"] = {"ok": False, "database": Config.TANGO_DB_NAME, "error": str(ex)}
    return {"ok": any_ok, "sources": results}
