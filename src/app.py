"""
app.py
========
Raíz de la app Flask: crea el objeto Flask, la clave de sesión, y
registra los blueprints que agrupan las rutas por área (patrón estándar
de Flask para no tener todas las rutas de un proyecto en un solo
archivo gigante):

  - auth.py             -> login, logout, cambiar de perfil (admin)
  - routes/dashboard.py -> ver el dashboard, registrar movimientos, cargar extractos
  - routes/usuarios.py  -> alta/edición de cuentas, editar el propio perfil
  - routes/correo.py    -> configurar la lectura automática de correo (Fase 1) de la propia cuenta
  - routes/admin_vistas.py -> panel admin: qué secciones del menú puede ver cada usuario
  - routes/tarjetas.py  -> CRUD de tarjetas de crédito propias (cupo/deuda por tarjeta)
  - routes/presupuesto.py -> presupuesto por 3 baldes, mapeo categoría->balde, metas de ahorro

Uso:
    py app.py
Abre solo en el navegador: http://127.0.0.1:5001

Variables de entorno opcionales (para correr dentro de Docker):
  HOST                -> por defecto 127.0.0.1 (solo esta PC). En Docker se
                          usa 0.0.0.0 para que el contenedor sea alcanzable
                          desde afuera vía el puerto mapeado.
  PORT                -> por defecto 5001.
  RUNNING_IN_DOCKER=1  -> evita intentar abrir un navegador (no existe
                          dentro del contenedor).

Usuarios: cada movimiento pertenece a un usuario_id. El rol 'admin' puede
"cambiar de perfil" (ver los datos de cualquier cuenta); el rol 'usuario'
siempre ve solo los suyos. Ver crear_usuario.py para dar de alta cuentas.

Rutas (por blueprint, ver el archivo de cada uno para el detalle):
  /login, /logout, /cambiar-vista          -> auth.py
  /, /vista/dashboard, /registrar,
  /cargar-extractos, /plantilla-excel      -> routes/dashboard.py
  /crear-usuario, /editar-usuario, /mi-perfil -> routes/usuarios.py
  /configurar-correo                       -> routes/correo.py
  /admin/vistas                            -> routes/admin_vistas.py
  /api/tarjetas, /api/tarjetas/crear,
  /api/tarjetas/<id>/editar|archivar|borrar -> routes/tarjetas.py
  /api/presupuesto, /api/presupuesto/guardar,
  /api/presupuesto/categoria/asignar,
  /api/metas-ahorro, /api/metas-ahorro/crear,
  /api/metas-ahorro/<id>/editar|archivar|borrar -> routes/presupuesto.py
  /health                                  -> este archivo (sin login, la usa el pipeline de despliegue)
"""

import os
import sys
import secrets
import threading
import webbrowser

from flask import Flask, jsonify, request, abort
from urllib.parse import urlparse

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import db_finanzas as db
from auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.usuarios import usuarios_bp
from routes.correo import correo_bp
from routes.admin_vistas import admin_vistas_bp
from routes.tarjetas import tarjetas_bp
from routes.presupuesto import presupuesto_bp

app = Flask(__name__)

# Clave de sesión: si no existe se genera una vez y se guarda en data/
# (fuera de git). Sin esto, Flask no puede firmar las cookies de sesión
# de forma segura.
_SECRET_KEY_PATH = db.DATA_DIR / "secret_key.txt"
if not _SECRET_KEY_PATH.exists():
    _SECRET_KEY_PATH.write_text(secrets.token_hex(32), encoding="utf-8")
app.secret_key = _SECRET_KEY_PATH.read_text(encoding="utf-8").strip()

# --- Endurecimiento de la cookie de sesión (hallazgo M2 de la revisión de
# seguridad 2026-09-11) ---
# HTTPONLY: ya era el default de Flask, se fija explícito para que no
# dependa de que nadie lo cambie sin darse cuenta.
# SAMESITE=Lax: mitiga (parcialmente) CSRF vía formularios cross-site simples
# sin romper la navegación normal dentro del propio dominio (ej. el iframe
# same-origin del dashboard).
# SECURE se deja SIN activar a propósito: la app corre sobre HTTP plano en
# la LAN local (puertos 5001/5002, sin TLS/proxy delante). Si se activara
# Secure=True, el navegador dejaría de enviar la cookie de sesión por HTTP
# plano y el login quedaría roto para todos. Si algún día se sirve detrás
# de HTTPS (proxy/reverse-proxy con TLS), activar esto también.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # SESSION_COOKIE_SECURE=True,  # NO activar: app sirve por HTTP plano en LAN.
)

