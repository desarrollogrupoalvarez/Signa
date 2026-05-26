from flask import Blueprint, abort, g, jsonify, request

from core.middleware import require_auth
from services import documents
from services import apartados as apartados_svc

bp = Blueprint("configuracion", __name__, url_prefix="/api/configuracion")


@bp.route("/rutas", methods=["GET"])
@require_auth("configuracion:rutas")
def get_rutas():
    """Compat: retorna rutas de los apartados transferencias/ingresos."""
    from config import Config

    t = apartados_svc.get_by_codigo(g.db, "transferencias", active_only=False)
    i = apartados_svc.get_by_codigo(g.db, "ingresos", active_only=False)
    eff = {
        "bandeja_entrada": (t.bandeja_path if t else ""),
        "transferencias_root": (t.destino_path if t else ""),
        "bandeja_ingresos": (i.bandeja_path if i else ""),
        "destino_ingresos": (i.destino_path if i else ""),
    }
    return jsonify(
        {
            "efectivo": eff,
            "sobreescritura": None,
            "env": {
                "BANDEJA_ENTRADA": Config.BANDEJA_ENTRADA,
                "TRANSFERENCIAS_ROOT": Config.TRANSFERENCIAS_ROOT,
                "BANDEJA_INGRESOS": Config.BANDEJA_INGRESOS,
                "DESTINO_INGRESOS": Config.DESTINO_INGRESOS,
            },
        }
    )


@bp.route("/rutas", methods=["PUT"])
@require_auth("configuracion:rutas")
def put_rutas():
    data = request.get_json(force=True) or {}
    pb = data.get("path_bandeja")
    pt = data.get("path_transferencias")
    pbi = data.get("path_bandeja_ingresos")
    pdi = data.get("path_destino_ingresos")
    if not all(isinstance(x, str) for x in (pb, pt, pbi, pdi)):
        abort(400, "Se requieren path_bandeja, path_transferencias, path_bandeja_ingresos, path_destino_ingresos (cadenas)")
    try:
        t = apartados_svc.get_by_codigo(g.db, "transferencias", active_only=False)
        i = apartados_svc.get_by_codigo(g.db, "ingresos", active_only=False)
        if not t or not i:
            abort(500, "Apartados base no encontrados (transferencias/ingresos)")
        t.bandeja_path = pb.strip()
        t.destino_path = pt.strip()
        i.bandeja_path = pbi.strip()
        i.destino_path = pdi.strip()
        g.db.commit()
    except ValueError as e:
        abort(400, str(e))
    except OSError as e:
        g.db.rollback()
        abort(500, f"No se pudo acceder a la ruta: {e}")
    try:
        documents.restart_inbox_watcher()
    except Exception as ex:
        from logging import getLogger

        getLogger("remitos").warning("restart_inbox_watcher: %s", ex)
    t = apartados_svc.get_by_codigo(g.db, "transferencias", active_only=False)
    i = apartados_svc.get_by_codigo(g.db, "ingresos", active_only=False)
    eff = {
        "bandeja_entrada": (t.bandeja_path if t else ""),
        "transferencias_root": (t.destino_path if t else ""),
        "bandeja_ingresos": (i.bandeja_path if i else ""),
        "destino_ingresos": (i.destino_path if i else ""),
    }
    return jsonify({"ok": True, "efectivo": eff})
