"""Rutas de bandeja y destino por apartado (depósitos, Sin Firmar, categorías)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import (
    BANDEJA_SUBDIR_CTC,
    BANDEJA_SUBDIR_SAN_RAFAEL,
    CARPETA_AGROINDUSTRIAS,
    CARPETA_TELECOMUNICACIONES,
    Config,
    DIR_TRANSFERENCIAS_CTC,
    DIR_TRANSFERENCIAS_SAN_RAFAEL,
    TANGO_FUENTE_CTC,
    TANGO_FUENTE_SAN_RAFAEL,
)

if TYPE_CHECKING:
    from models.apartado import Apartado

SIN_FIRMAR = "Sin Firmar"

_LEGACY_BANDEJA_TO_FUENTE = {
    BANDEJA_SUBDIR_SAN_RAFAEL.upper(): TANGO_FUENTE_SAN_RAFAEL,
    BANDEJA_SUBDIR_CTC.upper(): TANGO_FUENTE_CTC,
    CARPETA_AGROINDUSTRIAS.upper(): TANGO_FUENTE_SAN_RAFAEL,
    CARPETA_TELECOMUNICACIONES.upper(): TANGO_FUENTE_CTC,
}

_LEGACY_SEGMENT_TO_FUENTE = {
    DIR_TRANSFERENCIAS_SAN_RAFAEL.upper(): TANGO_FUENTE_SAN_RAFAEL,
    DIR_TRANSFERENCIAS_CTC.upper(): TANGO_FUENTE_CTC,
    CARPETA_AGROINDUSTRIAS.upper(): TANGO_FUENTE_SAN_RAFAEL,
    CARPETA_TELECOMUNICACIONES.upper(): TANGO_FUENTE_CTC,
}

_FUENTE_TO_CARPETA_DEFAULT = {
    TANGO_FUENTE_SAN_RAFAEL: CARPETA_AGROINDUSTRIAS,
    TANGO_FUENTE_CTC: CARPETA_TELECOMUNICACIONES,
}


@dataclass(frozen=True)
class CategoriaConfig:
    nombre: str
    keywords: str = ""


@dataclass(frozen=True)
class DepositoConfig:
    carpeta: str
    tango_fuente: str
    cod_depositos: tuple[str, ...]
    categorias: tuple[CategoriaConfig, ...] = ()


def _parse_cod_depositos(raw: str | list | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, list):
        parts = [str(x).strip() for x in raw if str(x).strip()]
        return tuple(parts)
    s = str(raw).replace(";", ",")
    return tuple(x.strip() for x in s.split(",") if x.strip())


def _safe_carpeta(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise ValueError("carpeta de depósito requerida")
    if "/" in n or "\\" in n or ".." in n:
        raise ValueError(f"carpeta inválida: {n}")
    return n


def categorias_from_json(raw: str | list | None) -> list[CategoriaConfig]:
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        s = (raw or "").strip()
        if not s or s == "[]":
            return []
        try:
            items = json.loads(s)
        except json.JSONDecodeError:
            return []
    if not isinstance(items, list):
        return []
    out: list[CategoriaConfig] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        nombre = (str(it.get("nombre") or "")).strip()
        if not nombre or "/" in nombre or "\\" in nombre:
            continue
        kw = (str(it.get("keywords") or "")).strip()
        out.append(CategoriaConfig(nombre=nombre, keywords=kw))
    return out


def _validate_categorias_list(cats: list[CategoriaConfig], *, context: str = "") -> None:
    if not cats:
        raise ValueError(f"{context}debe tener al menos una categoría".strip())
    seen: set[str] = set()
    for c in cats:
        cu = c.nombre.upper()
        if cu in seen:
            raise ValueError(f"categoría duplicada{': ' + context if context else ''}{c.nombre}")
        seen.add(cu)


def depositos_from_json(raw: str | list | None) -> list[DepositoConfig]:
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        s = (raw or "").strip()
        if not s or s == "[]":
            return []
        try:
            items = json.loads(s)
        except json.JSONDecodeError:
            return []
    if not isinstance(items, list):
        return []
    out: list[DepositoConfig] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        carpeta = _safe_carpeta(str(it.get("carpeta") or ""))
        fuente = (str(it.get("tango_fuente") or "")).strip().upper()
        if not fuente:
            continue
        cods = _parse_cod_depositos(it.get("cod_depositos"))
        if not cods:
            cods = ("2",)
        cats = tuple(categorias_from_json(it.get("categorias")))
        out.append(
            DepositoConfig(
                carpeta=carpeta,
                tango_fuente=fuente,
                cod_depositos=cods,
                categorias=cats,
            )
        )
    return out


def depositos_to_json(deps: list[DepositoConfig]) -> str:
    payload = []
    for d in deps:
        item: dict[str, Any] = {
            "carpeta": d.carpeta,
            "tango_fuente": d.tango_fuente,
            "cod_depositos": list(d.cod_depositos),
        }
        if d.categorias:
            item["categorias"] = [
                {"nombre": c.nombre, **({"keywords": c.keywords} if c.keywords else {})}
                for c in d.categorias
            ]
        payload.append(item)
    return json.dumps(payload, ensure_ascii=False)


def categorias_to_json(cats: list[CategoriaConfig]) -> str:
    payload = [{"nombre": c.nombre, **({"keywords": c.keywords} if c.keywords else {})} for c in cats]
    return json.dumps(payload, ensure_ascii=False)


def default_categorias_transferencia(apartado: "Apartado") -> list[CategoriaConfig]:
    kw = (getattr(apartado, "keywords_importante", None) or "").strip()
    if not kw:
        kw = "fibra,bateria,batería"
    return [
        CategoriaConfig(nombre="Regulares"),
        CategoriaConfig(nombre="Importante", keywords=kw),
    ]


def _legacy_global_categorias(apartado: "Apartado") -> list[CategoriaConfig]:
    cats = categorias_from_json(getattr(apartado, "categorias_destino", None))
    if cats:
        return cats
    if getattr(apartado, "modo_flujo", None) == "transferencia":
        return default_categorias_transferencia(apartado)
    return []


def _enrich_depositos_categorias(
    apartado: "Apartado", deps: list[DepositoConfig]
) -> list[DepositoConfig]:
    if getattr(apartado, "modo_flujo", None) != "transferencia":
        return deps
    fallback = tuple(_legacy_global_categorias(apartado))
    if not fallback:
        return deps
    out: list[DepositoConfig] = []
    for d in deps:
        if d.categorias:
            out.append(d)
        else:
            out.append(
                DepositoConfig(
                    carpeta=d.carpeta,
                    tango_fuente=d.tango_fuente,
                    cod_depositos=d.cod_depositos,
                    categorias=fallback,
                )
            )
    return out


def default_depositos_for_apartado(apartado: "Apartado") -> list[DepositoConfig]:
    """Fallback: fuentes Tango globales + cod_deposito del apartado."""
    cod_raw = (getattr(apartado, "cod_deposito", None) or "2").strip()
    cods = _parse_cod_depositos(cod_raw) or ("2",)
    default_cats = ()
    if getattr(apartado, "modo_flujo", None) == "transferencia":
        default_cats = tuple(default_categorias_transferencia(apartado))
    out: list[DepositoConfig] = []
    for src in Config.tango_transferencia_sources():
        carpeta = _FUENTE_TO_CARPETA_DEFAULT.get(src.id, src.id)
        out.append(
            DepositoConfig(
                carpeta=carpeta,
                tango_fuente=src.id,
                cod_depositos=cods,
                categorias=default_cats,
            )
        )
    return out


def parse_depositos(apartado: "Apartado") -> list[DepositoConfig]:
    deps = depositos_from_json(getattr(apartado, "depositos_config", None))
    if not deps:
        deps = default_depositos_for_apartado(apartado)
    return _enrich_depositos_categorias(apartado, deps)


def deposito_por_carpeta(apartado: "Apartado", carpeta: str | None) -> DepositoConfig | None:
    cu = (carpeta or "").strip().upper()
    if not cu:
        return None
    for dep in parse_depositos(apartado):
        if dep.carpeta.upper() == cu:
            return dep
    return None


def parse_categorias_for_deposito(
    apartado: "Apartado",
    *,
    carpeta: str | None = None,
    tango_fuente: str | None = None,
) -> list[CategoriaConfig]:
    """Categorías del depósito indicado (por carpeta o fuente Tango)."""
    if getattr(apartado, "modo_flujo", None) != "transferencia":
        return []
    dep = deposito_por_carpeta(apartado, carpeta) if carpeta else None
    if not dep and tango_fuente:
        dep = deposito_por_fuente(apartado, tango_fuente)
    if dep and dep.categorias:
        return list(dep.categorias)
    fallback = _legacy_global_categorias(apartado)
    return fallback


def parse_categorias(apartado: "Apartado") -> list[CategoriaConfig]:
    """Compat: categorías del primer depósito o legacy global."""
    deps = parse_depositos(apartado)
    if deps and deps[0].categorias:
        return list(deps[0].categorias)
    return _legacy_global_categorias(apartado)


def bandeja_sin_firmar(bandeja_root: Path, carpeta: str) -> Path:
    d = Path(bandeja_root) / _safe_carpeta(carpeta) / SIN_FIRMAR
    d.mkdir(parents=True, exist_ok=True)
    return d


def destino_deposito_root(destino_root: Path, carpeta: str) -> Path:
    d = Path(destino_root) / _safe_carpeta(carpeta)
    d.mkdir(parents=True, exist_ok=True)
    return d


def deposito_por_fuente(apartado: "Apartado", tango_fuente: str | None) -> DepositoConfig | None:
    fuente = (tango_fuente or "").strip().upper()
    if not fuente:
        return None
    for dep in parse_depositos(apartado):
        if dep.tango_fuente == fuente:
            return dep
    return None


def infer_tango_fuente_from_path(ruta: str | Path) -> str | None:
    try:
        parts = [p.upper() for p in Path(ruta).parts]
    except (TypeError, ValueError):
        return None
    part_set = set(parts)
    for name, fuente in _LEGACY_BANDEJA_TO_FUENTE.items():
        if name in part_set:
            return fuente
    for name, fuente in _LEGACY_SEGMENT_TO_FUENTE.items():
        if name in part_set:
            return fuente
    if TANGO_FUENTE_CTC in part_set:
        return TANGO_FUENTE_CTC
    if TANGO_FUENTE_SAN_RAFAEL in part_set:
        return TANGO_FUENTE_SAN_RAFAEL
    return None


def infer_deposito_carpeta_from_path(ruta: str | Path) -> str | None:
    try:
        p = Path(ruta)
        parts = list(p.parts)
    except (TypeError, ValueError):
        return None
    for i, part in enumerate(parts):
        if part.upper() == SIN_FIRMAR.upper() and i > 0:
            return parts[i - 1]
    upper_parts = {x.upper(): x for x in parts}
    for legacy, fuente in _LEGACY_BANDEJA_TO_FUENTE.items():
        if legacy in upper_parts:
            return _FUENTE_TO_CARPETA_DEFAULT.get(fuente, legacy)
    for legacy, fuente in _LEGACY_SEGMENT_TO_FUENTE.items():
        if legacy in upper_parts:
            return _FUENTE_TO_CARPETA_DEFAULT.get(fuente, legacy)
    for part in parts:
        up = part.upper()
        if up in (CARPETA_AGROINDUSTRIAS.upper(), CARPETA_TELECOMUNICACIONES.upper()):
            return part
    return None


def resolve_deposito_carpeta(apartado: "Apartado", *, ruta: str | Path | None, tango_fuente: str | None) -> str:
    carpeta = infer_deposito_carpeta_from_path(ruta) if ruta else None
    if carpeta:
        return carpeta
    dep = deposito_por_fuente(apartado, tango_fuente)
    if dep:
        return dep.carpeta
    deps = parse_depositos(apartado)
    if deps:
        return deps[0].carpeta
    return CARPETA_AGROINDUSTRIAS


def validate_depositos_payload(data: Any, *, modo_flujo: str = "transferencia") -> list[DepositoConfig]:
    if not isinstance(data, list) or len(data) < 1:
        raise ValueError("depositos_config debe ser una lista con al menos un depósito")
    deps = depositos_from_json(data)
    if not deps:
        raise ValueError("depositos_config inválido")
    seen_carpetas: set[str] = set()
    seen_fuentes: set[str] = set()
    for d in deps:
        if not Config.tango_source_by_id(d.tango_fuente):
            raise ValueError(f"tango_fuente desconocida o sin base configurada: {d.tango_fuente}")
        cu = d.carpeta.upper()
        if cu in seen_carpetas:
            raise ValueError(f"carpeta duplicada: {d.carpeta}")
        seen_carpetas.add(cu)
        if d.tango_fuente in seen_fuentes:
            raise ValueError(f"tango_fuente duplicada: {d.tango_fuente}")
        seen_fuentes.add(d.tango_fuente)
        if modo_flujo == "transferencia":
            _validate_categorias_list(list(d.categorias), context=f"{d.carpeta}: ")
    return deps


def validate_categorias_payload(data: Any, *, modo_flujo: str) -> list[CategoriaConfig]:
    """Legacy: categorías globales (se copian a cada depósito si hace falta)."""
    if modo_flujo != "transferencia":
        return []
    if not isinstance(data, list) or len(data) < 1:
        raise ValueError("categorias_destino debe ser una lista con al menos una categoría")
    cats = categorias_from_json(data)
    if not cats:
        raise ValueError("categorias_destino inválido")
    _validate_categorias_list(cats)
    return cats


def _embed_global_categorias_in_depositos(apartado: "Apartado") -> bool:
    """Migra categorias_destino global a cada depósito sin categorías propias."""
    raw = (getattr(apartado, "depositos_config", None) or "").strip()
    if not raw or raw == "[]":
        return False
    deps = depositos_from_json(raw)
    if not deps:
        return False
    if all(d.categorias for d in deps):
        return False
    fallback = tuple(_legacy_global_categorias(apartado))
    if not fallback:
        return False
    apartado.depositos_config = depositos_to_json(_enrich_depositos_categorias(apartado, deps))
    return True


def migrate_apartados_storage(db) -> int:
    """Rellena depositos_config / categorías por depósito en filas existentes."""
    from models.apartado import Apartado

    n = 0
    for a in db.query(Apartado).all():
        changed = False
        raw_d = (getattr(a, "depositos_config", None) or "").strip()
        if not raw_d or raw_d == "[]":
            a.depositos_config = depositos_to_json(default_depositos_for_apartado(a))
            changed = True
        if a.modo_flujo == "transferencia":
            raw_c = (getattr(a, "categorias_destino", None) or "").strip()
            if (not raw_c or raw_c == "[]") and not any(
                d.categorias for d in depositos_from_json(a.depositos_config)
            ):
                # Sin categorías globales ni por depósito: defaults en cada uno
                a.depositos_config = depositos_to_json(default_depositos_for_apartado(a))
                changed = True
            elif _embed_global_categorias_in_depositos(a):
                changed = True
        if changed:
            n += 1
    if n:
        db.commit()
    return n
