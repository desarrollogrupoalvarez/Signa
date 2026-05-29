"""
PDF signing logic using PyMuPDF.
"""

import base64
import io
from pathlib import Path

import fitz
from PIL import Image

SIGNATURE_INSERT_DPI = 220


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _upscale_signature_if_needed(img: Image.Image, rect: fitz.Rect) -> Image.Image:
    """Escala la firma si llega con pocos píxeles para el rectángulo en el PDF."""
    scale = SIGNATURE_INSERT_DPI / 72.0
    target_w = max(1, int(rect.width * scale))
    target_h = max(1, int(rect.height * scale))
    iw, ih = img.size
    if iw >= target_w and ih >= target_h:
        return img
    ratio = min(target_w / iw, target_h / ih)
    if ratio <= 1.0:
        return img
    nw = max(1, int(iw * ratio))
    nh = max(1, int(ih * ratio))
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def sign_pdf(source: Path, firma_b64: str, page_num: int, placement: dict, dest_dir: Path) -> Path:
    """
    Embed the signature image into `source` at `placement` (x, y, w, h in [0,1])
    on `page_num` (1-based). Saves the signed copy to `dest_dir` and returns its path.
    """
    raw = firma_b64.split(",", 1)[1] if "," in firma_b64 else firma_b64
    firma_bytes = base64.b64decode(raw)

    img = Image.open(io.BytesIO(firma_bytes))
    if img.format not in ("PNG", "JPEG", "WEBP"):
        raise ValueError("Formato de firma inválido")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    firma_bytes = buf.getvalue()

    x = _clamp(float(placement.get("x", 0)))
    y = _clamp(float(placement.get("y", 0)))
    w = _clamp(float(placement.get("w", 0.2)))
    h = _clamp(float(placement.get("h", 0.1)))
    if w < 0.01 or h < 0.01:
        raise ValueError("Tamaño de firma inválido")
    w = min(w, 1.0 - x)
    h = min(h, 1.0 - y)

    doc = fitz.open(str(source))
    if page_num < 1 or page_num > len(doc):
        doc.close()
        raise ValueError("Número de página fuera de rango")

    page = doc[page_num - 1]
    pr = page.rect
    rect = fitz.Rect(x * pr.width, y * pr.height, (x + w) * pr.width, (y + h) * pr.height)
    img = _upscale_signature_if_needed(img, rect)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    firma_bytes = buf.getvalue()
    page.insert_image(rect, stream=firma_bytes)

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name
    doc.save(str(dest), garbage=4, deflate=True)
    doc.close()
    return dest
