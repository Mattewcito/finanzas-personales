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
import time
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

# --- Rate limiting básico de /login (hallazgo H2 de la revisión de
# seguridad 2026-09-11) ---
# Limitador simple EN MEMORIA (dict), sin agregar dependencias nuevas
# (nada de flask-limiter -- el proyecto prefiere herramientas mínimas para
# una app familiar de bajo tráfico). Limitaciones conocidas y aceptadas:
#   - Se resetea si el proceso reinicia (perder el historial de intentos
#     fallidos al reiniciar el contenedor es aceptable acá).
#   - NO se comparte entre workers de gunicorn si hay más de uno corriendo
#     -- cada worker tiene su propio dict en memoria, así que el límite
#     real termina siendo (límite configurado x cantidad de workers). Para
#     esta app, con pocos workers y tráfico familiar, es una mitigación
#     razonable, no una garantía dura contra fuerza bruta distribuida.
_INTENTOS_FALLIDOS: dict[str, list[float]] = {}
_LOGIN_MAX_INTENTOS = 5
_LOGIN_VENTANA_SEG = 5 * 60   # 5 minutos
_LOGIN_BLOQUEO_SEG = 5 * 60   # 5 minutos


def _registrar_intento_fallido(clave: str) -> None:
    ahora = time.time()
    intentos = _INTENTOS_FALLIDOS.setdefault(clave, [])
    intentos.append(ahora)
    # Poda oportunista: solo conserva intentos dentro de la ventana +
    # bloqueo, para que el dict no crezca sin límite con el tiempo.
    limite = ahora - max(_LOGIN_VENTANA_SEG, _LOGIN_BLOQUEO_SEG)
    _INTENTOS_FALLIDOS[clave] = [t for t in intentos if t >= limite]


def _limpiar_intentos(clave: str) -> None:
    _INTENTOS_FALLIDOS.pop(clave, None)


def _bloqueado(clave: str) -> bool:
    ahora = time.time()
    intentos = _INTENTOS_FALLIDOS.get(clave, [])
    recientes = [t for t in intentos if t >= ahora - _LOGIN_VENTANA_SEG]
    if len(recientes) < _LOGIN_MAX_INTENTOS:
        return False
    # Bloqueado mientras el intento más reciente siga dentro de la
    # ventana de bloqueo (bloqueo "deslizante": cada intento nuevo
    # mientras se está bloqueado empuja el bloqueo hacia adelante).
    return ahora - recientes[-1] < _LOGIN_BLOQUEO_SEG


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


def requiere_vista_visible(vista: str, *, por_viendo: bool = False):
    """Decorador: bloquea una ruta que un admin ocultó -- no solo el
    ítem del menú, la ruta en sí, para que ocultar algo sea una
    restricción real (nadie accede hasta que se reactive), sin
    excepción de rol: un admin queda bloqueado igual que cualquiera si
    la vista está oculta para la cuenta que corresponda. Esto es seguro
    porque /admin/vistas (el panel que revierte cualquier restricción)
    NUNCA lleva este decorador -- siempre hay una puerta de salida.

    `por_viendo=False` (default): chequea la vista oculta de
    session["usuario_id"] (quien inició sesión) -- para funciones de
    autoservicio como Correo automático, ligadas a la identidad de
    sesión, no a la cuenta que se esté viendo (así un admin puede seguir
    configurando el correo de otro usuario vía viendo_id() aunque ese
    usuario tenga esa sección oculta para sí mismo).
    `por_viendo=True`: chequea la de viendo_id() -- para contenido del
    dashboard, donde lo que importa es DE QUÉ CUENTA se muestran datos,
    sin importar quién inició sesión."""
    def decorador(f):
        @wraps(f)
        def decorado(*args, **kwargs):
            id_a_chequear = viendo_id() if por_viendo else session.get("usuario_id")
            with db.conexion() as conn:
                ocultas = db.vistas_ocultas_de(conn, id_a_chequear)
            if vista in ocultas:
                # /api/... son llamadas fetch (esperan JSON, nunca una
                # redirección) -- el resto son páginas de verdad.
                if request.path.startswith("/api/"):
                    return jsonify(ok=False, error="Esta función está desactivada para esta cuenta."), 403
                return redirect(url_for("usuarios.mi_perfil"))
            return f(*args, **kwargs)
        return decorado
    return decorador


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
    vistas_ocultas = set()          # de session["usuario_id"] -- ítems de autoservicio (Correo automático)
    vistas_ocultas_viendo = set()   # de viendo_id() -- contenido del dashboard (de qué cuenta son los datos)
    if session.get("usuario_id"):
        with db.conexion() as conn:
            vistas_ocultas = db.vistas_ocultas_de(conn, session["usuario_id"])
            vistas_ocultas_viendo = db.vistas_ocultas_de(conn, viendo_id())
    if session.get("rol") == "admin":
        with db.conexion() as conn:
            usuarios_disponibles = db.listar_usuarios(conn)
            # La cuenta del propio admin queda SIEMPRE primera en la
            # lista (anclada), sin importar el orden de creación --
            # es la única forma de volver a la cuenta propia rápido
            # cuando la lista crece o se está filtrando por búsqueda.
            propio_id = session.get("usuario_id")
            usuarios_disponibles.sort(key=lambda u: u["id"] != propio_id)
            if viendo_id() != propio_id:
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
        "vistas_ocultas": vistas_ocultas,
        "vistas_ocultas_viendo": vistas_ocultas_viendo,
    }


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    ip = request.remote_addr or "desconocida"
    clave_ip = f"ip:{ip}"
    clave_user = f"user:{username.lower()}" if username else None

    if _bloqueado(clave_ip) or (clave_user and _bloqueado(clave_user)):
        return render_template(
            "login.html",
            error="Demasiados intentos fallidos. Esperá unos minutos e intentá de nuevo.",
        ), 429

    with db.conexion() as conn:
        db.crear_esquema(conn)
        cuenta = db.verificar_login(conn, username, password)

    if not cuenta:
        _registrar_intento_fallido(clave_ip)
        if clave_user:
            _registrar_intento_fallido(clave_user)
        return render_template("login.html", error="Usuario o contraseña incorrectos.")

    _limpiar_intentos(clave_ip)
    if clave_user:
        _limpiar_intentos(clave_user)

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
