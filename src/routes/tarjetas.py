"""
routes/tarjetas.py
====================
CRUD de tarjetas de crédito propias de la cuenta que se esté VIENDO
(`viendo_id()`, ver auth.py) -- alta, edición, archivado (soft delete) y
borrado definitivo (solo si nunca tuvo movimientos asociados). Ver
requisitos/2026-09-07_tarjetas-credito-cupo.md para el diseño completo.

Aislamiento: SIEMPRE viendo_id(), NUNCA session["usuario_id"] a secas --
las tarjetas son CONTENIDO/datos de la cuenta que se esté viendo (igual
que movimientos, perfil financiero, el propio Dashboard), no
autoservicio ligado a la identidad de quien inició sesión (a diferencia
de "Correo automático", ver auth.py::requiere_vista_visible). Un admin
viendo el perfil de otro usuario gestiona las tarjetas de ESA cuenta,
igual que hoy puede registrarle un movimiento a mano (ver
routes/dashboard.py::api_registrar_movimiento) o cargarle un extracto.

El cálculo de deuda/cupo disponible por tarjeta (para el Dashboard) NO
vive acá -- lo arma db.obtener_tarjetas_con_deuda() y lo expone
routes/dashboard.py::api_dashboard_data() bajo la clave "tarjetas", para
no duplicar esa consulta en dos rutas distintas.

Endpoints (todos requieren sesión iniciada; mismo patrón "todo POST,
acción en la URL" que ya usa routes/correo.py -- este proyecto no usa
verbos HTTP DELETE/PUT en ningún otro blueprint):
  GET  /api/tarjetas                     -> todas (activas y archivadas) de viendo_id()
  POST /api/tarjetas/crear                -> alta
  POST /api/tarjetas/<id>/editar          -> edición parcial
  POST /api/tarjetas/<id>/archivar        -> soft delete (activa=0)
  POST /api/tarjetas/<id>/borrar          -> borrado definitivo (falla si tiene movimientos)
"""
from flask import Blueprint, jsonify, request

import db_finanzas as db
from auth import login_required, viendo_id

tarjetas_bp = Blueprint("tarjetas", __name__)


def _parsear_cupo(valor_raw: str | None) -> tuple[float | None, str | None]:
    """Devuelve (cupo, None) si es válido, o (None, mensaje_de_error) si
    no. `valor_raw=None` o vacío devuelve (None, None) -- "no se mandó
    este campo" (válido en edición parcial, inválido en alta -- cada
    endpoint decide)."""
    if valor_raw is None or valor_raw.strip() == "":
        return None, None
    try:
        cupo = float(valor_raw)
    except ValueError:
        return None, "El cupo total no es un número válido."
    if cupo <= 0:
        return None, "El cupo total tiene que ser mayor a 0."
    return cupo, None


def _validar_ultimos4(valor: str | None) -> str | None:
    """None si es válido (vacío/None es válido -- es opcional), o un
    mensaje de error si viene algo que no son 4 dígitos."""
    v = (valor or "").strip()
    if v and (not v.isdigit() or len(v) != 4):
        return "Los últimos 4 dígitos tienen que ser 4 números."
    return None


@tarjetas_bp.route("/api/tarjetas", methods=["GET"])
@login_required
def api_listar_tarjetas():
    with db.conexion() as conn:
        tarjetas = db.obtener_tarjetas(conn, usuario_id=viendo_id())
    return jsonify(ok=True, tarjetas=tarjetas)


@tarjetas_bp.route("/api/tarjetas/crear", methods=["POST"])
@login_required
def api_crear_tarjeta():
    nombre = (request.form.get("nombre") or "").strip()
    entidad = (request.form.get("entidad") or "").strip() or None
    ultimos4 = (request.form.get("ultimos4") or "").strip() or None

    if not nombre:
        return jsonify(ok=False, error="Falta el nombre de la tarjeta."), 400

    cupo_total, error = _parsear_cupo(request.form.get("cupo_total"))
    if error:
        return jsonify(ok=False, error=error), 400
    if cupo_total is None:  # cupo_total es OBLIGATORIO al crear (a diferencia de la edición)
        return jsonify(ok=False, error="Falta el cupo total (tiene que ser mayor a 0)."), 400

    error = _validar_ultimos4(ultimos4)
    if error:
        return jsonify(ok=False, error=error), 400

    with db.conexion() as conn:
        try:
            tarjeta_id = db.crear_tarjeta(
                conn, usuario_id=viendo_id(), nombre=nombre,
                cupo_total=cupo_total, entidad=entidad, ultimos4=ultimos4,
            )
        except ValueError as e:
            return jsonify(ok=False, error=str(e)), 400

    return jsonify(ok=True, id=tarjeta_id)


@tarjetas_bp.route("/api/tarjetas/<int:tarjeta_id>/editar", methods=["POST"])
@login_required
def api_editar_tarjeta(tarjeta_id):
    """Edición parcial: solo se tocan los campos presentes en el form
    (mismo criterio que db.actualizar_usuario()). Un string vacío en
    entidad/ultimos4 SÍ es una instrucción explícita de "borrar este
    campo opcional" -- para no tocar un campo, simplemente no se manda
    esa clave en el form."""
    nombre = request.form.get("nombre")
    entidad = request.form.get("entidad")
    ultimos4 = request.form.get("ultimos4")

    cupo_total, error = _parsear_cupo(request.form.get("cupo_total"))
    if error:
        return jsonify(ok=False, error=error), 400

    if ultimos4 is not None:
        error = _validar_ultimos4(ultimos4)
        if error:
            return jsonify(ok=False, error=error), 400

    try:
        with db.conexion() as conn:
            ok = db.actualizar_tarjeta(
                conn, usuario_id=viendo_id(), tarjeta_id=tarjeta_id,
                nombre=nombre, entidad=entidad, cupo_total=cupo_total, ultimos4=ultimos4,
            )
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400

    if not ok:
        return jsonify(ok=False, error="Esa tarjeta no existe."), 404
    return jsonify(ok=True)


@tarjetas_bp.route("/api/tarjetas/<int:tarjeta_id>/archivar", methods=["POST"])
@login_required
def api_archivar_tarjeta(tarjeta_id):
    with db.conexion() as conn:
        ok = db.archivar_tarjeta(conn, usuario_id=viendo_id(), tarjeta_id=tarjeta_id)
    if not ok:
        return jsonify(ok=False, error="Esa tarjeta no existe."), 404
    return jsonify(ok=True)


@tarjetas_bp.route("/api/tarjetas/<int:tarjeta_id>/borrar", methods=["POST"])
@login_required
def api_borrar_tarjeta(tarjeta_id):
    """Nota de consistencia de API: "no existe / es ajena" da 404, igual
    que editar/archivar -- el 400 queda reservado para la única falla que
    es realmente "de negocio" acá (la tarjeta existe y es tuya, pero
    tiene movimientos asociados y por eso no se puede borrar
    definitivamente)."""
    with db.conexion() as conn:
        if db.obtener_tarjeta(conn, usuario_id=viendo_id(), tarjeta_id=tarjeta_id) is None:
            return jsonify(ok=False, error="Esa tarjeta no existe."), 404
        ok, error = db.borrar_tarjeta(conn, usuario_id=viendo_id(), tarjeta_id=tarjeta_id)
    if not ok:
        return jsonify(ok=False, error=error), 400
    return jsonify(ok=True)
