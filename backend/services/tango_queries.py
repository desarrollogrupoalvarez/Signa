"""Consultas parametrizadas a movimientos Tango (STA14/STA20/STA11)."""

from __future__ import annotations

from datetime import date
from typing import Any, Sequence

from config import Config
from services import tango_connection


def _schema(database: str) -> str:
    db = (database or "").strip()
    if not db:
        raise RuntimeError("Base Tango no indicada")
    return f"{db}.dbo"


def _in_placeholders(n: int) -> str:
    return ", ".join("?" for _ in range(n))


def _deposito_where_clause(cod_depositos: Sequence[str]) -> tuple[str, list[str]]:
    """
    Filtro SQL por depósito. Lista vacía (campo en blanco) = todos los depósitos, sin IN.
    """
    deps = [str(x).strip() for x in cod_depositos if str(x).strip()]
    if not deps:
        return "", []
    return (
        f"  AND CAST(S20.COD_DEPOSI AS VARCHAR(20)) IN ({_in_placeholders(len(deps))})\n",
        deps,
    )


def _fetch_all(
    sql: str, params: Sequence[Any], *, database: str
) -> list[dict[str, Any]]:
    conn = tango_connection.connect(database)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def fetch_transferencias(
    cod_depositos: Sequence[str],
    usuarios: Sequence[str],
    fecha: date,
    *,
    database: str,
    tango_fuente: str,
) -> list[dict[str, Any]]:
    dep_clause, dep_params = _deposito_where_clause(cod_depositos)
    usrs = [str(x).strip().upper() for x in usuarios if str(x).strip()]
    if not usrs:
        return []
    sch = _schema(database)
    sql = f"""
SELECT
    S14.ID_STA14 AS Id_STA14,
    S14.FECHA_MOV AS Fecha,
    S14.HORA_COMP AS Hora,
    S13.DESCRIPCIO AS Tipo_Movimiento,
    S14.T_COMP AS Codigo_Comp,
    S14.N_COMP AS Numero_Comp,
    S20.TIPO_MOV AS Tipo_movimiento,
    S20.COD_DEPOSI AS Cod_Origen,
    Origen.NOMBRE_SUC AS Deposito_Origen,
    S20.DEPOSI_DDE AS Cod_Destino,
    Destino.NOMBRE_SUC AS Deposito_Destino,
    S11.COD_ARTICU AS Codigo_Producto,
    S11.DESCRIPCIO AS Descripcion_Producto,
    S11.DESC_ADIC AS Descripcion_Adicional,
    S20.CANTIDAD AS Cantidad,
    S14.OBSERVACIO AS Observacion,
    S14.USUARIO
FROM {sch}.STA14 S14
INNER JOIN {sch}.STA20 S20 ON S14.ID_STA14 = S20.ID_STA14
INNER JOIN {sch}.STA11 S11 ON S20.ID_STA11 = S11.ID_STA11
LEFT JOIN {sch}.STA13 S13 ON S14.ID_STA13 = S13.ID_STA13
LEFT JOIN {sch}.STA22 Origen ON S20.COD_DEPOSI = Origen.COD_SUCURS
LEFT JOIN {sch}.STA22 Destino ON S20.DEPOSI_DDE = Destino.COD_SUCURS
WHERE S14.T_COMP LIKE 'TRA'
  AND S20.TIPO_MOV LIKE 'S'
{dep_clause}  AND S14.USUARIO IN ({_in_placeholders(len(usrs))})
  AND CAST(S14.FECHA_MOV AS DATE) = ?
ORDER BY S14.ID_STA14, S14.HORA_COMP
"""
    params: list[Any] = list(dep_params) + list(usrs) + [fecha.isoformat()]
    rows = _fetch_all(sql, params, database=database)
    fuente = (tango_fuente or "").strip().upper()
    for r in rows:
        r["tango_fuente"] = fuente
    return rows


