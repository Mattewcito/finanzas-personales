"""
Pruebas de routes/correo.py (blueprint "correo"): configuración de la
lectura automática de correo desde la interfaz web (Fase 1, ver
src/leer_correo.py y src/db_finanzas.py::correo_config).

IMPORTANTE -- reutiliza las fixtures app_ctx/client/login definidas en
tests/test_app_integration.py en vez de volver a hacer "import app": ese
import solo puede pasar en un único archivo de toda la corrida (los
valores calculados una sola vez al importar, como UPLOADS_DIR, quedarían
inconsistentes si se importara app.py más de una vez). Ver el docstring
de tests/test_app_integration.py para el detalle.

Todas las rutas de este blueprint usan siempre session["usuario_id"]
(nunca viendo_id()) -- ver el docstring de src/routes/correo.py.
"""
import db_finanzas as db
import leer_correo as lc

from test_app_integration import app_ctx, client, login  # noqa: F401 (fixtures reutilizadas)


def guardar_config_directo(usuario_id, **extra):
    """Crea una fila de correo_config directamente por BD (sin pasar por
    la ruta), para probar escenarios que requieren "ya había una config
    guardada de antes"."""
    kwargs = {"email": f"usuario{usuario_id}@example.com", "app_password": "clave-original"}
    kwargs.update(extra)
    with db.conexion() as conn:
        db.guardar_correo_config(conn, usuario_id, **kwargs)


def config_de(usuario_id):
    with db.conexion() as conn:
        return db.obtener_correo_config(conn, usuario_id)


FORM_BASE = {
    "email": "correo@example.com",
    "app_password": "clave-app-123",
    "imap_host": "imap.gmail.com",
    "imap_port": "993",
    "frecuencia_tipo": "intervalo",
    "frecuencia_minutos": "30",
    "frecuencia_hora": "",
    "activo": "1",
}


# ---------------------------------------------------------------------------
# GET /configurar-correo
# ---------------------------------------------------------------------------

