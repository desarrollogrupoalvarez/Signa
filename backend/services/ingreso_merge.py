"""
Anexa imágenes escaneo al final de un PDF (remitos IN).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import fitz

MAX_IMAGES = 20
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}

# Respaldo si el PDF no tiene páginas o tamaño inválido
A4_W_PT = 595.0
A4_H_PT = 842.0


def _target_page_size_pt(doc: fitz.Document) -> tuple[float, float]:
    """
    Misma caja de página que la 1.ª hoja del remito, para que al anexar no quede
    desproporcionado frente al documento original.
    """
    if doc.page_count < 1:
        return (A4_W_PT, A4_H_PT)
    r = doc[0].rect
    w, h = float(r.width), float(r.height)
    if w < 2 or h < 2:
        return (A4_W_PT, A4_H_PT)
    return (w, h)


def _fit_image_rect_in_page(iw: int, ih: int, page_w: float, page_h: float) -> fitz.Rect:
    """
    Centrado, aspecto de la imagen, encajada en el recto de página
    (equivalente a object-fit: contain), sin márgenes.
    """
    if iw < 1 or ih < 1:
        return fitz.Rect(0, 0, page_w, page_h)
    img_ar = iw / ih
    page_ar = page_w / page_h
    if img_ar > page_ar:
        w = page_w
        h = page_w / img_ar
    else:
        h = page_h
        w = page_h * img_ar
    x = (page_w - w) / 2
    y = (page_h - h) / 2
    return fitz.Rect(x, y, x + w, y + h)


def append_images_to_pdf_in_place(pdf_path: Path, image_paths: list[Path]) -> int:
    """
    Añade al final de `pdf_path` una página por imagen. Guarda in-place.
    Retorna el número de páginas añadidas.
    Si vienen más de MAX_IMAGES, solo usa las primeras.
    """
    if not image_paths:
        return 0
    to_add = [p for p in image_paths[:MAX_IMAGES] if p.suffix.lower() in ALLOWED_EXT and p.is_file()]
    if not to_add:
        return 0

    doc: fitz.Document | None = None
    tmp = pdf_path.with_suffix(".tmp_merge.pdf")
    try:
        doc = fitz.open(str(pdf_path))
        page_w, page_h = _target_page_size_pt(doc)
        for imgp in to_add:
            _append_one_image(doc, imgp, page_w, page_h)
        doc.save(str(tmp), garbage=4, deflate=True)
        doc.close()
        doc = None
        try:
            tmp.replace(pdf_path)
        except OSError:
            shutil.move(str(tmp), str(pdf_path))
    except Exception:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    return len(to_add)


def _append_one_image(doc: fitz.Document, image_path: Path, page_w: float, page_h: float) -> None:
    from PIL import Image

    with Image.open(str(image_path)) as imr:
        imr = imr.convert("RGB")
        w, h = imr.size

    page = doc.new_page(width=page_w, height=page_h)
    r = _fit_image_rect_in_page(w, h, page_w, page_h)
    page.insert_image(r, filename=str(image_path))
