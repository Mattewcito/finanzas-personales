"""
Pruebas de las protecciones de seguridad agregadas el 2026-09-11 tras el
review de `qa_reports/security_review_2026-09-11.md`:

  - Cabeceras de seguridad HTTP (src/app.py::agregar_cabeceras_seguridad)
  - Mitigación de CSRF por verificación de Origin/Referer
    (src/app.py::verificar_origen)
  - Rate limiting en memoria de /login (src/auth.py)
  - Longitud mínima de contraseña de 8 caracteres
    (src/routes/usuarios.py::PASSWORD_MIN_LEN)

IMPORTANTE -- reutiliza las fixtures app_ctx/client/login de
tests/test_app_integration.py: ese archivo es el único que puede hacer
"import app" (ver su docstring).
"""
import auth as auth_module

from test_app_integration import app_ctx, client, login  # noqa: F401 (fixtures reutilizadas)


# ---------------------------------------------------------------------------
# a. Cabeceras de seguridad presentes en cualquier respuesta.
# ---------------------------------------------------------------------------

def test_cabeceras_de_seguridad_presentes(client):
    resp = client.get("/login")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in resp.headers.get("Content-Security-Policy", "")
    assert "object-src 'none'" in resp.headers.get("Content-Security-Policy", "")


# ---------------------------------------------------------------------------
# b. Verificación de Origin/Referer en requests que cambian estado.
# ---------------------------------------------------------------------------

def test_post_con_origin_ajeno_es_rechazado(client, app_ctx):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post(
        "/cambiar-vista",
        data={"usuario_id": 1},
        headers={"Origin": "https://sitio-malicioso.example"},
    )
    assert resp.status_code == 403


def test_post_con_origin_propio_pasa(client, app_ctx):
    # El test client de Flask/Werkzeug usa "localhost" como host por
    # defecto (sin base_url explícito) -- un Origin con ese mismo host
    # tiene que pasar la verificación sin problema.
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")
    resp = client.post(
        "/cambiar-vista",
        data={"usuario_id": user_id},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 302


def test_post_sin_origin_ni_referer_pasa(client, app_ctx):
    # El test client "normal" no manda Origin/Referer -- este es
    # exactamente el caso que ya cubre el resto de la suite (591 tests
    # existentes siguen en verde), lo dejamos explícito acá también.
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/cambiar-vista", data={"usuario_id": user_id})
    assert resp.status_code == 302


def test_health_excluido_de_la_verificacion_de_origen(app_ctx):
    flaskapp, _, _ = app_ctx
    with flaskapp.app.test_client() as c:
        resp = c.get("/health", headers={"Origin": "https://sitio-malicioso.example"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# c. Rate limiting de /login: 5 fallos bloquean el 6to intento (429),
#    y un login correcto limpia el contador.
# ---------------------------------------------------------------------------

def test_login_se_bloquea_tras_cinco_intentos_fallidos(client):
    auth_module._INTENTOS_FALLIDOS.clear()
    try:
        for _ in range(5):
            resp = login(client, "admin_test", "clave-mala")
            assert resp.status_code == 200

        resp_bloqueado = login(client, "admin_test", "clave-mala")
        assert resp_bloqueado.status_code == 429
        assert "intentos".encode() in resp_bloqueado.data.lower() or b"Demasiados" in resp_bloqueado.data

        # Incluso con la contraseña CORRECTA, sigue bloqueado mientras
        # dure la ventana de bloqueo.
        resp_correcto_pero_bloqueado = login(client, "admin_test", "clave-admin-123")
        assert resp_correcto_pero_bloqueado.status_code == 429
    finally:
        auth_module._INTENTOS_FALLIDOS.clear()


def test_login_correcto_limpia_el_contador_de_intentos_fallidos(client):
    auth_module._INTENTOS_FALLIDOS.clear()
    try:
        for _ in range(3):
            login(client, "admin_test", "clave-mala")

        resp_ok = login(client, "admin_test", "clave-admin-123")
        assert resp_ok.status_code == 302

        clave_user = "user:admin_test"
        assert clave_user not in auth_module._INTENTOS_FALLIDOS
    finally:
        auth_module._INTENTOS_FALLIDOS.clear()


# ---------------------------------------------------------------------------
# d. Contraseña mínima de 8 caracteres en las tres rutas que la validan.
# ---------------------------------------------------------------------------

def test_crear_usuario_rechaza_password_corta(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post(
        "/api/crear-usuario",
        data={"username": "nuevo", "nombre": "Nuevo", "password": "1234567", "rol": "usuario"},
    )
    assert resp.status_code == 400
    assert "8 caracteres" in resp.get_json()["error"]


def test_crear_usuario_acepta_password_de_ocho(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post(
        "/api/crear-usuario",
        data={"username": "nuevo8", "nombre": "Nuevo8", "password": "12345678", "rol": "usuario"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_actualizar_perfil_rechaza_password_corta(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post(
        "/api/actualizar-perfil",
        data={"username": "admin_test", "nombre": "Admin", "password": "corta1"},
    )
    assert resp.status_code == 400
    assert "8 caracteres" in resp.get_json()["error"]


def test_editar_usuario_rechaza_password_corta(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")
    resp = client.post(
        f"/api/editar-usuario/{user_id}",
        data={"username": "user_test", "nombre": "Usuario", "password": "corta1", "rol": "usuario"},
    )
    assert resp.status_code == 400
    assert "8 caracteres" in resp.get_json()["error"]
