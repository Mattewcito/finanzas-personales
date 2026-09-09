"""
routes/presupuesto.py
=======================
API de presupuesto por 3 baldes (Necesidades / Gustos / Ahorro-deudas),
mapeo de categorías a balde, y metas de ahorro -- de la cuenta que se
esté VIENDO (`viendo_id()`, ver auth.py). Ver
requisitos/2026-09-08_presupuesto-ahorro-deudas.md para el diseño
completo.

Aislamiento: SIEMPRE viendo_id(), NUNCA session["usuario_id"] a secas --
presupuesto/categoria_balde/metas_ahorro son CONTENIDO/datos de la
cuenta que se esté viendo (igual que tarjetas/movimientos/perfil
financiero), no autoservicio ligado a la identidad de quien inició
sesión. Mismo criterio exacto que routes/tarjetas.py.

Este archivo es SOLO la API (JSON) -- no sirve ninguna plantilla/página
todavía. La sección nueva del dashboard que consuma estos endpoints es
trabajo de frontend-dataviz (fuera de alcance de este cambio).

Endpoints (todos requieren sesión iniciada; mismo patrón "todo POST,
acción en la URL" que ya usan routes/tarjetas.py y routes/correo.py):
  GET  /api/presupuesto                          -> {presupuesto, categoria_balde, baldes}
  POST /api/presupuesto/guardar                    -> guarda los 3 porcentajes
  POST /api/presupuesto/categoria/asignar           -> reasigna UNA categoría a un balde
  GET  /api/metas-ahorro                            -> todas (activas y archivadas) de viendo_id(), con avance
  POST /api/metas-ahorro/crear                      -> alta
  POST /api/metas-ahorro/<id>/editar                -> edición parcial
  POST /api/metas-ahorro/<id>/archivar              -> soft delete (activa=0)
  POST /api/metas-ahorro/<id>/borrar                -> borrado definitivo (falla si tiene aportes)
"""
from flask import Blueprint, jsonify, request

import db_finanzas as db
from auth import login_required, viendo_id

presupuesto_bp = Blueprint("presupuesto", __name__)


# ============================================================================
# Presupuesto (3 porcentajes) + mapeo de categorías a balde
# ============================================================================

@presupuesto_bp.route("/api/presupuesto", methods=["GET"])
@login_required
def api_obtener_presupuesto():
    """Todo lo que necesita la pantalla de configuración de presupuesto
    en una sola llamada: los 3 porcentajes (o el default 50/30/20 si
    todavía no se configuró nada), el mapeo categoría->balde YA
    autopoblado con defaults razonables, y el catálogo de baldes (id +
    label) para no hardcodear el texto en el frontend."""
    with db.conexion() as conn:
        presupuesto = db.obtener_presupuesto(conn, usuario_id=viendo_id())
        categoria_balde = db.obtener_mapeo_categorias(conn, usuario_id=viendo_id())
    return jsonify(ok=True, presupuesto=presupuesto, categoria_balde=categoria_balde, baldes=db.BALDES_PRESUPUESTO)


def _parsear_pct(valor_raw: str | None) -> tuple[float | None, str | None]:
    """Devuelve (pct, None) si es válido, o (None, mensaje_de_error) si
    no. Vacío/None es inválido acá -- a diferencia de _parsear_cupo() de
    tarjetas, los 3 porcentajes son SIEMPRE obligatorios al guardar (no
    hay "edición parcial" de presupuesto: guardar siempre reemplaza los
    3 juntos, ver db.guardar_presupuesto())."""
    if valor_raw is None or valor_raw.strip() == "":
        return None, "Falta un porcentaje."
    try:
        pct = float(valor_raw)
    except ValueError:
        return None, "Ese porcentaje no es un número válido."
    if pct < 0:
        return None, "Ningún porcentaje puede ser negativo."
    return pct, None


@presupuesto_bp.route("/api/presupuesto/guardar", methods=["POST"])
@login_required
def api_guardar_presupuesto():
    """Guarda los 3 porcentajes juntos (siempre los 3, nunca uno solo --
    ver db.guardar_presupuesto()). No exige que sumen 100 (se avisa, no
    se bloquea -- ver el documento de requisitos, "Algo a cuidar entre
    todos"): la respuesta siempre incluye "suma_pct" para que el
    frontend pueda mostrar la advertencia si corresponde."""
    pct_necesidades, error = _parsear_pct(request.form.get("pct_necesidades"))
    if error:
        return jsonify(ok=False, error=f"Necesidades: {error}"), 400
    pct_gustos, error = _parsear_pct(request.form.get("pct_gustos"))
    if error:
        return jsonify(ok=False, error=f"Gustos: {error}"), 400
    pct_ahorro_deudas, error = _parsear_pct(request.form.get("pct_ahorro_deudas"))
    if error:
        return jsonify(ok=False, error=f"Ahorro/deudas: {error}"), 400

    with db.conexion() as conn:
        try:
            presupuesto = db.guardar_presupuesto(
                conn, usuario_id=viendo_id(),
                pct_necesidades=pct_necesidades, pct_gustos=pct_gustos, pct_ahorro_deudas=pct_ahorro_deudas,
            )
        except ValueError as e:
            return jsonify(ok=False, error=str(e)), 400

    return jsonify(ok=True, presupuesto=presupuesto)


