#!/usr/bin/env python
"""
Indexa texto y/o rutas de PDFs existentes en comprobante_tango.

Uso:
  python indexar_pdfs_existentes.py          # texto_contenido IS NULL
  python indexar_pdfs_existentes.py --rutas     # solo rellena ruta IS NULL
  python indexar_pdfs_existentes.py --firmados  # solo estado=firmado (recomendado para rutas)
  python indexar_pdfs_existentes.py --todo      # texto o ruta faltantes

Optimizado: un escaneo por apartado, commit por lotes, progreso por registro.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

COMMIT_CADA = 25


def _filas_pendientes(db, modo: str, *, solo_firmados: bool = False):
    from models.comprobante_tango import ComprobanteTango
    from sqlalchemy import or_

    q = db.query(ComprobanteTango)
    if solo_firmados:
        q = q.filter(ComprobanteTango.estado == "firmado")
    if modo == "rutas":
        q = q.filter(
            ComprobanteTango.ruta.is_(None),
            ComprobanteTango.estado == "firmado",
        )
    elif modo == "todo":
        q = q.filter(
            or_(
                ComprobanteTango.texto_contenido.is_(None),
                ComprobanteTango.ruta.is_(None),
            )
        )
    else:
        q = q.filter(ComprobanteTango.texto_contenido.is_(None))
    return q.order_by(ComprobanteTango.id).all()


def _construir_indices(db, apartado_ids: set[int]) -> dict[int, object]:
    from models.apartado import Apartado
    from services.comprobante_text_index import IndiceRutasApartado

    indices: dict[int, IndiceRutasApartado] = {}
    for aid in sorted(apartado_ids):
        apartado = db.query(Apartado).filter(Apartado.id == aid).first()
        if not apartado:
            continue
        print(
            f"Escaneando carpetas | apartado={apartado.codigo} | id={aid} ...",
            flush=True,
        )
        idx = IndiceRutasApartado.build(apartado)
        indices[aid] = idx
        print(
            f"  Índice listo | firmados={len(idx.firmados)} pdf(s) | "
            f"pendientes={len(idx.pendientes)} pdf(s)",
            flush=True,
        )
    return indices


def main() -> int:
    from core.database import SessionLocal
    from models.apartado import Apartado
    from services.comprobante_text_index import indexar_comprobante_por_fila

    modo = "texto"
    if "--rutas" in sys.argv:
        modo = "rutas"
    elif "--todo" in sys.argv:
        modo = "todo"
    solo_firmados = "--firmados" in sys.argv
    if solo_firmados and modo == "texto":
        modo = "rutas"

    db = SessionLocal()
    procesados = 0
    fallidos = 0
    total_inicial = 0
    interrumpido = False

    try:
        rows = _filas_pendientes(db, modo, solo_firmados=solo_firmados)
        total_inicial = len(rows)
        etiqueta = {"texto": "texto", "rutas": "rutas", "todo": "texto/ruta"}[modo]
        if solo_firmados:
            etiqueta += " (solo firmados)"
        print(f"Pendientes de indexar ({etiqueta}): {total_inicial}", flush=True)
        if total_inicial == 0:
            print("Nada que hacer.")
            return 0

        apartado_ids = {int(r.apartado_id) for r in rows}
        indices = _construir_indices(db, apartado_ids)
        apartados_cache: dict[int, Apartado | None] = {}

        for i, row in enumerate(rows, start=1):
            aid = int(row.apartado_id)
            if aid not in apartados_cache:
                apartados_cache[aid] = (
                    db.query(Apartado).filter(Apartado.id == aid).first()
                )
            apartado = apartados_cache[aid]
            if not apartado:
                fallidos += 1
                print(
                    f"[{i}/{total_inicial}] FALLÓ id={row.id} | apartado_id={aid} no encontrado",
                    flush=True,
                )
                continue

            solo_ruta = modo == "rutas" or (
                modo == "todo" and row.texto_contenido and not row.ruta
            )
            indice = indices.get(aid)
            try:
                ok = indexar_comprobante_por_fila(
                    db,
                    row,
                    apartado,
                    solo_ruta=solo_ruta,
                    indice=indice,
                )
            except Exception as ex:
                ok = False
                print(f"[{i}/{total_inicial}] ERROR id={row.id} | {ex}", flush=True)

            if ok:
                procesados += 1
                estado_txt = "OK"
            else:
                fallidos += 1
                estado_txt = "FALLÓ"

            print(
                f"[{i}/{total_inicial}] {estado_txt} id={row.id} | "
                f"{row.pdf_filename} | estado={row.estado}",
                flush=True,
            )

            if i % COMMIT_CADA == 0:
                db.commit()
                print(
                    f"  >> commit en BD ({procesados} ok, {fallidos} fallidos hasta ahora)",
                    flush=True,
                )

        db.commit()
        print("  >> commit final en BD", flush=True)

    except KeyboardInterrupt:
        interrumpido = True
        try:
            db.commit()
            print("\nInterrumpido (Ctrl+C): progreso guardado hasta el último lote.", flush=True)
        except Exception:
            db.rollback()
            print("\nInterrumpido (Ctrl+C): no se pudo guardar el progreso.", flush=True)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(
        f"\nFinalizado: {procesados} procesados, {fallidos} fallidos, "
        f"{max(0, total_inicial - procesados - fallidos)} sin completar"
        + (" (interrumpido)" if interrumpido else ""),
        flush=True,
    )
    return 0 if fallidos == 0 and not interrumpido else 1


if __name__ == "__main__":
    raise SystemExit(main())
