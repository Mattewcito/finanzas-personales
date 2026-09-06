"""
routes/correo.py
====================
Configuración, desde la interfaz, de la lectura automática de correo
(Fase 1, ver src/leer_correo.py) para la cuenta del usuario QUE INICIÓ
SESIÓN -- igual que routes/usuarios.py::mi_perfil, esto usa siempre
session["usuario_id"], nunca viendo_id(): es información técnica de una
sola cuenta (el correo/contraseña de aplicación de esa persona), no algo
que un admin deba poder tocar mientras está "viendo" el perfil de otro
por error.

Endpoints:
  GET  /configurar-correo            -> página con el formulario + estado
  POST /api/correo/guardar           -> crea/actualiza la configuración
  POST /api/correo/probar            -> conecta por IMAP y devuelve una
                                         vista previa (NO inserta nada,
                                         ni siquiera hace falta haber
                                         guardado antes)
  POST /api/correo/sincronizar-ahora -> corre la sincronización YA MISMO
                                         con la config ya guardada (inserta)
  POST /api/correo/eliminar          -> borra la configuración (apaga la
                                         automatización de esta cuenta)

La contraseña de aplicación NUNCA se devuelve al navegador después de
guardarla -- ni en esta página ni en ningún endpoint. El formulario la
trata como "escribir para cambiar, dejar en blanco para mantener".
"""
import re

from flask import Blueprint, render_template, request, jsonify, session

import db_finanzas as db
import leer_correo as lc
from auth import login_required

correo_bp = Blueprint("correo", __name__)

_HORA_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _config_desde_formulario(existente: dict | None) -> tuple[dict | None, str | None]:
    """Arma el dict de config a partir de request.form, validando. Devuelve
    (config, None) si todo bien, o (None, mensaje_de_error) si no."""
    email = request.form.get("email", "").strip()
    app_password = request.form.get("app_password", "").strip()
    imap_host = request.form.get("imap_host", "").strip() or "imap.gmail.com"
    frecuencia_tipo = request.form.get("frecuencia_tipo", "intervalo").strip()
    frecuencia_hora = request.form.get("frecuencia_hora", "").strip() or None

    if not email or "@" not in email:
        return None, "El correo no es válido."
    if not app_password and not existente:
        return None, "Falta la contraseña de aplicación (obligatoria la primera vez)."

    try:
        imap_port = int(request.form.get("imap_port") or 993)
    except ValueError:
        return None, "El puerto IMAP debe ser un número."

    if frecuencia_tipo not in ("intervalo", "diario"):
        return None, "Frecuencia inválida."

    frecuencia_minutos = 30
    if frecuencia_tipo == "intervalo":
        try:
            frecuencia_minutos = int(request.form.get("frecuencia_minutos") or 30)
        except ValueError:
            return None, "Los minutos deben ser un número."
        if frecuencia_minutos < 5 or frecuencia_minutos > 1440:
            return None, "El intervalo debe ser entre 5 y 1440 minutos (24 horas)."
    else:
        if not frecuencia_hora or not _HORA_RE.match(frecuencia_hora):
            return None, "La hora diaria debe tener formato HH:MM (ej. 08:00)."

    activo = request.form.get("activo", "1") in ("1", "true", "on")

    return {
        "email": email,
        "app_password": app_password or None,  # None = no cambiar (ver db.guardar_correo_config)
        "imap_host": imap_host,
        "imap_port": imap_port,
        "frecuencia_tipo": frecuencia_tipo,
        "frecuencia_minutos": frecuencia_minutos,
        "frecuencia_hora": frecuencia_hora,
        "activo": activo,
    }, None


@correo_bp.route("/configurar-correo")
@login_required
def configurar_correo_page():
    with db.conexion() as conn:
        config = db.obtener_correo_config(conn, session["usuario_id"])
    return render_template("configurar_correo.html", activo="correo", config=config)


@correo_bp.route("/api/correo/guardar", methods=["POST"])
@login_required
def api_correo_guardar():
    usuario_id = session["usuario_id"]
    with db.conexion() as conn:
        existente = db.obtener_correo_config(conn, usuario_id)
        datos, error = _config_desde_formulario(existente)
        if error:
            return jsonify(ok=False, error=error), 400
        try:
            db.guardar_correo_config(
                conn, usuario_id,
                email=datos["email"], app_password=datos["app_password"],
                imap_host=datos["imap_host"], imap_port=datos["imap_port"],
                frecuencia_tipo=datos["frecuencia_tipo"], frecuencia_minutos=datos["frecuencia_minutos"],
                frecuencia_hora=datos["frecuencia_hora"], activo=datos["activo"],
            )
        except ValueError as e:
            return jsonify(ok=False, error=str(e)), 400

    return jsonify(ok=True)


@correo_bp.route("/api/correo/probar", methods=["POST"])
@login_required
def api_correo_probar():
    """Preview de conexión: NUNCA inserta nada en la BD, ni siquiera
    requiere haber guardado la configuración todavía -- prueba lo que
    esté escrito en el formulario en ese momento (si algún campo viene
    vacío, usa el ya guardado, para no obligar a re-escribir la
    contraseña solo para probar)."""
    usuario_id = session["usuario_id"]
    with db.conexion() as conn:
        existente = db.obtener_correo_config(conn, usuario_id)

    email = request.form.get("email", "").strip() or (existente["email"] if existente else "")
    app_password = request.form.get("app_password", "").strip() or (existente["app_password"] if existente else "")
    imap_host = request.form.get("imap_host", "").strip() or (existente["imap_host"] if existente else "imap.gmail.com")
    try:
        imap_port = int(request.form.get("imap_port") or (existente["imap_port"] if existente else 993))
        dias = int(request.form.get("dias") or 3)
    except ValueError:
        return jsonify(ok=False, error="Puerto o días inválidos."), 400

    if not email or not app_password:
        return jsonify(ok=False, error="Faltan correo o contraseña de aplicación para probar."), 400

    config = {"email": email, "app_password": app_password, "imap_host": imap_host, "imap_port": imap_port}

    try:
        movimientos = lc.buscar_movimientos_correo(dias, config)
    except Exception as e:
        return jsonify(ok=False, error=f"No se pudo conectar/leer: {e}"), 400

    return jsonify(ok=True, total=len(movimientos), movimientos=movimientos[:20])


@correo_bp.route("/api/correo/sincronizar-ahora", methods=["POST"])
@login_required
def api_correo_sincronizar_ahora():
    usuario_id = session["usuario_id"]
    with db.conexion() as conn:
        config = db.obtener_correo_config(conn, usuario_id)

    if not config:
        return jsonify(ok=False, error="Todavía no configuraste tu correo."), 400

    try:
        mensaje = lc.procesar_cuenta(config, dias=2, aplicar=True)
    except Exception as e:
        with db.conexion() as conn:
            db.actualizar_estado_correo(conn, usuario_id, ok=False, error=str(e))
        return jsonify(ok=False, error=str(e)), 400

    return jsonify(ok=True, mensaje=mensaje)


@correo_bp.route("/api/correo/eliminar", methods=["POST"])
@login_required
def api_correo_eliminar():
    with db.conexion() as conn:
        db.eliminar_correo_config(conn, session["usuario_id"])
    return jsonify(ok=True)
