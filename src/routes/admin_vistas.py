"""
routes/admin_vistas.py
========================
Panel de administración (solo admin), en el menú como "Ocultar vistas",
para decidir qué secciones del dashboard/menú puede ver cada usuario --
ej. Mathewcito puede ocultarle "Correo automático" a Emanuel, o a sí
mismo, y volver a mostrarlo cuando quiera. Ver
db_finanzas.py::VISTAS_DISPONIBLES para el catálogo completo de vistas
configurables (Dashboard, Tu perfil financiero, Insights automáticos,
Tarjetas y deudas, Análisis visual, Movimientos, Correo automático) --
se suman ahí a futuro.

El bloqueo es real y sin excepción de rol (ver
auth.py::requiere_vista_visible()): si una vista queda oculta, NADIE
accede -- ni siquiera un admin -- hasta que se reactive. Según la
vista, se chequea contra la cuenta que se esté VIENDO (Dashboard/Tu
perfil financiero/Insights/Tarjetas y deudas/Análisis visual/
Movimientos -- de qué cuenta son los datos que se muestran) o contra
quien inició sesión (Correo automático --
autoservicio ligado a la identidad, no a la cuenta que un admin esté
administrando). Esta página en sí, y sus endpoints, están exentos de
cualquier restricción: son el panel de control, nunca puede quedar
bloqueado -- es la única puerta de salida garantizada de cualquier
restricción que alguien se haya puesto a sí mismo por error.
"""
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for

import db_finanzas as db
from auth import login_required

admin_vistas_bp = Blueprint("admin_vistas", __name__)


def _solo_admin():
    return session.get("rol") == "admin"


@admin_vistas_bp.route("/admin/vistas")
@login_required
def admin_vistas_page():
    if not _solo_admin():
        return redirect(url_for("dashboard.home"))
    with db.conexion() as conn:
        usuarios = db.listar_usuarios(conn)
        ocultas_por_usuario = db.vistas_ocultas_todos(conn)
    return render_template(
        "admin_vistas.html", activo="admin_vistas",
        usuarios=usuarios, vistas=db.VISTAS_DISPONIBLES, ocultas_por_usuario=ocultas_por_usuario,
    )


@admin_vistas_bp.route("/api/admin/vistas/toggle", methods=["POST"])
@login_required
def api_admin_vistas_toggle():
    if not _solo_admin():
        return jsonify(ok=False, error="Solo un administrador puede cambiar esto."), 403

    usuario_id = request.form.get("usuario_id", type=int)
    vista = request.form.get("vista", "").strip()
    visible = request.form.get("visible") in ("1", "true", "on")

    vistas_validas = {v["id"] for v in db.VISTAS_DISPONIBLES}
    if vista not in vistas_validas:
        return jsonify(ok=False, error=f"Vista desconocida: {vista!r}"), 400

    with db.conexion() as conn:
        if not db.obtener_usuario(conn, usuario_id):
            return jsonify(ok=False, error="Ese usuario no existe."), 400
        if visible:
            db.mostrar_vista(conn, usuario_id, vista)
        else:
            db.ocultar_vista(conn, usuario_id, vista)

    return jsonify(ok=True)
