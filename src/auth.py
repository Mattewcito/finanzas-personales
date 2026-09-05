"""
auth.py
========
Autenticación y "a quién se está viendo" (multiusuario). Vive separado
del resto de las rutas porque `login_required` y `viendo_id()` los
necesita CUALQUIER otro blueprint (dashboard, usuarios) -- ponerlos acá
evita un import circular entre esos dos.

Patrón de diseño: Flask Blueprints. `app.py` (la raíz de la app) solo
crea el objeto Flask y registra este blueprint junto con
`routes/dashboard.py` y `routes/usuarios.py` -- cada uno agrupa las
rutas de un área del producto en vez de tener las ~30 rutas del proyecto
en un único archivo de 480 líneas.
"""
import os
from functools import wraps

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for

import db_finanzas as db

# Etiqueta que se muestra en el menú ("Mathewcito · Local/Online"). Ya NO
# se puede inferir de "¿estoy en Docker?" porque dev y online corren los
# dos en contenedores -- cada docker-compose (override, específico de
# cada máquina) fija su propio MODO_LABEL. "Local" es el default para
# cuando se corre directo con "py app.py" sin Docker.
MODO = os.environ.get("MODO_LABEL", "Local")

auth_bp = Blueprint("auth", __name__)


def login_required(f):
    @wraps(f)
    def decorado(*args, **kwargs):
        if not session.get("usuario_id"):
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorado


def viendo_id() -> int:
    """El usuario_id cuyos datos hay que mostrar/afectar ahora mismo.
    Para rol 'usuario' es siempre el suyo. Para 'admin' puede ser el de
    cualquiera (ver /cambiar-vista) -- por defecto, el suyo propio."""
    return session.get("viendo_id", session.get("usuario_id"))


@auth_bp.app_context_processor
def inyectar_globales():
    usuarios_disponibles = []
    # Por defecto, "la cuenta que se está viendo" es la propia -- si sos
    # admin viendo el perfil de otro, esto pasa a ser el nombre de esa
    # otra cuenta (ver cargar_extractos.html / registrar.html: se usa
    # para que el admin confirme a quién le está cargando datos antes de
    # mandarlos, después de que una carga terminó en la cuenta
    # equivocada por tener seleccionado otro perfil sin darse cuenta).
    usuario_viendo_nombre = session.get("nombre")
    if session.get("rol") == "admin":
        with db.conexion() as conn:
            usuarios_disponibles = db.listar_usuarios(conn)
            if viendo_id() != session.get("usuario_id"):
                cuenta_vista = db.obtener_usuario(conn, viendo_id())
                if cuenta_vista:
                    usuario_viendo_nombre = cuenta_vista["nombre_mostrado"]
    return {
        "modo": MODO,
        "usuario_nombre": session.get("nombre"),
        "usuario_rol": session.get("rol"),
        "viendo_id": viendo_id(),
        "usuario_viendo_nombre": usuario_viendo_nombre,
        "usuarios_disponibles": usuarios_disponibles,
    }


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    with db.conexion() as conn:
        db.crear_esquema(conn)
        cuenta = db.verificar_login(conn, username, password)

    if not cuenta:
        return render_template("login.html", error="Usuario o contraseña incorrectos.")

    session.clear()
    session["usuario_id"] = cuenta["id"]
    session["rol"] = cuenta["rol"]
    session["nombre"] = cuenta["nombre_mostrado"]
    session["viendo_id"] = cuenta["id"]  # por defecto, cada quien ve lo suyo al entrar
    return redirect(request.args.get("next") or url_for("dashboard.home"))


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/cambiar-vista", methods=["POST"])
@login_required
def cambiar_vista():
    if session.get("rol") != "admin":
        return jsonify(ok=False, error="Solo el admin puede cambiar de perfil."), 403
    nuevo_id = request.form.get("usuario_id", type=int)
    with db.conexion() as conn:
        existe = db.obtener_usuario(conn, nuevo_id)
    if not existe:
        return jsonify(ok=False, error="Ese usuario no existe."), 400
    session["viendo_id"] = nuevo_id
    return redirect(url_for("dashboard.home"))
