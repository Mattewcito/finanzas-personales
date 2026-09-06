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
  /health                                  -> este archivo (sin login, la usa el pipeline de despliegue)
"""

import os
import sys
import secrets
import threading
import webbrowser

from flask import Flask, jsonify

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import db_finanzas as db
from auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.usuarios import usuarios_bp
from routes.correo import correo_bp

app = Flask(__name__)

# Clave de sesión: si no existe se genera una vez y se guarda en data/
# (fuera de git). Sin esto, Flask no puede firmar las cookies de sesión
# de forma segura.
_SECRET_KEY_PATH = db.DATA_DIR / "secret_key.txt"
if not _SECRET_KEY_PATH.exists():
    _SECRET_KEY_PATH.write_text(secrets.token_hex(32), encoding="utf-8")
app.secret_key = _SECRET_KEY_PATH.read_text(encoding="utf-8").strip()

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


@app.route("/health")
def health():
    """Sin login a propósito: la usa el pipeline de despliegue para
    confirmar que el contenedor arrancó bien antes de darlo por bueno."""
    return jsonify(ok=True), 200


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5001))

    if not os.environ.get("RUNNING_IN_DOCKER"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    app.run(host=host, port=port, debug=False)
