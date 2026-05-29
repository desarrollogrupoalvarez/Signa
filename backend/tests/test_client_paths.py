"""Pruebas de mapeo mount Linux -> UNC Windows."""

from __future__ import annotations

import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from services import client_paths


class TestClientPaths(unittest.TestCase):
    def test_parse_map(self):
        raw = "/mnt/signa/trans=//SERVER/Transferencias;/mnt/signa/bandeja=\\\\SERVER\\Bandeja"
        pairs = client_paths.parse_storage_client_path_map(raw)
        self.assertEqual(len(pairs), 2)
        prefixes = {str(p[0]) for p in pairs}
        self.assertIn("/mnt/signa/trans", prefixes)
        self.assertIn("/mnt/signa/bandeja", prefixes)
        self.assertTrue(all(p[1].startswith("\\\\") for p in pairs))

    @patch("services.client_paths.os.name", "posix")
    def test_linux_to_unc(self):
        with patch.object(
            client_paths.Config,
            "STORAGE_CLIENT_PATH_MAP",
            "/mnt/signa/trans=\\\\SERVER\\Transferencias",
        ):
            p = PurePosixPath("/mnt/signa/trans/TRA/2026/01/doc.pdf")
            client, kind = client_paths.linux_path_to_client(Path(str(p)))
            self.assertEqual(kind, "unc")
            self.assertEqual(client, "\\\\SERVER\\Transferencias\\TRA\\2026\\01\\doc.pdf")

    @patch("services.client_paths.os.name", "posix")
    def test_linux_without_map_keeps_posix(self):
        with patch.object(client_paths.Config, "STORAGE_CLIENT_PATH_MAP", ""):
            p = PurePosixPath("/home/signa/datos/doc.pdf")
            client, kind = client_paths.linux_path_to_client(Path(str(p)))
            self.assertEqual(kind, "posix")
            self.assertIn("doc.pdf", client)

    @patch("services.client_paths.os.name", "posix")
    def test_path_locations_prefers_unc_in_api_fields(self):
        with patch.object(
            client_paths.Config,
            "STORAGE_CLIENT_PATH_MAP",
            "/mnt/signa/trans=\\\\SERVER\\Transferencias",
        ):
            p = PurePosixPath("/mnt/signa/trans/sub/archivo.pdf")
            locs = client_paths.path_locations(Path(str(p)))
            self.assertEqual(locs["unc_file"], "\\\\SERVER\\Transferencias\\sub\\archivo.pdf")
            self.assertIn("archivo.pdf", locs["server_file"])


if __name__ == "__main__":
    unittest.main()