# --- Límite de tamaño de request/upload (hallazgo M4) ---
# 20 MB de sobra para un extracto real (Excel/PDF de un banco); evita que
# una subida gigante agote memoria/disco del contenedor (gunicorn corre con
# pocos workers, ver Dockerfile) y cause una denegación de servicio.
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

# Asegura el esquema al arrancar el proceso (no solo al loguearse, como
# hacía antes solo auth.py): una sesión ya iniciada sobrevive a un
# reinicio del contenedor, así que si una versión nueva agrega una tabla
# (ej. correo_config) y nadie vuelve a loguearse, esas rutas reventarían
# con "no such table" contra una BD real que ya existía de antes. Es
# no-op si el esquema ya estaba al día.
with db.conexion() as _conn:
    db.crear_esquema(_conn)

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(usuarios_bp)
app.register_blueprint(correo_bp)
app.register_blueprint(admin_vistas_bp)
app.register_blueprint(tarjetas_bp)
app.register_blueprint(presupuesto_bp)


@app.route("/health")
def health():
    """Sin login a propósito: la usa el pipeline de despliegue para
    confirmar que el contenedor arrancó bien antes de darlo por bueno."""
    return jsonify(ok=True), 200


# --- Mitigación de CSRF sin tokens por formulario (hallazgo H1) ---
# El proyecto tiene muchos formularios en muchos templates; agregar un
# token CSRF a cada uno es una tarea grande. En su lugar, esta es una
# defensa en profundidad (NO una solución completa) basada en verificar
# el origen de la petición: si el navegador manda Origin o Referer, su
# host tiene que coincidir con el host de la app. Si NINGUNO de los dos
# headers está presente, se deja pasar (algunos clientes legítimos no los
# mandan, y bloquear ahí generaría falsos positivos). /health queda
# excluido porque lo usa el pipeline de despliegue sin esos headers y no
# cambia estado.
_METODOS_CON_ESTADO = {"POST", "PUT", "DELETE", "PATCH"}


def _host_de(url: str) -> str | None:
    try:
        return urlparse(url).netloc
    except ValueError:
        return None


@app.before_request
def verificar_origen():
    if request.method not in _METODOS_CON_ESTADO:
        return None
    if request.path == "/health":
        return None

    origen = request.headers.get("Origin") or request.headers.get("Referer")
    if not origen:
        # Ningún cliente moderno navegando "de verdad" debería omitir los
        # dos, pero herramientas/clientes legítimos (curl, scripts internos,
        # el propio test client de Flask) sí pueden hacerlo -- se deja
        # pasar en vez de bloquear con falsos positivos.
        return None

    host_origen = _host_de(origen)
    if host_origen and host_origen != request.host:
        abort(403)
    return None


# --- Cabeceras de seguridad HTTP (hallazgo H3) ---
@app.after_request
def agregar_cabeceras_seguridad(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    # SAMEORIGIN (no DENY): el dashboard se embebe a propósito en un
    # <iframe> same-origin dentro de base.html (/vista/dashboard) -- DENY
    # rompería eso.
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "same-origin"
    # CSP permisiva a propósito: base.html/login.html/dashboard_finanzas.html
    # usan bastante <script>/<style> inline sin nonce (revisado antes de
    # definir esto), así que una CSP estricta con script-src/style-src sin
    # 'unsafe-inline' rompería la app. Se deja documentado como deuda
    # técnica aceptada por ahora. Lo que sí se fija sin concesiones:
    # frame-ancestors 'self' (refuerza X-Frame-Options con la directiva
    # moderna) y object-src 'none' (bloquea <object>/<embed>, sin uso
    # legítimo conocido en la app).
    # style-src/font-src incluyen fonts.googleapis.com/fonts.gstatic.com:
    # dashboard_finanzas.html carga la tipografía Inter desde Google Fonts
    # (ver <link> en su <head>) -- sin esto, el CSP rompería esa carga.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "object-src 'none'; "
        "frame-ancestors 'self'"
    )
    return response


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5001))

    if not os.environ.get("RUNNING_IN_DOCKER"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    app.run(host=host, port=port, debug=False)
