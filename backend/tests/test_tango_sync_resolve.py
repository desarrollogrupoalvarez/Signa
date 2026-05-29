"""Pruebas de resolución de PDF en bandeja (colisiones y re-sync sin regenerar)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.tango_sync import _resolve_pdf_bandeja
from services import tango_comprobante_mapper as mapper


class TestResolvePdfBandeja(unittest.TestCase):
    def test_canonical_name(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            f = d / "TRA_20260528_123_RROLDAN.pdf"
            f.write_bytes(b"%PDF-1.4")
            got = _resolve_pdf_bandeja(d, f.name, None)
            self.assertEqual(got, f)

    def test_fname_previo_from_db(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            old = d / "TRA_20260528_123_RROLDAN.pdf"
            old.write_bytes(b"%PDF-1.4")
            new_name = "TRA_20260528_123_RROLDAN_999.pdf"
            got = _resolve_pdf_bandeja(d, new_name, old.name)
            self.assertEqual(got, old)

    def test_suffix_variant(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            alt = d / "TRA_20260528_123_RROLDAN_2.pdf"
            alt.write_bytes(b"%PDF-1.4")
            got = _resolve_pdf_bandeja(d, "TRA_20260528_123_RROLDAN.pdf", None)
            self.assertEqual(got, alt)

    def test_filename_legacy_structure(self):
        h = {
            "Fecha": "2026-05-28",
            "Numero_Comp": 100,
            "USUARIO": "RROLDAN",
            "Id_STA14": 4242,
        }
        name = mapper.filename_transferencia(h)
        self.assertEqual(name, "TRA_20260528_100_RROLDAN.pdf")


if __name__ == "__main__":
    unittest.main()