def fetch_transferencias_rango(
    cod_depositos: Sequence[str],
    fecha_desde: date,
    fecha_hasta: date,
    *,
    database: str,
    tango_fuente: str,
) -> list[dict[str, Any]]:
    """Transferencias en rango de fechas, sin filtro por USUARIO (Registros)."""
    dep_clause, dep_params = _deposito_where_clause(cod_depositos)
    sch = _schema(database)
    sql = f"""
SELECT
    S14.ID_STA14 AS Id_STA14,
    S14.FECHA_MOV AS Fecha,
    S14.HORA_COMP AS Hora,
    S13.DESCRIPCIO AS Tipo_Movimiento,
    S14.T_COMP AS Codigo_Comp,
    S14.N_COMP AS Numero_Comp,
    S20.TIPO_MOV AS Tipo_movimiento,
    S20.COD_DEPOSI AS Cod_Origen,
    Origen.NOMBRE_SUC AS Deposito_Origen,
    S20.DEPOSI_DDE AS Cod_Destino,
    Destino.NOMBRE_SUC AS Deposito_Destino,
    S11.COD_ARTICU AS Codigo_Producto,
    S11.DESCRIPCIO AS Descripcion_Producto,
    S11.DESC_ADIC AS Descripcion_Adicional,
    S20.CANTIDAD AS Cantidad,
    S14.OBSERVACIO AS Observacion,
    S14.USUARIO
FROM {sch}.STA14 S14
INNER JOIN {sch}.STA20 S20 ON S14.ID_STA14 = S20.ID_STA14
INNER JOIN {sch}.STA11 S11 ON S20.ID_STA11 = S11.ID_STA11
LEFT JOIN {sch}.STA13 S13 ON S14.ID_STA13 = S13.ID_STA13
LEFT JOIN {sch}.STA22 Origen ON S20.COD_DEPOSI = Origen.COD_SUCURS
LEFT JOIN {sch}.STA22 Destino ON S20.DEPOSI_DDE = Destino.COD_SUCURS
WHERE S14.T_COMP LIKE 'TRA'
  AND S20.TIPO_MOV LIKE 'S'
{dep_clause}  AND CAST(S14.FECHA_MOV AS DATE) >= ?
  AND CAST(S14.FECHA_MOV AS DATE) <= ?
ORDER BY S14.ID_STA14, S14.HORA_COMP
"""
    params: list[Any] = list(dep_params) + [fecha_desde.isoformat(), fecha_hasta.isoformat()]
    rows = _fetch_all(sql, params, database=database)
    fuente = (tango_fuente or "").strip().upper()
    for r in rows:
        r["tango_fuente"] = fuente
    return rows


def fetch_ingresos(
    cod_depositos: Sequence[str],
    usuarios: Sequence[str],
    fecha: date,
    *,
    database: str,
    tango_fuente: str | None = None,
) -> list[dict[str, Any]]:
    dep_clause, dep_params = _deposito_where_clause(cod_depositos)
    usrs = [str(x).strip().upper() for x in usuarios if str(x).strip()]
    if not usrs:
        return []
    db = (database or "").strip()
    if not db:
        return []
    sch = _schema(db)
    sql = f"""
SELECT
    S14.ID_STA14 AS Id_STA14,
    S14.FECHA_MOV AS Fecha,
    S14.HORA_COMP AS Hora,
    S14.T_COMP AS Codigo_Comp,
    S14.N_COMP AS remito_proveedor,
    S14.NCOMP_IN_S AS Numero_remito,
    S20.TIPO_MOV AS Tipo_movimiento,
    S20.COD_DEPOSI AS Cod_Origen,
    Origen.NOMBRE_SUC AS Deposito_Origen,
    S20.DEPOSI_DDE AS Cod_Destino,
    Destino.NOMBRE_SUC AS Deposito_Destino,
    S11.COD_ARTICU AS Codigo_Producto,
    S11.DESCRIPCIO AS Descripcion_Producto,
    S11.DESC_ADIC AS Descripcion_Adicional,
    S20.CANTIDAD AS Cantidad,
    S14.OBSERVACIO AS Observacion,
    CONCAT(C1.COD_PROVEE COLLATE Modern_Spanish_CI_AI, ' ' COLLATE Modern_Spanish_CI_AI, C1.NOM_PROVEE COLLATE Modern_Spanish_CI_AI) AS proveedor,
    S14.USUARIO,
    m.SIGLA_MEDIDA AS u_m
FROM {sch}.STA14 S14
INNER JOIN {sch}.STA20 S20 ON S14.ID_STA14 = S20.ID_STA14
INNER JOIN {sch}.STA11 S11 ON S20.ID_STA11 = S11.ID_STA11
LEFT JOIN {sch}.STA13 S13 ON S14.ID_STA13 = S13.ID_STA13
LEFT JOIN {sch}.STA22 Origen ON S20.COD_DEPOSI = Origen.COD_SUCURS
LEFT JOIN {sch}.STA22 Destino ON S20.DEPOSI_DDE = Destino.COD_SUCURS
LEFT JOIN {sch}.CPA01 C1 ON S14.COD_PRO_CL = C1.COD_PROVEE
LEFT JOIN {sch}.medida m ON S11.ID_MEDIDA_STOCK = m.ID_MEDIDA
WHERE S14.T_COMP LIKE 'REM'
  AND S20.TIPO_MOV LIKE 'E'
{dep_clause}  AND S14.USUARIO IN ({_in_placeholders(len(usrs))})
  AND CAST(S14.FECHA_MOV AS DATE) = ?
ORDER BY S14.ID_STA14, S14.HORA_COMP
"""
    params = list(dep_params) + list(usrs) + [fecha.isoformat()]
    rows = _fetch_all(sql, params, database=db)
    fuente = (tango_fuente or "").strip().upper()
    if fuente:
        for r in rows:
            r["tango_fuente"] = fuente
    return rows


