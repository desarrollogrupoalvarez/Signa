"""
Apartados: lectura, seed inicial, sincronizacion con rutas legacy, helpers para API.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from services import path_settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from models.apartado import Apartado
    from models.user import User

logger = logging.getLogger("remitos")

AREA_CODIGO_DEFAULT = "daudet"
CODIGO_TRA_DAUDET = "transferencias_daudet"
CODIGO_ING_DAUDET = "ingresos_daudet"


def get_by_codigo(
    db: "Session", codigo: str, *, active_only: bool = True
) -> "Apartado | None":
    from models.apartado import Apartado

    c = (codigo or "").strip()
    if not c:
        return None
    q = db.query(Apartado).filter(Apartado.codigo == c)
    if active_only:
        q = q.filter(Apartado.activo.is_(True))
    return q.first()


def get_by_id(db: "Session", ap_id: int) -> "Apartado | None":
    from models.apartado import Apartado

    return db.query(Apartado).filter(Apartado.id == ap_id).first()


def get_by_prefijo(
    db: "Session", pref: str, *, active_only: bool = True
) -> "Apartado | None":
    from models.apartado import Apartado

    p = (pref or "").strip()
    if not p:
        return None
    q = db.query(Apartado).filter(Apartado.prefijo == p)
    if active_only:
        q = q.filter(Apartado.activo.is_(True))
    return q.first()


def list_active_apartados(db: "Session") -> list:
    from models.apartado import Apartado

    return (
        db.query(Apartado)
        .filter(Apartado.activo.is_(True))
        .order_by(Apartado.orden, Apartado.codigo)
        .all()
    )


def get_default_by_modo_flujo(db: "Session", modo_flujo: str) -> "Apartado | None":
    from models.apartado import Apartado
    from models.area import Area

    return (
        db.query(Apartado)
        .outerjoin(Area, Apartado.area_id == Area.id)
        .filter(Apartado.modo_flujo == modo_flujo, Apartado.activo.is_(True))
        .order_by(Area.orden, Apartado.orden, Apartado.codigo)
        .first()
    )


def briefs_for_effective_user(db: "Session", user: "User | None") -> list[dict]:
    """Lista ordenada por area y apartado visible segun rol y asignacion."""
    from core.apartado_access import effective_apartados_for_user

    if not user or not user.role:
        return []
    rows = effective_apartados_for_user(db, user, user.role.name)
    return [a.to_brief() for a in rows]


def codigos_for_jwt_user(db: "Session", user: "User | None") -> list[str]:
    d = briefs_for_effective_user(db, user)
    return [x["codigo"] for x in d]


def _ensure_default_area(db: "Session"):
    from models.area import Area

    area = db.query(Area).filter(Area.codigo == AREA_CODIGO_DEFAULT).first()
    if not area:
        area = Area(
            codigo=AREA_CODIGO_DEFAULT,
            nombre="Depósito Daudet",
            activo=True,
            orden=0,
        )
        db.add(area)
        db.flush()
    return area


def seed_default_apartados_from_legacy_if_empty(db: "Session") -> int:
    """
    Si no hay filas, crea area Daudet + transferencias_daudet e ingresos_daudet desde env.
    """
    from models.apartado import Apartado

    n = db.query(Apartado).count()
    if n > 0:
        return 0

    eff = path_settings.get_legacy_merged(db)
    tra_b = (eff.get("bandeja_entrada") or "").strip()
    tra_d = (eff.get("transferencias_root") or "").strip()
    ing_b = (eff.get("bandeja_ingresos") or "").strip()
    ing_d = (eff.get("destino_ingresos") or "").strip()
    if not (tra_b and tra_d and ing_b and ing_d):
        logger.warning("seed apartados: rutas incompletas, no se insertaron filas")
        return 0

    from services.apartado_paths import (
        default_depositos_for_apartado,
        depositos_to_json,
    )

    area = _ensure_default_area(db)
    tra = Apartado(
        area_id=area.id,
        codigo=CODIGO_TRA_DAUDET,
        nombre="Transferencias Daudet",
        bandeja_path=tra_b,
        destino_path=tra_d,
        modo_flujo="transferencia",
        prefijo="td",
        activo=True,
        orden=0,
    )
    ing = Apartado(
        area_id=area.id,
        codigo=CODIGO_ING_DAUDET,
        nombre="Ingresos Daudet",
        bandeja_path=ing_b,
        destino_path=ing_d,
        modo_flujo="ingreso",
        prefijo="id",
        activo=True,
        orden=1,
    )
    tra.depositos_config = depositos_to_json(default_depositos_for_apartado(tra))
    tra.categorias_destino = "[]"
    ing.depositos_config = depositos_to_json(default_depositos_for_apartado(ing))
    ing.categorias_destino = "[]"
    db.add(tra)
    db.add(ing)
    db.commit()
    path_settings.invalidate_cache()
    logger.info("Seed apartados: area daudet + transferencias_daudet + ingresos_daudet")
    return 2


def sync_tra_ing_from_resolved_dict(db: "Session", eff: dict[str, str]) -> None:
    """Mantiene apartados default por modo_flujo alineados con get_resolved."""
    t = get_default_by_modo_flujo(db, "transferencia")
    i = get_default_by_modo_flujo(db, "ingreso")
    if t:
        t.bandeja_path = eff.get("bandeja_entrada") or t.bandeja_path
        t.destino_path = eff.get("transferencias_root") or t.destino_path
    if i:
        i.bandeja_path = eff.get("bandeja_ingresos") or i.bandeja_path
        i.destino_path = eff.get("destino_ingresos") or i.destino_path
    if t or i:
        db.commit()
        path_settings.invalidate_cache()


def tango_usernames_for_apartado(db: "Session", apartado: "Apartado") -> list[str]:
    from models.user import User

    try:
        users = list(apartado.users)
    except Exception:
        users = []
    names = []
    for u in users:
        if getattr(u, "is_active", True) is False:
            continue
        un = (getattr(u, "username", None) or "").strip().upper()
        if un:
            names.append(un)
    if names:
        return sorted(set(names))
    from models.apartado import Apartado as ApartadoModel

    rows = (
        db.query(User)
        .join(User.apartados)
        .filter(User.is_active.is_(True), ApartadoModel.id == apartado.id)
        .all()
    )
    return sorted({(u.username or "").strip().upper() for u in rows if (u.username or "").strip()})


def count_apartados_modo_en_area(db: "Session", area_id: int, modo_flujo: str) -> int:
    from models.apartado import Apartado

    return (
        db.query(Apartado)
        .filter(
            Apartado.area_id == int(area_id),
            Apartado.modo_flujo == modo_flujo,
            Apartado.activo.is_(True),
        )
        .count()
    )


def create_apartado(
    db: "Session",
    *,
    codigo: str,
    nombre: str,
    bandeja_path: str,
    destino_path: str,
    modo_flujo: str,
    prefijo: str,
    area_id: int,
    activo: bool = True,
    orden: int | None = None,
    cod_deposito: str | None = "",
    depositos_config: list | str | None = None,
    categorias_destino: list | str | None = None,
) -> "Apartado":
    from models.apartado import Apartado
    from services import areas as areas_svc

    if modo_flujo not in ("transferencia", "ingreso"):
        raise ValueError("modo_flujo debe ser transferencia o ingreso")
    c = (codigo or "").strip()
    p = (prefijo or "").strip()
    if not c or not p or len(p) > 8:
        raise ValueError("codigo y prefijo requeridos (prefijo max 8 caracteres)")
    area = areas_svc.get_by_id(db, int(area_id))
    if not area:
        raise ValueError("area_id invalido")
    for label, s in (("bandeja_path", bandeja_path), ("destino_path", destino_path)):
        t = (s or "").strip()
        if not t or not Path(t).is_absolute():
            raise ValueError(f"{label} requerido y debe ser ruta absoluta (o UNC)")
    if db.query(Apartado).filter(Apartado.codigo == c).first():
        raise ValueError("El codigo ya existe")
    if db.query(Apartado).filter(Apartado.prefijo == p).first():
        raise ValueError("El prefijo ya esta en uso")
    from services.apartado_paths import (
        DepositoConfig,
        default_depositos_for_apartado,
        depositos_from_json,
        depositos_to_json,
        validate_categorias_payload,
        validate_depositos_payload,
    )

    o = orden if orden is not None else (db.query(Apartado).count() + 1)
    cod_dep = (cod_deposito or "").strip()
    tmp = Apartado(
        area_id=area.id,
        codigo=c,
        nombre=(nombre or c).strip() or c,
        bandeja_path=(bandeja_path or "").strip(),
        destino_path=(destino_path or "").strip(),
        modo_flujo=modo_flujo,
        prefijo=p,
        activo=activo,
        orden=o,
        cod_deposito=cod_dep,
    )
    if depositos_config is not None:
        deps = validate_depositos_payload(depositos_config, modo_flujo=modo_flujo)
        dep_json = depositos_to_json(deps)
    else:
        dep_json = depositos_to_json(default_depositos_for_apartado(tmp))
    cat_json = "[]"
    if modo_flujo in ("transferencia", "ingreso") and categorias_destino is not None:
        global_cats = validate_categorias_payload(categorias_destino, modo_flujo=modo_flujo)
        deps_parsed = depositos_from_json(dep_json)
        if global_cats and deps_parsed and not any(d.categorias for d in deps_parsed):
            cat_tuple = tuple(global_cats)
            deps_parsed = [
                DepositoConfig(
                    carpeta=d.carpeta,
                    tango_fuente=d.tango_fuente,
                    cod_depositos=d.cod_depositos,
                    categorias=cat_tuple,
                )
                for d in deps_parsed
            ]
            dep_json = depositos_to_json(deps_parsed)

    a = Apartado(
        area_id=area.id,
        codigo=c,
        nombre=tmp.nombre,
        bandeja_path=tmp.bandeja_path,
        destino_path=tmp.destino_path,
        modo_flujo=modo_flujo,
        prefijo=p,
        activo=activo,
        orden=o,
        cod_deposito=cod_dep,
        depositos_config=dep_json,
        categorias_destino=cat_json,
    )
    db.add(a)
    return a


def apply_apartado_config_fields(ap: "Apartado", data: dict) -> None:
    from services.apartado_paths import (
        DepositoConfig,
        depositos_from_json,
        depositos_to_json,
        validate_categorias_payload,
        validate_depositos_payload,
    )

    for key in (
        "nombre",
        "bandeja_path",
        "destino_path",
        "modo_flujo",
        "activo",
        "orden",
        "cod_deposito",
        "keywords_importante",
    ):
        if key in data and data[key] is not None:
            if key == "nombre":
                n = str(data[key]).strip()
                if not n:
                    raise ValueError("nombre requerido")
                setattr(ap, key, n)
            else:
                setattr(ap, key, data[key])
    if "area_id" in data and data["area_id"] is not None:
        from sqlalchemy.orm import object_session

        sess = object_session(ap)
        if not sess:
            raise ValueError("area_id invalido")
        from services import areas as areas_svc

        area = areas_svc.get_by_id(sess, int(data["area_id"]))
        if not area:
            raise ValueError("area_id invalido")
        ap.area_id = area.id
    if "modo_flujo" in data and ap.modo_flujo not in ("transferencia", "ingreso"):
        raise ValueError("modo_flujo debe ser transferencia o ingreso")
    for label in ("bandeja_path", "destino_path"):
        if label in data and data[label] is not None:
            t = str(data[label]).strip()
            if not t or not Path(t).is_absolute():
                raise ValueError(f"{label} requerido y debe ser ruta absoluta (o UNC)")
    if "depositos_config" in data and data["depositos_config"] is not None:
        deps = validate_depositos_payload(
            data["depositos_config"], modo_flujo=ap.modo_flujo
        )
        ap.depositos_config = depositos_to_json(deps)
        ap.categorias_destino = "[]"
    if "categorias_destino" in data and data["categorias_destino"] is not None:
        if ap.modo_flujo == "transferencia":
            global_cats = validate_categorias_payload(
                data["categorias_destino"], modo_flujo=ap.modo_flujo
            )
            deps = depositos_from_json(ap.depositos_config)
            if deps and global_cats:
                cat_tuple = tuple(global_cats)
                ap.depositos_config = depositos_to_json(
                    [
                        DepositoConfig(
                            carpeta=d.carpeta,
                            tango_fuente=d.tango_fuente,
                            cod_depositos=d.cod_depositos,
                            categorias=d.categorias or cat_tuple,
                        )
                        for d in deps
                    ]
                )
            ap.categorias_destino = "[]"
        else:
            ap.categorias_destino = "[]"


def update_apartado(db: "Session", ap: "Apartado", data: dict) -> "Apartado":
    apply_apartado_config_fields(ap, data)
    return ap


def assign_user_apartados_by_ids(db: "Session", user: "User", apartado_ids: list[int] | None) -> None:
    from models.apartado import Apartado
    from models.user import User as UserModel

    u = db.query(UserModel).filter(UserModel.id == user.id).first()
    if not u:
        raise LookupError("Usuario no encontrado")
    if (u.role and u.role.name) == "superadmin":
        u.apartados = []
        return
    if not apartado_ids:
        u.apartados = []
        return
    ap_rows = (
        db.query(Apartado).filter(Apartado.id.in_(apartado_ids), Apartado.activo.is_(True)).all()
    )
    u.apartados = ap_rows


def assign_user_areas_by_ids(db: "Session", user: "User", area_ids: list[int] | None) -> None:
    from models.area import Area
    from models.user import User as UserModel

    u = db.query(UserModel).filter(UserModel.id == user.id).first()
    if not u:
        raise LookupError("Usuario no encontrado")
    if (u.role and u.role.name) == "superadmin":
        u.areas = []
        return
    if not area_ids:
        u.areas = []
        return
    rows = db.query(Area).filter(Area.id.in_(area_ids), Area.activo.is_(True)).all()
    u.areas = rows
