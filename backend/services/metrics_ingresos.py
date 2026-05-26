"""
Métricas por lectura de PDFs (Ingresos / Orden de compra).

Se calcula al vuelo: parsea texto extraído (PyMuPDF/fitz).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import fitz


def _norm_ascii_lower(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _tokens_equal_ci(a: str, b: str) -> bool:
    return _norm_ascii_lower(a.strip()) == _norm_ascii_lower(b.strip())


def _proveedor_human_tokens(proveedor: str) -> list[str]:
    """Nombre del proveedor sin códigos numéricos largos (p. ej. 020099) para alinearlo con texto de ítem/archivo."""
    out: list[str] = []
    for t in proveedor.split():
        if len(t) >= 5 and t.isdigit():
            continue
        if len(t) in (11, 13, 14) and t.isdigit():
            continue  # probable CUIT/documento largo
        out.append(t)
    return out


def _strip_proveedor_from_descripcion(descripcion: str | None, proveedor: str | None) -> str:
    """
    Si la descripción repite literalmente el nombre ya presente en «Proveedor» (concatenados en el PDF,
    metadatos o texto armado desde el nombre del archivo), quita ese prefijo.
    Sólo quita cuando coinciden **todas** las palabras del proveedor desde el inicio (evita dejar sólo una apellido
    cuando en la descripción aparece también el segundo nombre / producto tras el primero).
    """
    d = (descripcion or "").strip()
    p = (proveedor or "").strip()
    if not d or not p:
        return d
    pws = _proveedor_human_tokens(p)
    dws = d.split()
    if not pws or not dws:
        return d
    k = 0
    lim = min(len(pws), len(dws), 8)
    while k < lim and _tokens_equal_ci(dws[k], pws[k]):
        k += 1
    if k == 0 or k != len(pws):
        return d
    stripped = " ".join(dws[k:]).strip()
    # Proveedor de una sola palabra frecuentemente sólo conserva el apellido: no quitar esa palabra si el título ya trae más contexto (nombre + producto).
    if len(pws) == 1 and len(dws) > 2:
        return d
    return stripped or d


_PRODUCT_START_WORDS = frozenset(
    {
        "limpia",
        "limpiador",
        "aceite",
        "lubric",
        "combustible",
        "filtro",
        "filtros",
        "articulo",
        "producto",
        "bobina",
        "semilla",
        "fertiliza",
        "soluc",
        "repuesto",
        "pastilla",
    }
)


def _guess_proveedor_from_named_tail(words: list[str]) -> str | None:
    """
    Heurística típica de renombrado: «FECHA PROVE_APELLIDO PROVE_OTRO texto del producto…».
    Toma hasta 2 nombre propio en MAY/minúscula típico y se detiene en primera palabra de producto.
    """
    if len(words) < 2:
        return None
    taken: list[str] = []
    for w in words[:6]:
        if not w.strip():
            continue
        lw = _norm_ascii_lower(w)
        if any(lw.startswith(p) for p in _PRODUCT_START_WORDS):
            break
        if any(ch.isdigit() for ch in w):
            break
        if lw in ("san", "santa", "los", "las", "el", "de", "del", "la"):
            if not taken:
                continue
            break
        if len(w) < 3:
            continue
        taken.append(w)
        if len(taken) >= 2:
            break
    if len(taken) < 2:
        return None
    return " ".join(taken)


@dataclass
class IngresoItem:
    codigo: str
    descripcion: str
    cantidad: float | None
    um: str | None


@dataclass
class IngresoMetric:
    proveedor: str | None
    fecha: str | None  # dd/mm/yyyy (como aparece)
    remito_interno: str | None
    remito_proveedor: str | None
    deposito: str | None
    orden: str | None
    items: list[IngresoItem]


_RE_PROVEEDOR = re.compile(r"^\s*Proveedor:\s*(.+?)\s*$", re.IGNORECASE)
_RE_FECHA = re.compile(r"^\s*Remito\s+Interno:\s*(\S+)\s+Fecha:\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", re.IGNORECASE)
_RE_REM_PROV = re.compile(r"^\s*Remito\s+Proveedor:\s*(\S+)", re.IGNORECASE)
_RE_DEPOSITO = re.compile(r"^\s*Depósito\s+Gen\.\s*:\s*(.+?)\s*$", re.IGNORECASE)
_RE_ORDEN = re.compile(r"^\s*Observaciones:\s*(.+?)\s*$", re.IGNORECASE)
_RE_CANT_UM = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s+([A-Z]{1,6})\s*$")
# Código típico: alfanumérico y suele incluir al menos un dígito (evita confundir descripciones como "COFIAS")
_RE_CODE = re.compile(r"^(?=.*\d)[A-Z0-9]{4,}$")
_RE_QTY = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*$")
_RE_UM = re.compile(r"^[A-Z]{1,6}$")
_RE_TOTAL_UNIDADES = re.compile(r"^\s*Total\s+de\s+Unidades", re.IGNORECASE)
_RE_TABLE_HEADER = re.compile(r"c[oó]digo|art[ií]culo|descripci[oó]n|cantidad|u/m", re.IGNORECASE)

# Formato alternativo (otros): "Proveedor     : 40733  DIESEL LANGE S.R.L"
_RE_PROVEEDOR_ALT = re.compile(r"^\s*Proveedor\s*:\s*(.+?)\s*$", re.IGNORECASE)
_RE_FECHA_ALT = re.compile(r"^\s*INFORME\s+DE\s+RECEPCION.*?\bFecha\s*:\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", re.IGNORECASE)
_RE_ORDEN_ALT = re.compile(r"^\s*Observaciones\s*:\s*(.+?)\s*$", re.IGNORECASE)
# Tabla alternativa: "01AGR03763   DESC...   2   UNI   1.00"
_RE_ROW_ALT = re.compile(
    r"^\s*([A-Z0-9]{6,})\s+(.+?)\s+(\d+)\s+([A-Z]{1,6})\s+([0-9]+(?:[.,][0-9]+)?)\s*$"
)
_RE_BAD_DESC = re.compile(r"INFORME\s+DE\s+RECEPCION", re.IGNORECASE)

# Plantilla Lacosta / otros: Fecha sin bloque «Remito Interno» junto en la misma línea.
_RE_FECHA_SOLO_LINEA = re.compile(
    r"\bFecha\s*:\s*([0-9]{2}/[0-9]{2}/[0-9]{4})",
    re.IGNORECASE,
)


def _parse_orden_oc_from_line(ln: str) -> str | None:
    """Oc / orden de compra en una línea (varias plantillas)."""
    lr = ln.strip()
    for pat in (
        r"\(\s*OC\s*(\d+)\s*\)",
        r"\borden\s+de\s+compra\s*[:\s#]+\s*(\d+)\b",
        r"\borden\s+de\s+(?:compra|comp\.?\s+)\s*N[ºªoOo°.\s]*[:\s#]*(\d+)\b",
        r"\borden\s+de\s+(?:compra|comp\.?\s+)\s*(\d+)\b",
        r"\bOC\s*N[ºª.]?\s*[:#.\s]*(\d+)\b",
        r"\bOC\s*[:\s#]+\s*(\d+)\b",
        r"\bOC\s+(\d+)\b",
    ):
        m = re.search(pat, lr, re.IGNORECASE)
        if m and m.group(1):
            return m.group(1).strip()
    return None



# Una línea con código largo + descripción + cantidad + UM al final (remitos donde el PDF ordena así).
# Preferir _parse_tail_anchored_row: el modo «.+? cantidad UM» equivoca cuando hay números en la descripción.
_RE_ROW_TAIL_QTY_UM = re.compile(
    r"^\s*([\w\-]{5,})\s+(.+?)\s+([0-9]+(?:[.,][0-9]+)?)\s+([A-Za-zÁÉÍÓÚÄËÏÖÜÂÊÎÔÛÑáéíóúäëïöüâêîôûña-z.]{2,8})\s*$",
    re.IGNORECASE,
)
_RE_ROW_TAIL_QTY_UM_ALT = re.compile(
    r"^\s*((?:[A-Z]{2,}[0-9]{3,}[A-Z0-9]*|[0-9]{5,}[A-Z0-9]{2,}|[\w\-]{6,}))\s+(.+?)\s+([0-9]+(?:[.,][0-9]+)?)\s+([A-Za-zÁÉÍÓÚÑ]{2,8})\s*$",
    re.IGNORECASE,
)
_RE_TAIL_QTY_UM = (
    # 1.234,56 o 1.234 CJ  (Argentina: miles + opcional coma decimal)
    re.compile(
        r"\s+(?P<qty>\d{1,3}(?:\.\d{3})+(?:,\d{1,8})?)\s+(?P<um>[A-Za-zÁÉÍÓÚÄÖÜÑáéíóúÄ][A-Za-z0-9ÄÖÜÑº°.]{1,14})\s*$"
    ),
    # 1234,5 UN — decimal coma sin miles
    re.compile(
        r"\s+(?P<qty>\d{1,12},\d{1,8})\s+(?P<um>[A-Za-zÁÉÍÓÚÄÖÜÑáéíóú][A-Za-z0-9ÄÖÜÑº°.]{1,14})\s*$"
    ),
    # 1234.5 UN — decimal punto
    re.compile(
        r"\s+(?P<qty>\d{1,12}\.\d{1,8})\s+(?P<um>[A-Za-zÁÉÍÓÚÄÖÜÑáéíóú][A-Za-z0-9ÄÖÜÑº°.]{1,14})\s*$"
    ),
    # Entero + UM (p. ej. 2 CJ, 15 UN)
    re.compile(
        r"\s+(?P<qty>[0-9]{1,6})\s+(?P<um>[A-Za-zÁÉÍÓÚÄÖÜÑáéíóúÄ][A-Za-z0-9ÄÖÜÑº°]{1,14})\s*$"
    ),
)
# Palabras OCR que pueden confundirse con UM corto (excepto cuando es un código real conocido más abajo).
_UM_REJECT_TINY = frozenset({"oc", "de", "el", "la", "al", "del", "los", "las", "lo", "es", "si", "no", "en"})
_SKIP_FIRST_ARTICLE_TOKEN = frozenset({"articulo", "articulos", "articulo.", "articulos.", "cantidad", "producto"})
_META_LINE_START = re.compile(
    r"^\s*(Proveedor|Cliente|Remito|Dep[oó]sito|ruc|CUIT|cuit|TEL|Tel[eé]fono|Domicilio|Localidad|OBS|Observa|OBSERV|P[eá]gina|\d{1,2}\s+de\s+\d{1,2})",
    re.IGNORECASE,
)

# Convención habitual al guardar: "DD-MM-YYYY texto… (OC nnn)"
_RE_FN_LEAD_DATE = re.compile(
    r"^\s*(?P<d>\d{1,2})[-_/.\s]+(?P<m>\d{1,2})[-_/.\s]+(?P<y>\d{4})\s+(?P<tail>.+)$"
)
_RE_FN_OC = re.compile(r"\(\s*OC\s*(\d+)\s*\)", re.IGNORECASE)


def _is_item_table_header(ln: str) -> bool:
    """
    Cabeceras tipo remito con varias columnas (no siempre empiezan por «Código»).
    """
    n = _norm_ascii_lower(ln)
    keys = (
        "codigo",
        "articulo",
        "descripcion",
        "cantidad",
        "cant.",
        " u/m",
        "u.m",
        "unidad",
        "importe",
        "precio",
        "item",
    )
    return sum(1 for k in keys if k in n) >= 2


def _looks_skip_for_item_row(ln: str) -> bool:
    if len(ln) < 6:
        return True
    if _META_LINE_START.match(ln):
        return True
    n = _norm_ascii_lower(ln)
    if n.startswith("total") and any(x in n for x in ("unidad", "kilos", "$", "importe", "sub", "gen")):
        return True
    if "total de unidades" in n:
        return True
    return False


def _qty_to_float(raw: str) -> float | None:
    """Interpreta cantidad con formato español-argentino de miles/decimales."""
    s = (raw or "").strip().replace("\u00a0", "").replace(" ", "")
    if not s:
        return None
    # 1.234,56 AR
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,8})?", s):
        if "," in s:
            ints, frac = s.rsplit(",", 1)
            return float(ints.replace(".", "") + "." + frac)
        return float(s.replace(".", ""))
    if re.fullmatch(r"\d+,\d+", s):
        return float(s.replace(",", "."))
    if re.fullmatch(r"\d+\.\d+", s):
        return float(s)
    if re.fullmatch(r"\d+", s):
        return float(s)
    return _to_float(raw)


def _looks_like_article_code(tok: str) -> bool:
    t = tok.strip()
    if len(t) < 4 or t.casefold() in _SKIP_FIRST_ARTICLE_TOKEN:
        return False
    if t.isdigit():
        return 5 <= len(t) <= 14
    # Alfanum con al menos un dígito típico (01AGR…, ART-1020)
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9\-./]+$", t) and any(c.isdigit() for c in t))


def _um_token_ok(u: str) -> bool:
    """UM de 2–14 caracteres típicos CJ, UNI, BOT, KG… excluye partículas muy genéricas."""
    u = u.strip()
    if not (2 <= len(u) <= 14):
        return False
    cup = u.upper().replace("°", "").strip(".")
    if cup == "UN" or cup.startswith("UN.") or cup == "UNI":
        return True
    k = "".join(ch for ch in u.casefold() if ch.isalnum())
    if k == "oc":
        return False
    cf = u.casefold().strip(".")
    if cf in _UM_REJECT_TINY and cf not in ("uni", "ud"):
        return False
    return True


def _parse_tail_anchored_row(ln: str) -> IngresoItem | None:
    """Extrae código + descripción tomando cantidad y UM al final de la línea (evita números en la descripción)."""
    s = " ".join(ln.replace("\t", " ").split()).strip()
    if len(s) < 10:
        return None
    m = None
    for rx in _RE_TAIL_QTY_UM:
        mm = rx.search(s)
        if mm:
            m = mm
            break
    if not m:
        return None
    qty_raw = m.group("qty").strip()
    um_raw = m.group("um").strip()
    if not _um_token_ok(um_raw):
        return None
    cant = _qty_to_float(qty_raw)
    if cant is None or cant < -1e-6 or cant > 1e10:
        return None
    head = s[: m.start()].strip()
    if not head:
        return None
    parts = head.split(None, 1)
    first = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""
    if first.casefold() in _SKIP_FIRST_ARTICLE_TOKEN:
        codigo, desc = "0001", head
    elif _looks_like_article_code(first):
        codigo, desc = first, rest
    else:
        codigo, desc = "0001", head
    desc = desc.strip()
    if not desc:
        codigo, desc = "0001", head.strip()
    if _RE_BAD_DESC.search(desc):
        return None
    if len(desc) < 1:
        return None
    return IngresoItem(codigo=codigo, descripcion=desc, cantidad=cant, um=um_raw.upper() if um_raw.upper() else um_raw)


def _try_parse_item_line(ln: str) -> IngresoItem | None:
    """Última capa: línea completa código + desc + cant + UM."""
    norm = " ".join(ln.replace("\t", " ").split())
    anchor = _parse_tail_anchored_row(norm)
    if anchor is not None:
        return anchor

    for rx in (_RE_ROW_TAIL_QTY_UM_ALT, _RE_ROW_TAIL_QTY_UM):
        m = rx.match(norm)
        if not m:
            continue
        codigo = m.group(1).strip()
        desc = m.group(2).strip()
        cant = _qty_to_float(m.group(3).strip()) or _to_float(m.group(3).strip())
        um = m.group(4).strip()
        if not codigo or len(desc) < 2:
            continue
        if _RE_BAD_DESC.search(desc):
            continue
        lowc = codigo.lower()
        if lowc in ("proveedor", "cliente", "remito", "articulo", "codigo", "codigo."):
            continue
        return IngresoItem(codigo=codigo, descripcion=desc, cantidad=cant, um=um)
    m2 = _RE_ROW_ALT.match(norm)
    if m2:
        codigo = m2.group(1).strip()
        desc = m2.group(2).strip()
        um = m2.group(4).strip()
        cant = _qty_to_float(m2.group(5).strip()) or _to_float(m2.group(5).strip())
        if desc and not _RE_BAD_DESC.search(desc):
            return IngresoItem(codigo=codigo, descripcion=desc, cantidad=cant, um=um)
    return None


def _extract_items_fallback_block(lines: list[str]) -> list[IngresoItem]:
    """
    Para plantillas donde in_table estaba cerrado antes (cabecera distinta) o el texto viene en una línea.
    """
    out: list[IngresoItem] = []
    seen_header = False
    for ln in lines:
        s = " ".join(ln.split())
        if _is_item_table_header(s):
            seen_header = True
            continue
        if not seen_header:
            continue
        if _looks_skip_for_item_row(s):
            continue
        if _RE_TOTAL_UNIDADES.search(s) or (s.lower().startswith("total ") and len(s) < 40):
            break
        it = _try_parse_item_line(s)
        if it:
            out.append(it)
    return out


def _fallback_items_any_line(lines: list[str]) -> list[IngresoItem]:
    """Si no apareció cabecera reconocida, intentar todas las líneas que parecen renglones de ítem."""
    out: list[IngresoItem] = []
    for ln in lines:
        s = " ".join(ln.split())
        if _looks_skip_for_item_row(s):
            continue
        if len(s) > 260:
            continue
        it = _try_parse_item_line(s)
        if it:
            out.append(it)
    return out


def extract_pdf_text(path: Path, max_pages: int = 12) -> str:
    out: list[str] = []
    doc = None
    try:
        doc = fitz.open(str(path))
        for i in range(min(len(doc), max_pages)):
            raw = ""
            try:
                raw = doc[i].get_text(sort=True) or ""
            except (TypeError, AttributeError):
                raw = doc[i].get_text() or ""
            out.append(raw)
    except Exception:
        return ""
    finally:
        try:
            if doc:
                doc.close()
        except Exception:
            pass
    return "\n".join(out)


def _merge_filename_hints(filename: str, m: IngresoMetric, raw_text: str) -> IngresoMetric:
    """
    Si el PDF es escaneado o no coincide con plantilla Tango, el texto llega vacío y no hay ítems.
    Muchos usuarios renombran el archivo como: DD-MM-YYYY Proveedor texto (OC NNN).
    IMPORTANTE: del nombre SOLO se usa fecha (y OC opcional) como último recurso.
    No se generan ítems/descripcion desde el nombre porque contamina la tabla y oculta fallas de parseo del PDF.
    """
    if m.items:
        return m
    stem = Path(filename).stem.strip()
    if not stem:
        return m
    mobj = _RE_FN_LEAD_DATE.match(stem)
    oc_m = _RE_FN_OC.search(stem)
    fecha_hint = None
    orden_hint = oc_m.group(1) if oc_m else None
    if mobj:
        try:
            d, mo, y = int(mobj.group("d")), int(mobj.group("m")), int(mobj.group("y"))
            datetime(y, mo, d)
            fecha_hint = f"{d:02d}/{mo:02d}/{y}"
        except (ValueError, OSError):
            fecha_hint = None

    texto_muy_escaso = len((raw_text or "").strip()) < 30
    pistas_en_nombre = bool(fecha_hint or orden_hint)
    # Sin ítems: usar nombre SOLO para completar metadatos cuando falta texto extraíble
    # (o cuando explícitamente hay fecha/OC en el nombre), nunca para ítems.
    if not texto_muy_escaso and not pistas_en_nombre:
        return m

    return IngresoMetric(
        proveedor=m.proveedor,
        fecha=m.fecha or fecha_hint,
        remito_interno=m.remito_interno,
        remito_proveedor=m.remito_proveedor,
        deposito=m.deposito,
        orden=m.orden or (orden_hint if orden_hint else None),
        items=[],
    )


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(".", "").replace(",", ".")) if s.count(",") == 1 and s.count(".") > 1 else float(s.replace(",", "."))
    except Exception:
        try:
            return float(s.replace(",", "."))
        except Exception:
            return None


def parse_ingreso_text(text: str) -> IngresoMetric:
    proveedor = None
    fecha = None
    remito_interno = None
    remito_proveedor = None
    deposito = None
    orden = None
    items: list[IngresoItem] = []
    total_unidades: float | None = None

    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]

    in_table = False
    qty_queue: list[float] = []
    um_current: str | None = None

    def _assign_from_queue():
        # asignar cantidades en orden a ítems sin cantidad
        nonlocal qty_queue
        if not qty_queue:
            return
        for it in items:
            if not qty_queue:
                break
            if it.cantidad is None:
                it.cantidad = qty_queue.pop(0)

    def _assign_um_to_missing(um: str):
        for it in items:
            if it.um is None:
                it.um = um

    for idx, ln in enumerate(lines):
        # Metadatos (siempre)
        m = _RE_FECHA.search(ln)
        if m:
            remito_interno = m.group(1).strip()
            fecha = m.group(2).strip()
            continue

        m = _RE_REM_PROV.search(ln)
        if m and not remito_proveedor:
            remito_proveedor = m.group(1).strip()
            continue

        m = _RE_PROVEEDOR.search(ln)
        if m:
            proveedor = m.group(1).strip()
            continue

        m = _RE_PROVEEDOR_ALT.match(ln)
        if m and not proveedor:
            proveedor = m.group(1).strip()
            continue

        m = _RE_FECHA_ALT.search(ln)
        if m and not fecha:
            fecha = m.group(1).strip()
            continue

        m = _RE_DEPOSITO.search(ln)
        if m:
            deposito = m.group(1).strip()
            continue

        m = _RE_ORDEN.search(ln)
        if m:
            orden = m.group(1).strip()
            continue

        m = _RE_ORDEN_ALT.match(ln)
        if m and not orden:
            orden = m.group(1).strip()
            continue

        m = _RE_FECHA_SOLO_LINEA.search(ln)
        if m and not fecha:
            fecha = m.group(1).strip()
            continue

        ord_oc = _parse_orden_oc_from_line(ln)
        if ord_oc and not orden:
            orden = ord_oc
            continue

        # Inicio de tabla ("Código…", cabeceras con varias palabras / «Detalle de artículos»)
        if not in_table:
            lnl = _norm_ascii_lower(ln)
            if lnl.startswith("codigo"):
                in_table = True
            elif _is_item_table_header(ln):
                in_table = True
            elif "detalle" in lnl and any(x in lnl for x in ("articulo", "item", "producto", "entrega")):
                in_table = True
            continue

        # Fin de tabla + total
        if _RE_TOTAL_UNIDADES.search(ln):
            mnum = re.search(r"([0-9]+(?:[.,][0-9]+)?)", ln)
            if mnum:
                total_unidades = _to_float(mnum.group(1))
            else:
                # a veces viene en la siguiente línea
                if idx + 1 < len(lines):
                    mnext = _RE_QTY.match(lines[idx + 1].strip())
                    if mnext:
                        total_unidades = _to_float(mnext.group(1))
            break

        # Ignorar headers repetidos
        if _RE_TABLE_HEADER.search(ln):
            continue

        # Tabla alternativa en una línea
        mrow = _RE_ROW_ALT.match(ln)
        if mrow:
            codigo = mrow.group(1).strip()
            desc = mrow.group(2).strip()
            um = mrow.group(4).strip()
            cant = _to_float(mrow.group(5).strip())
            if desc and _RE_BAD_DESC.search(desc):
                continue
            items.append(IngresoItem(codigo=codigo, descripcion=desc, cantidad=cant, um=um))
            continue

        # Código de artículo
        if _RE_CODE.match(ln):
            items.append(IngresoItem(codigo=ln.strip(), descripcion="", cantidad=None, um=None))
            # Si ya hay U/M vigente, aplicarla
            if um_current:
                items[-1].um = um_current
            _assign_from_queue()
            continue

        # Cantidad + UM en una línea
        mqu = _RE_CANT_UM.match(ln)
        if mqu:
            qv = _to_float(mqu.group(1))
            if qv is not None:
                qty_queue.append(qv)
                _assign_from_queue()
            um_current = mqu.group(2).strip()
            _assign_um_to_missing(um_current)
            continue

        # Cantidad sola
        mq = _RE_QTY.match(ln)
        if mq:
            qv = _to_float(mq.group(1))
            if qv is not None:
                qty_queue.append(qv)
                _assign_from_queue()
            continue

        # UM sola (ej: UNI)
        if _RE_UM.match(ln):
            um_current = ln.strip()
            _assign_um_to_missing(um_current)
            continue

        # Descripción: asignar a la primera fila que todavía no tenga descripción
        if items:
            for it in items:
                if not it.descripcion:
                    it.descripcion = ln.strip()
                    break
            else:
                # si todas tienen descripción, anexar a la última (descripciones multilínea)
                items[-1].descripcion = (items[-1].descripcion + " " + ln.strip()).strip()

        _assign_from_queue()

    # Heurística: si existe "Total de Unidades" y hay exactamente 1 ítem sin cantidad,
    # imputar la diferencia contra la suma de cantidades conocidas.
    if total_unidades is not None and items:
        missing_idx = [idx for idx, it in enumerate(items) if it.cantidad is None]
        if len(missing_idx) == 1:
            known_sum = sum((it.cantidad or 0.0) for it in items)
            diff = total_unidades - known_sum
            # tolerancia para errores de redondeo / lectura
            if diff >= 0 and diff <= max(total_unidades, 0.0) + 1e-6:
                items[missing_idx[0]].cantidad = round(diff, 3)

    # Plantilla Lacosta / remitos con cabeceras distinta a solo «Código» o texto en pocas líneas.
    if not items:
        extra_items = _extract_items_fallback_block(lines)
        if not extra_items:
            extra_items = _fallback_items_any_line(lines)
        items = extra_items

    # Limpieza: evitar filas vacías o corruptas + dedupe (algunos PDFs repiten páginas)
    cleaned = []
    seen = set()
    for it in items:
        if not it.codigo or not it.descripcion:
            continue
        if _RE_BAD_DESC.search(it.descripcion):
            continue
        dfix = (
            _strip_proveedor_from_descripcion(it.descripcion, proveedor)
            if proveedor
            else it.descripcion
        )
        it2 = IngresoItem(
            codigo=it.codigo,
            descripcion=dfix,
            cantidad=it.cantidad,
            um=it.um,
        )
        key = (it2.codigo, it2.descripcion, it2.cantidad, it2.um)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(it2)
    items = cleaned

    return IngresoMetric(
        proveedor=proveedor,
        fecha=fecha,
        remito_interno=remito_interno,
        remito_proveedor=remito_proveedor,
        deposito=deposito,
        orden=orden,
        items=items,
    )


def parse_ingreso_pdf(path: Path) -> IngresoMetric:
    text = extract_pdf_text(path)
    m = parse_ingreso_text(text)
    return _merge_filename_hints(path.name, m, text)