def fetch_ingresos_rango(
    cod_depositos: Sequence[str],
    fecha_desde: date,
    fecha_hasta: date,
    *,
    database: str,
    tango_fuente: str | None = None,
) -> list[dict[str, Any]]:
    """Ingresos (REM/E) en rango de fechas, sin filtro por USUARIO (Registros)."""
    dep_clause, dep_params = _deposito_where_clause(cod_depositos)
    db = (database or "").strip()
    if not db:
        return []
    sch = _schema(db)
    sql = f"""
SELECT
    S14.ID_STA14 AS Id_STA14,
    S14.FECHA_MOV AS Fecha,
    S14.HORA_COMP AS Hora,
    S14.T_COMP AS Codigo_Comp,
    S14.N_COMP AS remito_proveedor,
    S14.NCOMP_IN_S AS Numero_remito,
    S20.TIPO_MOV AS Tipo_movimiento,
    S20.COD_DEPOSI AS Cod_Origen,
    Origen.NOMBRE_SUC AS Deposito_Origen,
    S20.DEPOSI_DDE AS Cod_Destino,
    Destino.NOMBRE_SUC AS Deposito_Destino,
    S11.COD_ARTICU AS Codigo_Producto,
    S11.DESCRIPCIO AS Descripcion_Producto,
    S11.DESC_ADIC AS Descripcion_Adicional,
    S20.CANTIDAD AS Cantidad,
    S14.OBSERVACIO AS Observacion,
    CONCAT(C1.COD_PROVEE COLLATE Modern_Spanish_CI_AI, ' ' COLLATE Modern_Spanish_CI_AI, C1.NOM_PROVEE COLLATE Modern_Spanish_CI_AI) AS proveedor,
    S14.USUARIO,
    m.SIGLA_MEDIDA AS u_m
FROM {sch}.STA14 S14
INNER JOIN {sch}.STA20 S20 ON S14.ID_STA14 = S20.ID_STA14
INNER JOIN {sch}.STA11 S11 ON S20.ID_STA11 = S11.ID_STA11
LEFT JOIN {sch}.STA13 S13 ON S14.ID_STA13 = S13.ID_STA13
LEFT JOIN {sch}.STA22 Origen ON S20.COD_DEPOSI = Origen.COD_SUCURS
LEFT JOIN {sch}.STA22 Destino ON S20.DEPOSI_DDE = Destino.COD_SUCURS
LEFT JOIN {sch}.CPA01 C1 ON S14.COD_PRO_CL = C1.COD_PROVEE
LEFT JOIN {sch}.medida m ON S11.ID_MEDIDA_STOCK = m.ID_MEDIDA
WHERE S14.T_COMP LIKE 'REM'
  AND S20.TIPO_MOV LIKE 'E'
{dep_clause}  AND CAST(S14.FECHA_MOV AS DATE) >= ?
  AND CAST(S14.FECHA_MOV AS DATE) <= ?
ORDER BY S14.ID_STA14, S14.HORA_COMP
"""
    params = list(dep_params) + [fecha_desde.isoformat(), fecha_hasta.isoformat()]
    rows = _fetch_all(sql, params, database=db)
    fuente = (tango_fuente or "").strip().upper()
    if fuente:
        for r in rows:
            r["tango_fuente"] = fuente
    return rows
