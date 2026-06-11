"""
Generación de comprobantes PDF (transferencia entre depósitos e informe de recepción).

"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html import escape
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable, Sequence, Union

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NumberLike = Union[str, int, float, Decimal]

LINEA_ESTANDAR_PT = 0.15
LINEA_RECEPCION_PT = 0.06
_FUENTE_RN_INTERNA = "CourierNewComprobante"

MARCO_ALTURA_MIN_DEFAULT_MM = 95.0
MARCO_PADDING_VERTICAL_TOTAL_MM = 5.6
MARCO_OUTSET_MM = 1.25
MARCO_EPSILON_RENDER_PT = 14.0

# Zona de firma (transferencia): espacio vacío inferior derecho, reservado aunque haya muchas líneas
FIRMA_CAJA_ANCHO_MM = 58.0
FIRMA_CAJA_ALTO_MM = 42.0
FIRMA_MARGEN_SUPERIOR_MM = 6.0
_PAGE_A4_W_MM = 210.0
_PAGE_A4_H_MM = 297.0
_DOC_MARGIN_R_MM = 10.0
_DOC_MARGIN_B_MM = 8.0
_FIRMA_TOTAL_ROW_MM = 11.0
_FIRMA_META_KEY = "rf_firma"

# Rectángulo medido al generar el PDF (página 1-based, x/y/w/h normalizados, origen arriba-izq.)
_zona_firma_rect: dict[str, float | int] | None = None


def _resolver_fuente_comprobante() -> str:
    if _FUENTE_RN_INTERNA in pdfmetrics.getRegisteredFontNames():
        return _FUENTE_RN_INTERNA
    rutas: list[Path] = []
    win = os.environ.get("WINDIR")
    if win:
        pf = Path(win) / "Fonts"
        rutas.extend([pf / "cour.ttf", pf / "Courier New.ttf", pf / "cour.otf"])
    rutas.extend(
        [
            Path("/Library/Fonts/Courier New.ttf"),
            Path("/System/Library/Fonts/Supplemental/Courier New.ttf"),
            Path("/usr/share/fonts/truetype/msttcorefonts/couri.ttf"),
        ]
    )
    for archivo in rutas:
        if not archivo.is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont(_FUENTE_RN_INTERNA, str(archivo)))
            return _FUENTE_RN_INTERNA
        except (OSError, ValueError):
            continue
    return "Courier"


_FONT = _resolver_fuente_comprobante()
_BASE_SIZE = 9
_TITLE_SIZE = 10

def _lbl_izquierda(nombre: str) -> str:
    return f"{nombre}:"


def _lbl_derecha(nombre: str) -> str:
    return f"{nombre}:"


# Anchos en caracteres (Courier) para alinear ":" en cabecera de transferencia
_META_LBL_IZQ_CHARS = len("Observaciones")
_META_LBL_DER_CHARS = len("Usuario")

_META_RCV_COL_LBL_TXT_MM = 32.0
_META_RCV_COL_COLON_MM = 3.5
_META_RCV_COL_LBL_D_MM = 14.0
_META_RCV_COL_VAL_D_MM = 36.0
_FILA_TABLA_RCV_ALTO_MM = 5.2


def _lbl_meta_colon(nombre: str, ancho_chars: int) -> str:
    """Etiqueta con ':' alineado verticalmente (espacios no separables)."""
    pad = max(0, ancho_chars - len(nombre))
    return f"{nombre}{'\u00a0' * pad}:"


def _lbl_texto_rcv(nombre: str) -> str:
    """Solo texto de etiqueta (sin ':'), palabras sin salto."""
    return nombre.replace(" ", "\u00a0")


@dataclass
class LineaArticulo:
    """Fila de artículo. ``referencia`` es Descripcion_Adicional de Tango, en la misma línea que ``descripción``."""

    codigo: str
    descripcion: str
    cantidad: NumberLike
    referencia: str | None = None


@dataclass
class DatosComprobanteTransferencia:
    numero_comprobante: str
    fecha: str
    hora: str
    origen_codigo: str
    origen_deposito: str
    destino_codigo: str
    destino_deposito: str
    usuario: str
    observaciones: str
    lineas: Sequence[LineaArticulo] = field(default_factory=tuple)


def datos_comprobante_vacio() -> DatosComprobanteTransferencia:
    return DatosComprobanteTransferencia(
        numero_comprobante="",
        fecha="",
        hora="",
        origen_codigo="",
        origen_deposito="",
        destino_codigo="",
        destino_deposito="",
        usuario="",
        observaciones="",
        lineas=(),
    )


@dataclass
class LineaRecepcion:
    codigo_articulo: str
    descripcion: str
    deposito: str
    unidad_medida: str
    cantidad: NumberLike


@dataclass
class DatosInformeRecepcion:
    numero_informe: str
    fecha: str
    numero_remito: str
    proveedor: str
    observaciones: str
    usuario: str
    deposito_general: str
    lineas: Sequence[LineaRecepcion] = field(default_factory=tuple)


def datos_informe_recepcion_vacio() -> DatosInformeRecepcion:
    return DatosInformeRecepcion(
        numero_informe="",
        fecha="",
        numero_remito="",
        proveedor="",
        observaciones="",
        usuario="",
        deposito_general="",
        lineas=(),
    )


def _str_cabecera(d: Mapping[str, Any], clave: str, default: str) -> str:
    if clave not in d:
        return default
    v = d[clave]
    return "" if v is None else str(v)


def linea_articulo_desde_dict(m: Mapping[str, Any]) -> LineaArticulo:
    try:
        ref_cruda = m.get("referencia", None)
        referencia: str | None = None if ref_cruda is None else str(ref_cruda)
        return LineaArticulo(
            codigo=str(m["codigo"]),
            descripcion=str(m["descripcion"]),
            cantidad=m["cantidad"],
            referencia=referencia,
        )
    except KeyError as e:
        raise ValueError(
            f"Línea de artículo: falta la clave obligatoria {e.args[0]!r}"
        ) from e


def linea_recepcion_desde_dict(m: Mapping[str, Any]) -> LineaRecepcion:
    try:
        return LineaRecepcion(
            codigo_articulo=str(m["codigo_articulo"]),
            descripcion=str(m["descripcion"]),
            deposito=str(m["deposito"]),
            unidad_medida=str(m["unidad_medida"]),
            cantidad=m["cantidad"],
        )
    except KeyError as e:
        raise ValueError(
            f"Línea de recepción: falta la clave obligatoria {e.args[0]!r}"
        ) from e


def datos_transferencia_desde_dict(d: Mapping[str, Any]) -> DatosComprobanteTransferencia:
    base = datos_comprobante_vacio()
    raw_lineas = d.get("lineas", base.lineas)
    if raw_lineas is None:
        raw_lineas = ()
    if isinstance(raw_lineas, (str, bytes, bytearray)) or not isinstance(
        raw_lineas, Sequence
    ):
        raise TypeError(
            "lineas debe ser una secuencia (p. ej. list) de mappings, no "
            f"{type(raw_lineas).__name__!r}"
        )
    lineas_out: list[LineaArticulo] = []
    for i, fila in enumerate(raw_lineas):
        if not isinstance(fila, Mapping):
            raise TypeError(
                f"lineas[{i}] debe ser un mapping (p. ej. dict), no {type(fila).__name__!r}"
            )
        try:
            lineas_out.append(linea_articulo_desde_dict(fila))
        except ValueError as err:
            raise ValueError(f"lineas[{i}]: {err.args[0]}") from err
    return DatosComprobanteTransferencia(
        numero_comprobante=_str_cabecera(d, "numero_comprobante", base.numero_comprobante),
        fecha=_str_cabecera(d, "fecha", base.fecha),
        hora=_str_cabecera(d, "hora", base.hora),
        origen_codigo=_str_cabecera(d, "origen_codigo", base.origen_codigo),
        origen_deposito=_str_cabecera(d, "origen_deposito", base.origen_deposito),
        destino_codigo=_str_cabecera(d, "destino_codigo", base.destino_codigo),
        destino_deposito=_str_cabecera(d, "destino_deposito", base.destino_deposito),
        usuario=_str_cabecera(d, "usuario", base.usuario),
        observaciones=_str_cabecera(d, "observaciones", base.observaciones),
        lineas=tuple(lineas_out),
    )


def datos_recepcion_desde_dict(d: Mapping[str, Any]) -> DatosInformeRecepcion:
    base = datos_informe_recepcion_vacio()
    raw_lineas = d.get("lineas", base.lineas)
    if raw_lineas is None:
        raw_lineas = ()
    if isinstance(raw_lineas, (str, bytes, bytearray)) or not isinstance(
        raw_lineas, Sequence
    ):
        raise TypeError(
            "lineas debe ser una secuencia (p. ej. list) de mappings, no "
            f"{type(raw_lineas).__name__!r}"
        )
    lineas_out: list[LineaRecepcion] = []
    for i, fila in enumerate(raw_lineas):
        if not isinstance(fila, Mapping):
            raise TypeError(
                f"lineas[{i}] debe ser un mapping (p. ej. dict), no {type(fila).__name__!r}"
            )
        try:
            lineas_out.append(linea_recepcion_desde_dict(fila))
        except ValueError as err:
            raise ValueError(f"lineas[{i}]: {err.args[0]}") from err
    return DatosInformeRecepcion(
        numero_informe=_str_cabecera(d, "numero_informe", base.numero_informe),
        fecha=_str_cabecera(d, "fecha", base.fecha),
        numero_remito=_str_cabecera(d, "numero_remito", base.numero_remito),
        proveedor=_str_cabecera(d, "proveedor", base.proveedor),
        observaciones=_str_cabecera(d, "observaciones", base.observaciones),
        usuario=_str_cabecera(d, "usuario", base.usuario),
        deposito_general=_str_cabecera(d, "deposito_general", base.deposito_general),
        lineas=tuple(lineas_out),
    )


def _num_a_decimal(valor: NumberLike) -> Decimal:
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, int):
        return Decimal(valor)
    if isinstance(valor, float):
        return Decimal(str(valor))
    s = str(valor).strip().replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"Cantidad no numérica: {valor!r}") from e


def _fmt_cantidad(cantidad: NumberLike) -> str:
    return f"{_num_a_decimal(cantidad):.2f}"


def _total_cantidades(lineas: Iterable[LineaArticulo]) -> Decimal:
    return sum((_num_a_decimal(l.cantidad) for l in lineas), start=Decimal("0"))


def _total_cantidades_recepcion(lineas: Iterable[LineaRecepcion]) -> Decimal:
    return sum((_num_a_decimal(l.cantidad) for l in lineas), start=Decimal("0"))


def _p(texto: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(texto).replace("\n", "<br/>"), style)


def _p_html_safe(body: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(body, style)


def _descripcion_lineas(l: LineaArticulo, style: ParagraphStyle) -> Paragraph:
    partes: list[str] = []
    if l.descripcion.strip():
        partes.append(l.descripcion.strip())
    if l.referencia and str(l.referencia).strip():
        partes.append(str(l.referencia).strip())
    texto = " ".join(partes)
    inner = escape(texto).replace("\n", "<br/>")
    return _p_html_safe(inner or " ", style)


def _desc_recepcion(lin: LineaRecepcion, style: ParagraphStyle) -> Paragraph:
    t = escape(lin.descripcion.strip()).replace("\n", "<br/>")
    return _p_html_safe(t or " ", style)


def _altura_story_medida(flowables: list, ancho_disponible: float) -> float:
    alto = 0.0
    limite_vertical = float(10**9)
    for f in flowables:
        if isinstance(f, KeepTogether):
            alto += _altura_story_medida(list(f._content), ancho_disponible)
            continue
        if isinstance(f, CondPageBreak):
            continue
        _w, h = f.wrap(ancho_disponible, limite_vertical)
        alto += h
    return alto


def _fabricar_marcados_pagina(doc, alto_marco_primera: float, outset: float):
    def on_primera(canvas, doc_pdf):
        frame_sup_y = doc_pdf.bottomMargin + doc_pdf.height
        x_rect = doc_pdf.leftMargin - outset
        ancho_rect = doc_pdf.width + 2 * outset
        canvas.saveState()
        canvas.setStrokeColor(colors.black)
        canvas.setLineWidth(LINEA_ESTANDAR_PT)
        canvas.rect(
            x_rect,
            frame_sup_y - alto_marco_primera,
            ancho_rect,
            alto_marco_primera,
            stroke=1,
            fill=0,
        )
        canvas.restoreState()

    def on_siguientes(canvas, doc_pdf):
        x_rect = doc_pdf.leftMargin - outset
        y_rect = doc_pdf.bottomMargin - outset
        ancho_rect = doc_pdf.width + 2 * outset
        alto_rect = doc_pdf.height + 2 * outset
        canvas.saveState()
        canvas.setStrokeColor(colors.black)
        canvas.setLineWidth(LINEA_ESTANDAR_PT)
        canvas.rect(x_rect, y_rect, ancho_rect, alto_rect, stroke=1, fill=0)
        canvas.restoreState()

    return on_primera, on_siguientes


def _nuevo_doc_a4(path: Path) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=8 * mm,
    )


def _estilo_base(parent: ParagraphStyle, nombre: str, *, align: int, size: int | None = None) -> ParagraphStyle:
    sz = size if size is not None else _BASE_SIZE
    return ParagraphStyle(
        nombre,
        parent=parent,
        fontName=_FONT,
        fontSize=sz,
        alignment=align,
        leading=sz + 2,
    )


def _estilos_transferencia(styles) -> dict[str, ParagraphStyle]:
    n = styles["Normal"]
    return {
        "title": ParagraphStyle(
            "TituloTransferencia",
            parent=n,
            fontName=_FONT,
            fontSize=_TITLE_SIZE,
            alignment=TA_CENTER,
            spaceAfter=8,
            leading=_TITLE_SIZE + 2,
        ),
        "meta_lbl": _estilo_base(n, "MetaLbl", align=TA_LEFT),
        "meta_lbl_r": _estilo_base(n, "MetaLblR", align=TA_RIGHT),
        "meta_val": _estilo_base(n, "MetaVal", align=TA_LEFT),
        "cell_norm": _estilo_base(n, "CellNorm", align=TA_LEFT),
        "cell_header": _estilo_base(n, "CellHead", align=TA_LEFT),
        "cell_qty": _estilo_base(n, "CellQty", align=TA_CENTER),
        "cell_head_qty": _estilo_base(n, "CellHeadQty", align=TA_RIGHT),
        "cell_qty_hdr": _estilo_base(n, "CellQtyHdr", align=TA_CENTER),
        "total": _estilo_base(n, "TotalQty", align=TA_RIGHT),
    }


def _estilos_recepcion(styles) -> dict[str, ParagraphStyle]:
    n = styles["Normal"]
    return {
        "title": ParagraphStyle(
            "TituloRecepcion",
            parent=n,
            fontName=_FONT,
            fontSize=_TITLE_SIZE,
            alignment=TA_CENTER,
            spaceAfter=8,
            leading=_TITLE_SIZE + 2,
        ),
        "meta_lbl": ParagraphStyle(
            "MetaLblRecv",
            parent=n,
            fontName=_FONT,
            fontSize=_BASE_SIZE,
            alignment=TA_LEFT,
            leading=_BASE_SIZE + 2,
            wordWrap="LTR",
            splitLongWords=0,
        ),
        "meta_colon": _estilo_base(n, "MetaColonRecv", align=TA_LEFT),
        "meta_lbl_r": _estilo_base(n, "MetaLblRRecv", align=TA_RIGHT),
        "meta_val": _estilo_base(n, "MetaValRecv", align=TA_LEFT),
        "cell_norm": _estilo_base(n, "CellNormRecv", align=TA_LEFT),
        "cell_norm_c": _estilo_base(n, "CellNormRecvC", align=TA_CENTER),
        "cell_header": _estilo_base(n, "CellHeadRecv", align=TA_LEFT),
        "cell_header_c": _estilo_base(n, "CellHeadRecvC", align=TA_CENTER),
        "cell_qty": _estilo_base(n, "CellQtyRecv", align=TA_RIGHT),
        "cell_head_qty": _estilo_base(n, "CellHeadQtyRecv", align=TA_RIGHT),
        "total": _estilo_base(n, "TotalQtyRecv", align=TA_RIGHT),
        "total_compact": ParagraphStyle(
            "TotalQtyRecvCompact",
            parent=n,
            fontName=_FONT,
            fontSize=_BASE_SIZE,
            alignment=TA_RIGHT,
            leading=_BASE_SIZE + 1,
            spaceBefore=0,
            spaceAfter=0,
        ),
    }


def placement_firma_transferencia_norm() -> dict[str, float]:
    """
    Rectángulo de firma en coordenadas 0–1 (origen arriba-izquierda, hoja A4).
    Debe coincidir con el espacio reservado al pie de la última página.
    """
    x = (_PAGE_A4_W_MM - _DOC_MARGIN_R_MM - FIRMA_CAJA_ANCHO_MM) / _PAGE_A4_W_MM
    y = (
        _PAGE_A4_H_MM
        - _DOC_MARGIN_B_MM
        - _FIRMA_TOTAL_ROW_MM
        - FIRMA_CAJA_ALTO_MM
        - FIRMA_MARGEN_SUPERIOR_MM
    ) / _PAGE_A4_H_MM
    return {
        "x": x,
        "y": y,
        "w": FIRMA_CAJA_ANCHO_MM / _PAGE_A4_W_MM,
        "h": FIRMA_CAJA_ALTO_MM / _PAGE_A4_H_MM,
    }


def _anotar_zona_firma_pdf(
    path: Path, placement: dict[str, float | int] | None = None
) -> None:
    """Guarda la zona de firma en Keywords (posición real del espacio vacío en el PDF)."""
    try:
        import fitz
    except ImportError:
        return
    import re

    base = placement_firma_transferencia_norm()
    pl = dict(base)
    if placement:
        pl.update(placement)
    page = int(pl.get("page", 1))
    doc = fitz.open(str(path))
    prev = (doc.metadata or {}).get("keywords") or ""
    token = (
        f"{_FIRMA_META_KEY}={page},{pl['x']:.4f},{pl['y']:.4f},"
        f"{pl['w']:.4f},{pl['h']:.4f}"
    )
    prev_clean = re.sub(r"rf_firma=[^\s;]+", "", prev).strip()
    keywords = f"{prev_clean} {token}".strip() if prev_clean else token
    doc.set_metadata({"keywords": keywords})
    doc.saveIncr()
    doc.close()


class _ReservaZonaFirma(Flowable):
    """Espacio vacío para firma; al dibujarse registra su rectángulo en la página."""

    def __init__(self, ancho_contenido: float) -> None:
        self.ancho_contenido = ancho_contenido
        self.ancho_caja = FIRMA_CAJA_ANCHO_MM * mm
        self.alto = FIRMA_CAJA_ALTO_MM * mm

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        return min(self.ancho_contenido, availWidth), self.alto

    def draw(self) -> None:
        global _zona_firma_rect
        c = self.canv
        x_bl, y_bl = c.absolutePosition(0, 0)
        page_w, page_h = c._pagesize
        w_izq = max(self.ancho_contenido - self.ancho_caja, 0)
        x_box = x_bl + w_izq
        _zona_firma_rect = {
            "page": c.getPageNumber(),
            "x": x_box / page_w,
            "y": (page_h - y_bl - self.alto) / page_h,
            "w": self.ancho_caja / page_w,
            "h": self.alto / page_h,
        }


def _bloque_zona_firma(ancho_total: float) -> _ReservaZonaFirma:
    return _ReservaZonaFirma(ancho_total)


def _reserva_vertical_firma_transferencia() -> float:
    return (FIRMA_MARGEN_SUPERIOR_MM + FIRMA_CAJA_ALTO_MM) * mm


def _pie_firma_y_total(ancho: float, total_row: Table) -> list:
    """Espacio de firma + total; fuerza salto de página si no cabe al pie."""
    bloque = KeepTogether(
        [
            Spacer(1, FIRMA_MARGEN_SUPERIOR_MM * mm),
            _bloque_zona_firma(ancho),
            total_row,
        ]
    )
    # Altura aproximada del total + margen para CondPageBreak
    min_restante = _reserva_vertical_firma_transferencia() + 14 * mm
    return [CondPageBreak(min_restante), bloque]


def _linea_horizontal_ancho(ancho: float) -> Table:
    t = Table([[""]], colWidths=[ancho])
    t.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, -1), LINEA_ESTANDAR_PT, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return t


def _tabla_items_con_reglas(
    hdr: list,
    body_rows: list,
    col_widths: list[float],
    qty_col: int,
    *,
    qty_centrado: bool = False,
) -> Table:
    tbl = Table([hdr] + body_rows, colWidths=col_widths, repeatRows=1)
    cmds: list[tuple] = [
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (qty_col, 0), (qty_col, -1), 2),
        ("LEFTPADDING", (qty_col, 0), (qty_col, -1), 2),
        # Líneas horizontales encabezado
        ("LINEABOVE", (0, 0), (-1, 0), LINEA_ESTANDAR_PT, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), LINEA_ESTANDAR_PT, colors.black),
    ]
    if qty_centrado:
        cmds.append(("ALIGN", (qty_col, 0), (qty_col, -1), "CENTER"))
    else:
        cmds.append(("ALIGN", (qty_col, 0), (qty_col, 0), "CENTER"))
        cmds.append(("ALIGN", (qty_col, 1), (qty_col, -1), "RIGHT"))
    tbl.setStyle(TableStyle(cmds))
    return tbl


def _fila_vacia_recepcion(st: dict[str, ParagraphStyle]) -> list:
    vacio = _p("\u00a0", st["cell_norm"])
    vacio_c = _p("\u00a0", st["cell_norm_c"])
    return [vacio, vacio, vacio_c, vacio_c, _p("\u00a0", st["cell_qty"])]


def _tabla_items_recepcion_con_columnas(
    hdr: list,
    body_rows: list,
    col_widths: list[float],
    qty_col: int,
    *,
    st: dict[str, ParagraphStyle],
    filas_relleno_extra: int = 0,
) -> Table:
    """Tabla recepción: solo verticales entre columnas; horizontales en encabezado y cierre (antes del total)."""
    cuerpo = list(body_rows)
    fila_vacia = _fila_vacia_recepcion(st)
    for _ in range(max(0, filas_relleno_extra)):
        cuerpo.append(list(fila_vacia))
    tbl = Table([hdr] + cuerpo, colWidths=col_widths, repeatRows=1)
    ncols = len(col_widths)
    last_row = len(cuerpo)
    dep_col, um_col = 2, 3
    lw = LINEA_RECEPCION_PT
    cmds: list[tuple] = [
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (qty_col, 0), (qty_col, -1), 2),
        ("LEFTPADDING", (qty_col, 0), (qty_col, -1), 2),
        ("LINEABOVE", (0, 0), (-1, 0), lw, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), lw, colors.black),
        ("LINEBELOW", (0, last_row), (-1, last_row), lw, colors.black),
        ("LINERIGHT", (ncols - 1, 0), (ncols - 1, -1), lw, colors.black),
        ("ALIGN", (dep_col, 0), (dep_col, -1), "CENTER"),
        ("ALIGN", (um_col, 0), (um_col, -1), "CENTER"),
        ("ALIGN", (qty_col, 0), (qty_col, 0), "CENTER"),
        ("ALIGN", (qty_col, 1), (qty_col, -1), "RIGHT"),
    ]
    for c in range(1, ncols):
        cmds.append(("LINEBEFORE", (c, 0), (c, -1), lw, colors.black))
    tbl.setStyle(TableStyle(cmds))
    return tbl


def _pie_con_marco(
    doc: SimpleDocTemplate,
    story_antes_pie: list,
    flowables_pie: list,
    *,
    altura_minima_marco_mm: float | None,
) -> tuple[list, float, float]:
    """
    Calcula espacio inferior + pie y el alto del marco en la primera página.
    Misma fórmula que antes: natural, mínimo, relleno, epsilon y tope al frame.
    """
    h_pre = _altura_story_medida(story_antes_pie, doc.width)
    h_pie = _altura_story_medida(flowables_pie, doc.width)
    natural = h_pre + h_pie
    h_min = (
        MARCO_ALTURA_MIN_DEFAULT_MM
        if altura_minima_marco_mm is None
        else float(altura_minima_marco_mm)
    ) * mm
    relleno_v = MARCO_PADDING_VERTICAL_TOTAL_MM * mm
    outset = MARCO_OUTSET_MM * mm
    alto_cuad = doc.height + 2 * outset
    if natural > doc.height:
        alto_marco = alto_cuad
        espacio = 0.0
    else:
        bloque = max(h_min, natural + relleno_v)
        alto_marco = min(bloque, alto_cuad)
        espacio = max(0.0, alto_marco - natural)
    to_add = [Spacer(1, espacio), *flowables_pie]
    alto_marco = min(alto_marco + MARCO_EPSILON_RENDER_PT, alto_cuad)
    return to_add, alto_marco, outset


def _filas_relleno_tabla_hasta_total_rcv(
    doc: SimpleDocTemplate,
    story_antes_tabla: list,
    fila_total: Table,
    *,
    altura_tabla_sin_relleno: float,
    altura_minima_marco_mm: float | None,
) -> tuple[int, float, float]:
    """
    Cuántas filas vacías agregar a la tabla para que su borde inferior
    coincida con la línea horizontal del TOTAL (sin Spacer intermedio).
    """
    inner_w = doc.width
    h_pie = _altura_story_medida([fila_total], inner_w)
    h_arriba = _altura_story_medida(story_antes_tabla, inner_w)
    h_min = (
        MARCO_ALTURA_MIN_DEFAULT_MM
        if altura_minima_marco_mm is None
        else float(altura_minima_marco_mm)
    ) * mm
    relleno_v = MARCO_PADDING_VERTICAL_TOTAL_MM * mm
    outset = MARCO_OUTSET_MM * mm
    alto_cuad = doc.height + 2 * outset
    natural0 = h_arriba + altura_tabla_sin_relleno + h_pie
    if natural0 > doc.height:
        return 0, alto_cuad, outset
    bloque = min(max(h_min, natural0 + relleno_v), alto_cuad)
    objetivo_tabla = bloque - h_pie - h_arriba
    fila_pt = _FILA_TABLA_RCV_ALTO_MM * mm
    filas = 0
    while filas < 120 and (altura_tabla_sin_relleno + filas * fila_pt) < objetivo_tabla - 1:
        filas += 1
    altura_final = altura_tabla_sin_relleno + filas * fila_pt
    natural_f = h_arriba + altura_final + h_pie
    alto_marco = min(max(h_min, natural_f + relleno_v), alto_cuad)
    alto_marco = min(alto_marco + MARCO_EPSILON_RENDER_PT, alto_cuad)
    return filas, alto_marco, outset


def _indexar_texto_post_generacion(out: Path, comprobante_id: int | None = None) -> None:
    try:
        from services.comprobante_text_index import persistir_texto_comprobante

        persistir_texto_comprobante(out, comprobante_id)
    except Exception:
        pass


def generar_transferencia_pdf(
    datos: DatosComprobanteTransferencia,
    ruta_salida: str | Path,
    *,
    titulo: str = "TRANSFERENCIA ENTRE DEPOSITOS",
    altura_minima_marco_mm: float | None = None,
    comprobante_id: int | None = None,
) -> Path:
    global _zona_firma_rect
    _zona_firma_rect = None

    out = Path(ruta_salida).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = _nuevo_doc_a4(out)
    styles = getSampleStyleSheet()
    st = _estilos_transferencia(styles)

    story: list = [_p(titulo, st["title"])]
    inner_w = doc.width
    # Etiquetas ajustadas al ancho del texto (Courier); el valor va pegado al ":"
    w_lbl_i = 28 * mm
    w_lbl_d = 17 * mm
    w_val_d = 38 * mm
    w_rest_i = inner_w - w_lbl_i - w_lbl_d - w_val_d
    if w_rest_i < 30 * mm:
        w_rest_i = max(inner_w - w_lbl_i - w_lbl_d - w_val_d, 25 * mm)

    origen_txt = " ".join(
        x for x in (datos.origen_codigo.strip(), datos.origen_deposito.strip()) if x
    )
    destino_txt = " ".join(
        x for x in (datos.destino_codigo.strip(), datos.destino_deposito.strip()) if x
    )
    usuario_txt = datos.usuario.strip().upper() if datos.usuario else datos.usuario

    meta_rows = [
        [
            _p(_lbl_meta_colon("Comprobante", _META_LBL_IZQ_CHARS), st["meta_lbl"]),
            _p(datos.numero_comprobante, st["meta_val"]),
            _p(_lbl_meta_colon("Fecha", _META_LBL_DER_CHARS), st["meta_lbl"]),
            _p(datos.fecha, st["meta_val"]),
        ],
        [
            _p(_lbl_meta_colon("Origen", _META_LBL_IZQ_CHARS), st["meta_lbl"]),
            _p(origen_txt, st["meta_val"]),
            _p(_lbl_meta_colon("Usuario", _META_LBL_DER_CHARS), st["meta_lbl"]),
            _p(usuario_txt, st["meta_val"]),
        ],
        [
            _p(_lbl_meta_colon("Destino", _META_LBL_IZQ_CHARS), st["meta_lbl"]),
            _p(destino_txt, st["meta_val"]),
            _p(_lbl_meta_colon("Hora", _META_LBL_DER_CHARS), st["meta_lbl"]),
            _p(datos.hora, st["meta_val"]),
        ],
        [
            _p(_lbl_meta_colon("Observaciones", _META_LBL_IZQ_CHARS), st["meta_lbl"]),
            _p(datos.observaciones.strip() or " ", st["meta_val"]),
            "",
            "",
        ],
    ]
    meta_tbl = Table(meta_rows, colWidths=[w_lbl_i, w_rest_i, w_lbl_d, w_val_d])
    meta_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                # Poco espacio entre ":" (fin col. etiqueta) y valor
                ("RIGHTPADDING", (0, 0), (0, -1), 0),
                ("LEFTPADDING", (1, 0), (1, -1), 1),
                ("RIGHTPADDING", (2, 0), (2, -1), 0),
                ("LEFTPADDING", (3, 0), (3, -1), 1),
                ("TOPPADDING", (2, 0), (3, 2), 0),
                ("BOTTOMPADDING", (2, 0), (3, 2), 0),
                ("SPAN", (1, 3), (3, 3)),
            ]
        )
    )
    story.append(meta_tbl)
    story.append(Spacer(1, 10))

    # Ancho mínimo para encabezado "Cantidad" y valores (p. ej. 1234.56) sin partir línea
    w_qty = 24 * mm
    w_art = max((inner_w - w_qty) / 4, 18 * mm)
    w_desc = inner_w - w_art - w_qty
    qty_col = 2

    hdr = [
        _p_html_safe("Artículo", st["cell_header"]),
        _p_html_safe("Descripción", st["cell_header"]),
        _p_html_safe("Cantidad", st["cell_qty_hdr"]),
    ]
    body_rows = [
        [
            _p(l.codigo.strip(), st["cell_norm"]),
            _descripcion_lineas(l, st["cell_norm"]),
            _p_html_safe(
                escape(_fmt_cantidad(l.cantidad)).replace("\n", "<br/>"),
                st["cell_qty"],
            ),
        ]
        for l in datos.lineas
    ]
    articulo_tbl = _tabla_items_con_reglas(
        hdr, body_rows, [w_art, w_desc, w_qty], qty_col, qty_centrado=True
    )
    story.append(articulo_tbl)

    story_pre_total = list(story)
    total = _total_cantidades(datos.lineas)
    total_row = Table(
        [[_p_html_safe(f"TOTAL: {escape(_fmt_cantidad(total))}", st["total"])]],
        colWidths=[inner_w],
    )
    total_row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEABOVE", (0, 0), (-1, 0), LINEA_ESTANDAR_PT, colors.black),
            ]
        )
    )
    pie_flowables = _pie_firma_y_total(inner_w, total_row)

    extras, alto_m, outset = _pie_con_marco(
        doc,
        story_pre_total,
        pie_flowables,
        altura_minima_marco_mm=altura_minima_marco_mm,
    )
    story.extend(extras)

    p1, p2 = _fabricar_marcados_pagina(doc, alto_m, outset)
    doc.build(story, onFirstPage=p1, onLaterPages=p2)
    _anotar_zona_firma_pdf(out, _zona_firma_rect)
    _indexar_texto_post_generacion(out, comprobante_id)
    return out


def generar_recepcion_pdf(
    datos: DatosInformeRecepcion,
    ruta_salida: str | Path,
    *,
    titulo: str = "INFORME DE RECEPCIÓN",
    altura_minima_marco_mm: float | None = None,
    comprobante_id: int | None = None,
) -> Path:
    out = Path(ruta_salida).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = _nuevo_doc_a4(out)
    styles = getSampleStyleSheet()
    st = _estilos_recepcion(styles)

    story: list = [_p(titulo, st["title"])]
    inner_w = doc.width
    w_lbl_txt = _META_RCV_COL_LBL_TXT_MM * mm
    w_colon = _META_RCV_COL_COLON_MM * mm
    w_lbl_d = _META_RCV_COL_LBL_D_MM * mm
    w_colon_d = _META_RCV_COL_COLON_MM * mm
    w_val_d = _META_RCV_COL_VAL_D_MM * mm
    fijos_meta = w_lbl_txt + w_colon + w_lbl_d + w_colon_d + w_val_d
    w_val_l = inner_w - fijos_meta
    if w_val_l < 16 * mm:
        w_val_l = max(inner_w - fijos_meta, 12 * mm)

    usuario_txt = datos.usuario.strip().upper() if datos.usuario else datos.usuario
    vacio = ""
    meta_filas_rcv = [
        [
            _p(_lbl_texto_rcv("Remito interno"), st["meta_lbl"]),
            _p(":", st["meta_colon"]),
            _p(datos.numero_informe.strip(), st["meta_val"]),
            _p(_lbl_texto_rcv("Fecha"), st["meta_lbl_r"]),
            _p(":", st["meta_colon"]),
            _p(datos.fecha.strip(), st["meta_val"]),
        ],
        [
            _p(_lbl_texto_rcv("Remito proveedor"), st["meta_lbl"]),
            _p(":", st["meta_colon"]),
            _p(datos.numero_remito.strip(), st["meta_val"]),
            _p(_lbl_texto_rcv("Usuario"), st["meta_lbl_r"]),
            _p(":", st["meta_colon"]),
            _p(usuario_txt, st["meta_val"]),
        ],
        [
            _p(_lbl_texto_rcv("Proveedor"), st["meta_lbl"]),
            _p(":", st["meta_colon"]),
            _p(datos.proveedor.strip(), st["meta_val"]),
            vacio,
            vacio,
            vacio,
        ],
        [
            _p(_lbl_texto_rcv("Deposito Gen."), st["meta_lbl"]),
            _p(":", st["meta_colon"]),
            _p(datos.deposito_general.strip(), st["meta_val"]),
            vacio,
            vacio,
            vacio,
        ],
        [
            _p(_lbl_texto_rcv("Observaciones"), st["meta_lbl"]),
            _p(":", st["meta_colon"]),
            _p(datos.observaciones.strip() or " ", st["meta_val"]),
            vacio,
            vacio,
            vacio,
        ],
    ]
    meta_tbl_r = Table(
        meta_filas_rcv,
        colWidths=[w_lbl_txt, w_colon, w_val_l, w_lbl_d, w_colon_d, w_val_d],
    )
    meta_tbl_r.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), 1),
                ("LEFTPADDING", (1, 0), (1, -1), 0),
                ("RIGHTPADDING", (1, 0), (1, -1), 2),
                ("LEFTPADDING", (2, 0), (2, -1), 2),
                ("LEFTPADDING", (3, 0), (3, -1), 0),
                ("RIGHTPADDING", (3, 0), (3, -1), 1),
                ("LEFTPADDING", (4, 0), (4, -1), 0),
                ("RIGHTPADDING", (4, 0), (4, -1), 2),
                ("LEFTPADDING", (5, 0), (5, -1), 1),
                ("SPAN", (2, 2), (5, 2)),
                ("SPAN", (2, 3), (5, 3)),
                ("SPAN", (2, 4), (5, 4)),
            ]
        )
    )
    story.append(meta_tbl_r)
    story.append(Spacer(1, 10))

    w_cod = 28 * mm
    w_dep = 13 * mm
    w_um = 13 * mm
    w_qty_r = 24 * mm
    w_descr = inner_w - w_cod - w_dep - w_um - w_qty_r
    qty_ix = 4

    hdr_r = [
        _p_html_safe("Código<br/>Artículo", st["cell_header"]),
        _p_html_safe("Descripción", st["cell_header"]),
        _p_html_safe("Dep", st["cell_header_c"]),
        _p_html_safe("U/M", st["cell_header_c"]),
        _p_html_safe("Cantidad<br/>Unidades", st["cell_head_qty"]),
    ]
    cuerpo_r = [
        [
            _p(li.codigo_articulo.strip(), st["cell_norm"]),
            _desc_recepcion(li, st["cell_norm"]),
            _p(li.deposito.strip(), st["cell_norm_c"]),
            _p(li.unidad_medida.strip(), st["cell_norm_c"]),
            _p_html_safe(
                escape(_fmt_cantidad(li.cantidad)).replace("\n", "<br/>"),
                st["cell_qty"],
            ),
        ]
        for li in datos.lineas
    ]
    col_art = [w_cod, w_descr, w_dep, w_um, w_qty_r]
    tbl_sin_relleno = _tabla_items_recepcion_con_columnas(
        hdr_r, cuerpo_r, col_art, qty_ix, st=st, filas_relleno_extra=0
    )
    _, altura_tbl_base = tbl_sin_relleno.wrap(inner_w, 10**9)

    tot_dec = _total_cantidades_recepcion(datos.lineas)
    fila_tot = Table(
        [[_p_html_safe(f"TOTAL: {escape(_fmt_cantidad(tot_dec))}", st["total_compact"])]],
        colWidths=[inner_w],
    )
    fila_tot.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LINEABOVE", (0, 0), (-1, 0), LINEA_RECEPCION_PT, colors.black),
            ]
        )
    )

    filas_relleno, alto_mc, outset = _filas_relleno_tabla_hasta_total_rcv(
        doc,
        story,
        fila_tot,
        altura_tabla_sin_relleno=altura_tbl_base,
        altura_minima_marco_mm=altura_minima_marco_mm,
    )
    tbl_itm = _tabla_items_recepcion_con_columnas(
        hdr_r, cuerpo_r, col_art, qty_ix, st=st, filas_relleno_extra=filas_relleno
    )
    story.append(tbl_itm)
    story.append(fila_tot)

    p1, p2 = _fabricar_marcados_pagina(doc, alto_mc, outset)
    doc.build(story, onFirstPage=p1, onLaterPages=p2)
    _indexar_texto_post_generacion(out, comprobante_id)
    return out


def generar_transferencia_desde_dict(
    datos_dict: Mapping[str, Any],
    ruta_salida: str | Path,
    *,
    titulo: str = "TRANSFERENCIA ENTRE DEPOSITOS",
    altura_minima_marco_mm: float | None = None,
) -> Path:
    return generar_transferencia_pdf(
        datos_transferencia_desde_dict(datos_dict),
        ruta_salida,
        titulo=titulo,
        altura_minima_marco_mm=altura_minima_marco_mm,
    )


def generar_recepcion_desde_dict(
    datos_dict: Mapping[str, Any],
    ruta_salida: str | Path,
    *,
    titulo: str = "INFORME DE RECEPCIÓN",
    altura_minima_marco_mm: float | None = None,
) -> Path:
    return generar_recepcion_pdf(
        datos_recepcion_desde_dict(datos_dict),
        ruta_salida,
        titulo=titulo,
        altura_minima_marco_mm=altura_minima_marco_mm,
    )


def _ejemplo() -> None:
    demo = DatosComprobanteTransferencia(
        numero_comprobante="TRA 00001-00134432",
        fecha="29/04/2026",
        hora="09:24",
        origen_codigo="2",
        origen_deposito="DEPOSITO CTC SAN RAFAEL",
        destino_codigo="FG",
        destino_deposito="OFICINA DATA CENTER NOC",
        usuario="RROLDAN",
        observaciones="Pedido por Miglierina Horacio",
        lineas=[
            LineaArticulo(
                codigo="01TEC01633",
                descripcion="SW HW S5735 L24T4S-A-V2",
                cantidad="1",
                referencia="QU23A6013404",
            )
        ],
    )
    base = Path(__file__).resolve().parent
    generar_transferencia_pdf(demo, base / "transferencia_generada.pdf")
    print("Generado:", base / "transferencia_generada.pdf")


if __name__ == "__main__":
    _base = Path(__file__).resolve().parent
    _argv = [a.lower() for a in sys.argv[1:]]
    if "recepcion" in _argv or "recepción" in _argv:
        _out_r = generar_recepcion_pdf(
            datos_informe_recepcion_vacio(),
            _base / "plantilla_recepcion_vacia.pdf",
        )
        print("Generado (recepción vacía):", _out_r)
    else:
        _out = generar_transferencia_pdf(
            datos_comprobante_vacio(),
            _base / "plantilla_vacia.pdf",
        )
        print("Generado (plantilla vacía transferencia):", _out)