@presupuesto_bp.route("/api/presupuesto/categoria/asignar", methods=["POST"])
@login_required
def api_asignar_categoria_balde():
    """Reasigna UNA categoría (texto libre, ver movimientos.categoria) de
    viendo_id() a un balde -- así "podés cambiar esa asignación sin tocar
    código" (criterio de aceptación del documento)."""
    categoria = (request.form.get("categoria") or "").strip()
    balde = (request.form.get("balde") or "").strip()

    if not categoria:
        return jsonify(ok=False, error="Falta la categoría."), 400

    with db.conexion() as conn:
        try:
            db.asignar_categoria_balde(conn, usuario_id=viendo_id(), categoria=categoria, balde=balde)
        except ValueError as e:
            return jsonify(ok=False, error=str(e)), 400
        categoria_balde = db.obtener_mapeo_categorias(conn, usuario_id=viendo_id())

    return jsonify(ok=True, categoria_balde=categoria_balde)


# ============================================================================
# Metas de ahorro
# ============================================================================

def _parsear_monto_objetivo(valor_raw: str | None) -> tuple[float | None, str | None]:
    """Mismo criterio que _parsear_cupo() de tarjetas: (None, None) si
    viene vacío (válido en edición parcial; crear exige un valor,
    chequeado aparte), (None, mensaje) si viene pero no es válido."""
    if valor_raw is None or valor_raw.strip() == "":
        return None, None
    try:
        monto = float(valor_raw)
    except ValueError:
        return None, "El monto objetivo no es un número válido."
    if monto <= 0:
        return None, "El monto objetivo tiene que ser mayor a 0."
    return monto, None


@presupuesto_bp.route("/api/metas-ahorro", methods=["GET"])
@login_required
def api_listar_metas_ahorro():
    with db.conexion() as conn:
        metas = db.obtener_metas_ahorro(conn, usuario_id=viendo_id())
    return jsonify(ok=True, metas=metas)


@presupuesto_bp.route("/api/metas-ahorro/crear", methods=["POST"])
@login_required
def api_crear_meta_ahorro():
    nombre = (request.form.get("nombre") or "").strip()
    fecha_objetivo = (request.form.get("fecha_objetivo") or "").strip() or None

    if not nombre:
        return jsonify(ok=False, error="Falta el nombre de la meta."), 400

    monto_objetivo, error = _parsear_monto_objetivo(request.form.get("monto_objetivo"))
    if error:
        return jsonify(ok=False, error=error), 400
    if monto_objetivo is None:  # obligatorio al crear (a diferencia de la edición)
        return jsonify(ok=False, error="Falta el monto objetivo (tiene que ser mayor a 0)."), 400

    with db.conexion() as conn:
        try:
            meta_id = db.crear_meta_ahorro(
                conn, usuario_id=viendo_id(), nombre=nombre,
                monto_objetivo=monto_objetivo, fecha_objetivo=fecha_objetivo,
            )
        except ValueError as e:
            return jsonify(ok=False, error=str(e)), 400

    return jsonify(ok=True, id=meta_id)


@presupuesto_bp.route("/api/metas-ahorro/<int:meta_id>/editar", methods=["POST"])
@login_required
def api_editar_meta_ahorro(meta_id):
    """Edición parcial: solo se tocan los campos presentes en el form
    (mismo criterio que api_editar_tarjeta()). Un string vacío en
    fecha_objetivo SÍ es una instrucción explícita de "quitarla" -- para
    no tocarla, simplemente no se manda esa clave en el form."""
    nombre = request.form.get("nombre")
    fecha_objetivo = request.form.get("fecha_objetivo")

    monto_objetivo, error = _parsear_monto_objetivo(request.form.get("monto_objetivo"))
    if error:
        return jsonify(ok=False, error=error), 400

    try:
        with db.conexion() as conn:
            ok = db.actualizar_meta_ahorro(
                conn, usuario_id=viendo_id(), meta_id=meta_id,
                nombre=nombre, monto_objetivo=monto_objetivo, fecha_objetivo=fecha_objetivo,
            )
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400

    if not ok:
        return jsonify(ok=False, error="Esa meta no existe."), 404
    return jsonify(ok=True)


@presupuesto_bp.route("/api/metas-ahorro/<int:meta_id>/archivar", methods=["POST"])
@login_required
def api_archivar_meta_ahorro(meta_id):
    with db.conexion() as conn:
        ok = db.archivar_meta_ahorro(conn, usuario_id=viendo_id(), meta_id=meta_id)
    if not ok:
        return jsonify(ok=False, error="Esa meta no existe."), 404
    return jsonify(ok=True)


@presupuesto_bp.route("/api/metas-ahorro/<int:meta_id>/borrar", methods=["POST"])
@login_required
def api_borrar_meta_ahorro(meta_id):
    """Nota de consistencia de API: "no existe / es ajena" da 404, igual
    que editar/archivar -- el 400 queda reservado para la única falla que
    es realmente "de negocio" acá (la meta existe y es tuya, pero tiene
    aportes asociados y por eso no se puede borrar definitivamente).
    Mismo criterio exacto que api_borrar_tarjeta()."""
    with db.conexion() as conn:
        if db.obtener_meta_ahorro(conn, usuario_id=viendo_id(), meta_id=meta_id) is None:
            return jsonify(ok=False, error="Esa meta no existe."), 404
        ok, error = db.borrar_meta_ahorro(conn, usuario_id=viendo_id(), meta_id=meta_id)
    if not ok:
        return jsonify(ok=False, error=error), 400
    return jsonify(ok=True)
