"""Agrupa filas Tango, genera PDFs y nombres seguros."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from generador import (
    datos_recepcion_desde_dict,
    datos_transferencia_desde_dict,
    generar_recepcion_pdf,
    generar_transferencia_pdf,
)

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_token(s: str, *, max_len: int = 40) -> str:
    t = _SAFE.sub("_", (s or "").strip())
    return (t[:max_len] or "X").strip("_") or "X"


def _norm_num(val: Any) -> str:
    """Normaliza N_COMP / números que vienen como float o Decimal desde ODBC."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return ""
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return str(val).strip()
    if isinstance(val, Decimal):
        if val == val.to_integral_value():
            return str(int(val))
        return str(val).strip()
    s = str(val).strip()
    if re.fullmatch(r"\d+\.0+", s):
        return s.split(".", 1)[0]
    return s


def _id_sta14(row: Mapping[str, Any]) -> str:
    v = row.get("Id_STA14")
    if v is None:
        v = row.get("ID_STA14")
    if v is None:
        return ""
    return _norm_num(v)


def _fmt_fecha(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%d/%m/%Y")
    if isinstance(val, date):
        return val.strftime("%d/%m/%Y")
    s = str(val).strip()
    if not s:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return s


def _fmt_hora(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%H:%M")
    s = str(val).strip()
    if not s:
        return ""
    if len(s) >= 5 and s[2] == ":":
        return s[:5]
    # HHMMSS o HHMM sin separadores (p.ej. "085147" → "08:51")
    if s.isdigit() and len(s) >= 4:
        return s[:2] + ":" + s[2:4]
    return s


def _hora_compact(val: Any) -> str:
    h = _fmt_hora(val)
    return h.replace(":", "") if h else "0000"


def _fecha_key(val: Any) -> str:
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, datetime):
        return val.date().isoformat()
    s = str(val).strip()
    if len(s) >= 10 and s[4] == "-":
        return s[:10]
    return s


def _yyyymmdd(val: Any) -> str:
    fk = _fecha_key(val)
    try:
        return datetime.strptime(fk[:10], "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        return _safe_token(fk, max_len=8)


def clave_transferencia(row: Mapping[str, Any]) -> str:
    fuente = str(row.get("tango_fuente") or "").strip().upper()
    id14 = _id_sta14(row)
    if id14:
        base = f"STA14:{id14}"
    else:
        t = str(row.get("Codigo_Comp") or row.get("T_COMP") or "TRA").strip()
        n = _norm_num(row.get("Numero_Comp") or row.get("N_COMP"))
        f = _fecha_key(row.get("Fecha"))
        h = _hora_compact(row.get("Hora"))
        u = str(row.get("USUARIO") or "").strip().upper()
        base = f"{t}|{n}|{f}|{h}|{u}"
    return f"{fuente}:{base}" if fuente else base


def clave_ingreso(row: Mapping[str, Any]) -> str:
    fuente = str(row.get("tango_fuente") or "").strip().upper()
    id14 = _id_sta14(row)
    if id14:
        base = f"STA14:{id14}"
    else:
        t = str(row.get("Codigo_Comp") or row.get("T_COMP") or "REM").strip()
        prov = _norm_num(row.get("remito_proveedor") or row.get("N_COMP"))
        rem = _norm_num(row.get("Numero_remito") or row.get("NCOMP_IN_S"))
        f = _fecha_key(row.get("Fecha"))
        h = _hora_compact(row.get("Hora"))
        u = str(row.get("USUARIO") or "").strip().upper()
        base = f"{t}|{prov}|{rem}|{f}|{h}|{u}"
    return f"{fuente}:{base}" if fuente else base


def group_transferencias(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    g: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        g[clave_transferencia(r)].append(dict(r))
    return g


def group_ingresos(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    g: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        g[clave_ingreso(r)].append(dict(r))
    return g


def map_transferencia_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    h = rows[0]
    lineas = []
    for r in rows:
        lineas.append(
            {
                "codigo": str(r.get("Codigo_Producto") or ""),
                "descripcion": str(r.get("Descripcion_Producto") or ""),
                "cantidad": r.get("Cantidad") or 0,
                "referencia": str(r.get("Descripcion_Adicional") or "") or None,
            }
        )
    num = _norm_num(h.get("Numero_Comp"))
    return {
        "numero_comprobante": f"{h.get('Codigo_Comp', 'TRA')} {num}".strip(),
        "fecha": _fmt_fecha(h.get("Fecha")),
        "hora": _fmt_hora(h.get("Hora")),
        "origen_codigo": str(h.get("Cod_Origen") or ""),
        "origen_deposito": str(h.get("Deposito_Origen") or ""),
        "destino_codigo": str(h.get("Cod_Destino") or ""),
        "destino_deposito": str(h.get("Deposito_Destino") or ""),
        "usuario": str(h.get("USUARIO") or ""),
        "observaciones": str(h.get("Observacion") or ""),
        "lineas": lineas,
    }


def map_ingreso_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    h = rows[0]
    lineas = []
    for r in rows:
        lineas.append(
            {
                "codigo_articulo": str(r.get("Codigo_Producto") or ""),
                "descripcion": str(r.get("Descripcion_Producto") or ""),
                "deposito": str(r.get("Cod_Origen") or h.get("Deposito_Origen") or h.get("Cod_Origen") or ""),
                "unidad_medida": str(r.get("u_m") or ""),
                "cantidad": r.get("Cantidad") or 0,
            }
        )
    return {
        "numero_informe": _norm_num(h.get("Numero_remito")),
        "fecha": _fmt_fecha(h.get("Fecha")),
        "numero_remito": _norm_num(h.get("remito_proveedor")),
        "proveedor": str(h.get("proveedor") or ""),
        "observaciones": str(h.get("Observacion") or ""),
        "usuario": str(h.get("USUARIO") or ""),
        "deposito_general": str(h.get("Deposito_Origen") or h.get("Cod_Origen") or ""),
        "lineas": lineas,
    }


def _ymd_to_iso(ymd: str) -> str | None:
    s = (ymd or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _last_segment_is_id(part: str) -> bool:
    p = (part or "").strip().lower()
    return p.startswith("id") and len(p) > 2 and p[2:].isdigit()


def parse_meta_from_filename(name: str) -> tuple[str | None, str | None]:
    """
    Infiere (fecha ISO, usuario Tango) desde nombres generados por esta app.
    Soporta TRA/REM_yyyymmdd_num_user y formatos legacy REM con hora u otros segmentos.
    """
    stem = (name or "").rsplit(".", 1)[0]
    parts = stem.split("_")
    if len(parts) < 2:
        return None, None
    kind = parts[0].upper()

    def _user_from_tail() -> str | None:
        if len(parts) < 2:
            return None
        tail = parts[-1]
        if _last_segment_is_id(tail):
            u = parts[-2] if len(parts) >= 2 else None
        elif tail.isdigit() and len(parts) >= 3:
            # TRA_yyyymmdd_num_usuario_IdSTA14
            u = parts[-2]
        else:
            u = tail
        return (u or "").strip().upper() or None

    if kind == "TRA":
        if len(parts) >= 4 and len(parts[1]) == 8 and parts[1].isdigit():
            return _ymd_to_iso(parts[1]), _user_from_tail()
        ymd = next((p for p in parts if len(p) == 8 and p.isdigit()), None)
        return (_ymd_to_iso(ymd) if ymd else None), _user_from_tail()

    if kind == "REM":
        if len(parts) >= 4 and len(parts[1]) == 8 and parts[1].isdigit():
            return _ymd_to_iso(parts[1]), _user_from_tail()
        ymd = next((p for p in parts if len(p) == 8 and p.isdigit()), None)
        return (_ymd_to_iso(ymd) if ymd else None), _user_from_tail()

    return None, None


def purge_old_format_files(
    bandeja: Path,
    fname_correcto: str,
    h: Mapping[str, Any],
) -> list[str]:
    """
    Elimina del disco (y notifica para que se quite del store) archivos de la
    bandeja que correspondan al mismo comprobante pero con un nombre distinto
    al nombre canónico (fname_correcto).

    Retorna la lista de nombres eliminados.
    """
    num = _norm_num(
        h.get("Numero_Comp")
        or h.get("Numero_remito")
        or h.get("remito_proveedor")
        or ""
    )
    usr = _safe_token(str(h.get("USUARIO") or ""), max_len=16).lower()
    if not num or not usr:
        return []

    eliminados: list[str] = []
    for f in list(bandeja.rglob("*.pdf")):
        if f.name == fname_correcto:
            continue
        stem_lower = f.stem.lower()
        if num in stem_lower and usr in stem_lower:
            try:
                f.unlink()
                eliminados.append(f.name)
            except OSError:
                pass
    return eliminados


def filename_transferencia(h: Mapping[str, Any]) -> str:
    ymd = _yyyymmdd(h.get("Fecha"))
    num = _safe_token(_norm_num(h.get("Numero_Comp")), max_len=20)
    usr = _safe_token(str(h.get("USUARIO") or ""), max_len=16)
    return f"TRA_{ymd}_{num}_{usr}.pdf"


def filename_ingreso(h: Mapping[str, Any]) -> str:
    """Formato alineado con transferencias: REM_yyyymmdd_numeroRemito_usuario.pdf"""
    ymd = _yyyymmdd(h.get("Fecha"))
    num = _safe_token(
        _norm_num(
            h.get("Numero_remito")
            or h.get("NCOMP_IN_S")
            or h.get("remito_proveedor")
            or h.get("N_COMP")
        ),
        max_len=20,
    )
    usr = _safe_token(str(h.get("USUARIO") or ""), max_len=16)
    return f"REM_{ymd}_{num}_{usr}.pdf"


def resolve_output_path(bandeja: Path, preferred_name: str) -> Path:
    """Si el nombre ya existe, agrega sufijo _2, _3… para no pisar otro comprobante."""
    bandeja.mkdir(parents=True, exist_ok=True)
    path = bandeja / preferred_name
    if not path.exists():
        return path
    stem = path.stem
    for n in range(2, 500):
        alt = bandeja / f"{stem}_{n}.pdf"
        if not alt.exists():
            return alt
    raise OSError(f"No se pudo obtener nombre único para {preferred_name}")


def generar_pdf_transferencia(datos: dict[str, Any], bandeja: Path, header_row: Mapping[str, Any]) -> Path:
    preferred = filename_transferencia(header_row)
    out = resolve_output_path(bandeja, preferred)
    generar_transferencia_pdf(datos_transferencia_desde_dict(datos), out)
    return out


def generar_pdf_ingreso(datos: dict[str, Any], bandeja: Path, header_row: Mapping[str, Any]) -> Path:
    preferred = filename_ingreso(header_row)
    out = resolve_output_path(bandeja, preferred)
    generar_recepcion_pdf(datos_recepcion_desde_dict(datos), out)
    return out
