"""Rutas para clientes (UNC Windows) vs rutas del servidor (POSIX en Linux)."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from config import Config


def _norm_linux_prefix(raw: str) -> PurePosixPath:
    s = (raw or "").strip().replace("\\", "/").rstrip("/")
    return PurePosixPath(s) if s else PurePosixPath()


def _norm_unc_root(raw: str) -> str:
    """Normaliza raíz UNC para mostrar en Windows (\\\\servidor\\recurso)."""
    s = (raw or "").strip()
    if not s:
        return s
    s = s.replace("/", "\\")
    if s.startswith("\\\\"):
        return s
    if s.startswith("\\"):
        return "\\" + s
    if s.startswith("//"):
        return "\\\\" + s[2:]
    return "\\\\" + s.lstrip("\\")


def parse_storage_client_path_map(raw: str | None) -> list[tuple[PurePosixPath, str]]:
    """
    STORAGE_CLIENT_PATH_MAP:
      /mnt/signa/transferencias=\\\\SERVIDOR\\Transferencias;/mnt/signa/bandeja=//SERVIDOR/Bandeja
    """
    text = (raw or "").strip()
    if not text:
        return []
    pairs: list[tuple[PurePosixPath, str]] = []
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        linux_s, unc_s = chunk.split("=", 1)
        linux = _norm_linux_prefix(linux_s)
        unc = _norm_unc_root(unc_s)
        if not linux.parts or not unc:
            continue
        pairs.append((linux, unc))
    pairs.sort(key=lambda item: len(item[0].parts), reverse=True)
    return pairs


def _map_cache() -> list[tuple[PurePosixPath, str]]:
    return parse_storage_client_path_map(getattr(Config, "STORAGE_CLIENT_PATH_MAP", ""))


def _normalize_windows_explorer_path(p: str) -> str:
    if not p or not isinstance(p, str):
        return p
    if p.startswith("\\\\?\\UNC\\"):
        return "\\\\" + p[len("\\\\?\\UNC\\") :]
    if p.startswith("\\\\?\\"):
        return p[len("\\\\?\\") :]
    return p


def _path_to_posix_str(path: Path) -> str:
    raw = str(path).replace("\\", "/")
    if raw.startswith("/"):
        return raw
    if os.name != "nt":
        try:
            return str(path.resolve())
        except OSError:
            return raw
    try:
        return str(path.resolve()).replace("\\", "/")
    except OSError:
        return raw


def _server_posix_path(path: Path) -> PurePosixPath:
    return PurePosixPath(_path_to_posix_str(path))


def _posix_to_client(posix: PurePosixPath) -> tuple[str, str]:
    for prefix, unc_root in _map_cache():
        try:
            rel = posix.relative_to(prefix)
        except ValueError:
            continue
        if rel.parts:
            rel_win = "\\".join(rel.parts)
            return f"{unc_root}\\{rel_win}", "unc"
        return unc_root, "unc"
    return str(posix), "posix"


def linux_path_to_client(path: Path) -> tuple[str, str]:
    """
    Convierte ruta del servidor a ruta útil para el cliente.
    Retorna (path, kind) con kind en unc | windows | posix.
    """
    if os.name == "nt":
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        return _normalize_windows_explorer_path(str(resolved)), "windows"

    return _posix_to_client(_server_posix_path(path))


def path_locations(path: Path) -> dict[str, str]:
    """Carpeta/archivo en servidor y equivalente para cliente."""
    file_posix = _server_posix_path(path)
    folder_posix = file_posix.parent

    if os.name == "nt":
        try:
            server_folder = str(path.parent.resolve())
            server_file = str(path.resolve())
        except OSError:
            server_folder = str(folder_posix)
            server_file = str(file_posix)
        client_folder, kind_f = linux_path_to_client(path.parent)
        client_file, kind = linux_path_to_client(path)
    else:
        server_folder = str(folder_posix)
        server_file = str(file_posix)
        client_folder, kind_f = _posix_to_client(folder_posix)
        client_file, kind = _posix_to_client(file_posix)

    unc_folder = client_folder if kind_f == "unc" else server_folder
    unc_file = client_file if kind == "unc" else server_file

    return {
        "server_folder": server_folder,
        "server_file": server_file,
        "client_folder": client_folder,
        "client_file": client_file,
        "client_kind": kind,
        "unc_folder": unc_folder,
        "unc_file": unc_file,
    }
