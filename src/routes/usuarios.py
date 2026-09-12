"""
routes/usuarios.py
====================
Alta y edición de cuentas (solo admin) y edición del propio perfil.
"""
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for

import db_finanzas as db
from auth import login_required

usuarios_bp = Blueprint("usuarios", __name__)

# Mínimo de longitud de contraseña (hallazgo M1 de la revisión de seguridad
# 2026-09-11: 4 caracteres era trivialmente adivinable, sobre todo
# combinado con la falta de rate limiting que ya se agregó en /login).
PASSWORD_MIN_LEN = 8


@usuarios_bp.route("/crear-usuario")
@login_required
def crear_usuario_page():
    if session.get("rol") != "admin":
        return redirect(url_for("dashboard.home"))
    with db.conexion() as conn:
        usuarios = db.listar_usuarios(conn)
    return render_template("crear_usuario.html", activo="crear_usuario", usuarios=usuarios)


@usuarios_bp.route("/api/crear-usuario", methods=["POST"])
@login_required
def api_crear_usuario():
    if session.get("rol") != "admin":
        return jsonify(ok=False, error="Solo un administrador puede crear usuarios."), 403

    username = request.form.get("username", "").strip()
    nombre = request.form.get("nombre", "").strip()
    password = request.form.get("password", "")
    rol = request.form.get("rol", "usuario").strip()

    if not username or not nombre or not password:
        return jsonify(ok=False, error="Faltan campos."), 400
    if rol not in ("admin", "usuario"):
        return jsonify(ok=False, error="Rol inválido."), 400
    if len(password) < PASSWORD_MIN_LEN:
        return jsonify(ok=False, error=f"La contraseña debe tener al menos {PASSWORD_MIN_LEN} caracteres."), 400

    with db.conexion() as conn:
        db.crear_esquema(conn)
        nuevo_id = db.crear_usuario(conn, username, password, rol, nombre)

    # No hace falta "generar" nada -- /api/dashboard-data va a devolver
    # listas vacías para este usuario la primera vez que entre.
    return jsonify(ok=True, id=nuevo_id)


@usuarios_bp.route("/mi-perfil")
@login_required
def mi_perfil():
    """Edita SIEMPRE la cuenta con la que se inició sesión (no la que se
    esté 'viendo' si sos admin) -- para no confundir "mi perfil" con la
    cuenta ajena que un admin puede estar mirando en ese momento."""
    with db.conexion() as conn:
        cuenta = db.obtener_usuario(conn, session["usuario_id"])
    return render_template("mi_perfil.html", activo="mi_perfil", cuenta=cuenta)


@usuarios_bp.route("/api/actualizar-perfil", methods=["POST"])
@login_required
def api_actualizar_perfil():
    username = request.form.get("username", "").strip()
    nombre = request.form.get("nombre", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not nombre:
        return jsonify(ok=False, error="Faltan campos."), 400
    if password and len(password) < PASSWORD_MIN_LEN:
        return jsonify(ok=False, error=f"La contraseña debe tener al menos {PASSWORD_MIN_LEN} caracteres."), 400

    with db.conexion() as conn:
        db.actualizar_usuario(conn, session["usuario_id"], username=username,
                               nombre_mostrado=nombre, password=password or None)

    session["nombre"] = nombre  # para que el menú lo refleje ya, sin tener que volver a loguearse

    return jsonify(ok=True)


@usuarios_bp.route("/editar-usuario/<int:usuario_id>")
@login_required
def editar_usuario_page(usuario_id):
    if session.get("rol") != "admin":
        return redirect(url_for("dashboard.home"))
    with db.conexion() as conn:
        cuenta = db.obtener_usuario(conn, usuario_id)
    if not cuenta:
        return redirect(url_for("usuarios.crear_usuario_page"))
    return render_template("editar_usuario.html", activo="crear_usuario", cuenta=cuenta)


@usuarios_bp.route("/api/editar-usuario/<int:usuario_id>", methods=["POST"])
@login_required
def api_editar_usuario(usuario_id):
    if session.get("rol") != "admin":
        return jsonify(ok=False, error="Solo un administrador puede editar otras cuentas."), 403

    username = request.form.get("username", "").strip()
    nombre = request.form.get("nombre", "").strip()
    password = request.form.get("password", "").strip()
    rol = request.form.get("rol", "").strip()

    if not username or not nombre or rol not in ("admin", "usuario"):
        return jsonify(ok=False, error="Faltan campos o rol inválido."), 400
    if password and len(password) < PASSWORD_MIN_LEN:
        return jsonify(ok=False, error=f"La contraseña debe tener al menos {PASSWORD_MIN_LEN} caracteres."), 400

    with db.conexion() as conn:
        db.actualizar_usuario(conn, usuario_id, username=username, nombre_mostrado=nombre,
                               password=password or None, rol=rol)

    if usuario_id == session.get("usuario_id"):  # el admin se editó a sí mismo
        session["nombre"] = nombre
        session["rol"] = rol

    return jsonify(ok=True)