def test_get_configurar_correo_sin_config_previa_da_200_sin_reventar(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.get("/configurar-correo")
    assert resp.status_code == 200


def test_get_configurar_correo_con_config_guardada_no_expone_la_password_en_el_html(client, app_ctx):
    _, admin_id, _ = app_ctx
    guardar_config_directo(admin_id, app_password="secreta-super-unica-xyz")
    login(client, "admin_test", "clave-admin-123")

    resp = client.get("/configurar-correo")

    assert resp.status_code == 200
    assert b"secreta-super-unica-xyz" not in resp.data


def test_configurar_correo_redirige_a_login_sin_sesion(client):
    resp = client.get("/configurar-correo")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# POST /api/correo/guardar -- validaciones
# ---------------------------------------------------------------------------

def test_guardar_primera_vez_sin_contrasena_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    datos = dict(FORM_BASE)
    datos["app_password"] = ""
    resp = client.post("/api/correo/guardar", data=datos)
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_guardar_con_email_invalido_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    datos = dict(FORM_BASE)
    datos["email"] = "no-es-un-correo"
    resp = client.post("/api/correo/guardar", data=datos)
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_guardar_intervalo_con_minutos_por_debajo_del_minimo_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    datos = dict(FORM_BASE)
    datos["frecuencia_minutos"] = "2"
    resp = client.post("/api/correo/guardar", data=datos)
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_guardar_intervalo_con_minutos_por_encima_del_maximo_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    datos = dict(FORM_BASE)
    datos["frecuencia_minutos"] = "2000"
    resp = client.post("/api/correo/guardar", data=datos)
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_guardar_diario_con_hora_mal_formada_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    datos = dict(FORM_BASE)
    datos["frecuencia_tipo"] = "diario"
    datos["frecuencia_hora"] = "25:99"
    resp = client.post("/api/correo/guardar", data=datos)
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_guardar_diario_con_hora_vacia_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    datos = dict(FORM_BASE)
    datos["frecuencia_tipo"] = "diario"
    datos["frecuencia_hora"] = ""
    resp = client.post("/api/correo/guardar", data=datos)
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/correo/guardar -- caso feliz
# ---------------------------------------------------------------------------

def test_guardar_caso_feliz_da_200_y_queda_correctamente_en_la_bd(client, app_ctx):
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")

    resp = client.post("/api/correo/guardar", data=dict(FORM_BASE))

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    fila = config_de(admin_id)
    assert fila is not None
    assert fila["email"] == "correo@example.com"
    assert fila["app_password"] == "clave-app-123"
    assert fila["frecuencia_tipo"] == "intervalo"
    assert fila["frecuencia_minutos"] == 30


def test_guardar_caso_feliz_diario_da_200_y_guarda_la_hora(client, app_ctx):
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")

    datos = dict(FORM_BASE)
    datos["frecuencia_tipo"] = "diario"
    datos["frecuencia_hora"] = "08:30"

    resp = client.post("/api/correo/guardar", data=datos)

    assert resp.status_code == 200
    fila = config_de(admin_id)
    assert fila["frecuencia_tipo"] == "diario"
    assert fila["frecuencia_hora"] == "08:30"


# ---------------------------------------------------------------------------
# Aislamiento entre usuarios -- el caso más importante
# ---------------------------------------------------------------------------

def test_guardar_y_eliminar_de_un_usuario_no_afecta_la_config_del_otro(client, app_ctx):
    _, admin_id, user_id = app_ctx

    login(client, "admin_test", "clave-admin-123")
    datos_admin = dict(FORM_BASE)
    datos_admin["email"] = "admin@example.com"
    client.post("/api/correo/guardar", data=datos_admin)
    client.get("/logout")

    login(client, "user_test", "clave-user-456")
    datos_user = dict(FORM_BASE)
    datos_user["email"] = "user@example.com"
    client.post("/api/correo/guardar", data=datos_user)

    fila_admin = config_de(admin_id)
    fila_user = config_de(user_id)
    assert fila_admin["email"] == "admin@example.com"
    assert fila_user["email"] == "user@example.com"

    # el usuario normal borra SU config -- la del admin debe seguir intacta
    resp = client.post("/api/correo/eliminar")
    assert resp.status_code == 200
    assert config_de(user_id) is None
    assert config_de(admin_id) is not None
    assert config_de(admin_id)["email"] == "admin@example.com"


def test_guardar_nunca_usa_otro_usuario_id_aunque_se_intente_forzar_por_form(client, app_ctx):
    """Ni siquiera si el form trajera un usuario_id, la ruta debe usar
    siempre session['usuario_id'] -- nunca otro (ver docstring del
    blueprint: esto es info técnica de UNA cuenta, no un dato "viendo")."""
    _, admin_id, user_id = app_ctx
    login(client, "user_test", "clave-user-456")

    datos = dict(FORM_BASE)
    datos["usuario_id"] = str(admin_id)  # el form no debería tener efecto acá
    client.post("/api/correo/guardar", data=datos)

    assert config_de(user_id) is not None
    assert config_de(admin_id) is None


# ---------------------------------------------------------------------------
# POST /api/correo/probar
# ---------------------------------------------------------------------------

def test_probar_sin_config_previa_y_sin_campos_en_el_form_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/correo/probar", data={})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_probar_con_movimientos_mockeados_da_200_y_no_inserta_nada(client, app_ctx, monkeypatch):
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")

    movimientos_falsos = [
        {"fecha": "2026-09-01", "tipo": "gasto", "categoria": "otros", "moneda": "COP",
         "monto": 1000.0 * i, "descripcion": f"Movimiento {i}", "entidad": "Bancolombia"}
        for i in range(25)
    ]
    monkeypatch.setattr(lc, "buscar_movimientos_correo", lambda dias, config: movimientos_falsos)

    resp = client.post("/api/correo/probar", data={
        "email": "correo@example.com", "app_password": "clave-app-123",
    })

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["total"] == 25
    assert len(body["movimientos"]) == 20  # tope de 20, aunque el mock devuelva más

    with db.conexion() as conn:
        assert db.obtener_movimientos(conn, usuario_id=admin_id) == []


def test_probar_usa_credenciales_ya_guardadas_como_fallback_si_el_form_viene_vacio(client, app_ctx, monkeypatch):
    _, admin_id, _ = app_ctx
    guardar_config_directo(admin_id, email="guardado@example.com", app_password="clave-guardada")
    login(client, "admin_test", "clave-admin-123")

    recibido = {}

    def _fake_buscar(dias, config):
        recibido.update(config)
        return []

    monkeypatch.setattr(lc, "buscar_movimientos_correo", _fake_buscar)

    resp = client.post("/api/correo/probar", data={})

    assert resp.status_code == 200
    assert recibido["email"] == "guardado@example.com"
    assert recibido["app_password"] == "clave-guardada"


def test_probar_con_excepcion_de_imap_da_400(client, monkeypatch):
    login(client, "admin_test", "clave-admin-123")

    def _fallar(dias, config):
        raise RuntimeError("no se pudo conectar")

    monkeypatch.setattr(lc, "buscar_movimientos_correo", _fallar)

    resp = client.post("/api/correo/probar", data={
        "email": "correo@example.com", "app_password": "clave-app-123",
    })

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/correo/sincronizar-ahora
# ---------------------------------------------------------------------------

def test_sincronizar_ahora_sin_config_previa_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/correo/sincronizar-ahora")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_sincronizar_ahora_con_config_previa_y_procesar_cuenta_ok_da_200(client, app_ctx, monkeypatch):
    _, admin_id, _ = app_ctx
    guardar_config_directo(admin_id)
    login(client, "admin_test", "clave-admin-123")

    monkeypatch.setattr(lc, "procesar_cuenta", lambda config, dias, aplicar: "2 movimiento(s) insertado(s)")

    resp = client.post("/api/correo/sincronizar-ahora")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["mensaje"] == "2 movimiento(s) insertado(s)"


def test_sincronizar_ahora_con_excepcion_da_400_y_deja_el_estado_de_error_en_bd(client, app_ctx, monkeypatch):
    _, admin_id, _ = app_ctx
    guardar_config_directo(admin_id)
    login(client, "admin_test", "clave-admin-123")

    def _fallar(config, dias, aplicar):
        raise RuntimeError("fallo simulado de sincronizacion")

    monkeypatch.setattr(lc, "procesar_cuenta", _fallar)

    resp = client.post("/api/correo/sincronizar-ahora")

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False

    fila = config_de(admin_id)
    assert fila["ultima_corrida_ok"] == 0
    assert "fallo simulado de sincronizacion" in fila["ultimo_error"]


def test_sincronizar_ahora_redirige_a_login_sin_sesion(client):
    resp = client.post("/api/correo/sincronizar-ahora")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# POST /api/correo/eliminar
# ---------------------------------------------------------------------------

def test_eliminar_borra_la_config_y_deja_de_aparecer(client, app_ctx):
    _, admin_id, _ = app_ctx
    guardar_config_directo(admin_id)
    login(client, "admin_test", "clave-admin-123")

    resp = client.post("/api/correo/eliminar")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert config_de(admin_id) is None

    resp_get = client.get("/configurar-correo")
    assert resp_get.status_code == 200


# ---------------------------------------------------------------------------
# Todas las rutas requieren login
# ---------------------------------------------------------------------------

def test_api_correo_guardar_redirige_a_login_sin_sesion(client):
    resp = client.post("/api/correo/guardar", data=dict(FORM_BASE))
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_api_correo_probar_redirige_a_login_sin_sesion(client):
    resp = client.post("/api/correo/probar", data={})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_api_correo_eliminar_redirige_a_login_sin_sesion(client):
    resp = client.post("/api/correo/eliminar")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
