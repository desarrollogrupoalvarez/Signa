"""Extracción de texto de PDFs con pdfplumber."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("remitos")


def extraer_texto_pdf(ruta_pdf: str) -> str:
    """
    Extrae todo el texto del PDF. Retorna string vacío ante cualquier error;
    nunca lanza excepción.
    """
    path = Path(ruta_pdf)
    if not path.is_file():
        logger.warning("PDF_EXTRACT_NO_EXISTE | ruta=%s", ruta_pdf)
        return ""
    try:
        import pdfplumber
    except ImportError:
        logger.warning("PDF_EXTRACT_SIN_PDFPLUMBER | ruta=%s", ruta_pdf)
        return ""
    try:
        partes: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                try:
                    t = page.extract_text() or ""
                except Exception:
                    t = ""
                if t:
                    partes.append(t)
        return "\n".join(partes)
    except (OSError, PermissionError) as ex:
        logger.warning("PDF_EXTRACT_IO | ruta=%s | %s", ruta_pdf, ex)
        return ""
    except Exception as ex:
        logger.warning("PDF_EXTRACT_ERROR | ruta=%s | %s", ruta_pdf, ex)
        return ""
