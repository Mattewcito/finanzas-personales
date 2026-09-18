"""
routes/pwa.py
=============
Blueprint de la PWA (2026-09-18, ver requisitos/2026-09-18_paridad-lukas.md,
Fase 1): lo que el navegador necesita para poder instalar la app en la
pantalla de inicio del celular.

Por qué estas dos rutas no son simples archivos de /static/:

- /sw.js TIENE que servirse desde la raíz. El alcance de un service worker
  es la carpeta desde donde se sirve: desde /static/pwa/sw.js solo podría
  controlar /static/pwa/*, no la app. Además va con `Cache-Control:
  no-cache`, para que el navegador revise en cada visita si hay una versión
  nueva del service worker -- si no, un sw.js viejo podría quedar pegado
  en los celulares durante horas.
- /manifest.webmanifest podría vivir en /static/, pero servirlo con el
  mimetype correcto (`application/manifest+json`) evita advertencias de
  Chrome y deja las dos piezas de la PWA en el mismo lugar.

Las dos son PÚBLICAS a propósito (sin @login_required): el navegador las
pide antes de que haya sesión, incluso desde la pantalla de login, y no
contienen ningún dato de ninguna cuenta.
"""
from pathlib import Path

from flask import Blueprint, send_from_directory

pwa_bp = Blueprint("pwa", __name__)

PWA_DIR = Path(__file__).resolve().parent.parent / "static" / "pwa"


@pwa_bp.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(PWA_DIR, "manifest.webmanifest",
                               mimetype="application/manifest+json")


@pwa_bp.route("/sw.js")
def service_worker():
    resp = send_from_directory(PWA_DIR, "sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp
