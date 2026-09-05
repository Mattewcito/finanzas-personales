"""
Pruebas de integración de la app Flask: login, control de acceso, y
aislamiento de datos entre usuarios.

IMPORTANTE: usan una base de datos temporal (tmp_path de pytest), nunca
finanzas.db real. La fixture "client" parchea db_finanzas.DATA_DIR ANTES
de importar app.py por primera vez -- por eso ningún otro archivo de
test debe hacer "import app" fuera de esta fixture (los valores como
UPLOADS_DIR se calculan una sola vez, al importar).

También parchea actualizar_dashboard.PROJECT_ROOT/LOG_PATH: varias rutas
(src/routes/dashboard.py, src/routes/usuarios.py) llaman a
actualizar_dashboard.main() de forma síncrona, y esos dos valores también
se calculan una sola vez al importar el módulo -- si no se parchean acá,
cada corrida de estos tests sobrescribe de verdad
data/dashboard_<id>.html y data/actualizar_dashboard.log con datos de
prueba (bug de regresión real, detectado y corregido el 2026-09-05: ver
tests/test_actualizar_dashboard.py para el detalle del aislamiento).
"""
import pytest
import db_finanzas as db
import actualizar_dashboard as ad


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "finanzas.db")
    monkeypatch.setattr(db, "XLSX_PATH", tmp_path / "finanzas_personales.xlsx")
    monkeypatch.setattr(ad, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ad, "LOG_PATH", tmp_path / "actualizar_dashboard.log")

    import app as flaskapp  # primera y única importación de app.py en toda la corrida de tests
    flaskapp.app.config.update(TESTING=True)

    conn = db.conectar()
    db.crear_esquema(conn)
    admin_id = db.crear_usuario(conn, "admin_test", "clave-admin-123", "admin", "Admin")
    user_id = db.crear_usuario(conn, "user_test", "clave-user-456", "usuario", "Usuario")
    conn.close()

    return flaskapp, admin_id, user_id


@pytest.fixture
def client(app_ctx):
    flaskapp, _, _ = app_ctx
    with flaskapp.app.test_client() as c:
        yield c


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def test_login_correcto_redirige_al_dashboard(client):
    resp = login(client, "admin_test", "clave-admin-123")
    assert resp.status_code == 302


def test_login_incorrecto_muestra_error(client):
    resp = login(client, "admin_test", "clave-mala")
    assert resp.status_code == 200
    assert "incorrectos".encode() in resp.data


def test_ruta_protegida_redirige_a_login_sin_sesion(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_health_responde_sin_login(app_ctx):
    flaskapp, _, _ = app_ctx
    with flaskapp.app.test_client() as c:
        resp = c.get("/health")
        assert resp.status_code == 200


def test_usuario_normal_no_puede_cambiar_de_perfil(client):
    login(client, "user_test", "clave-user-456")
    resp = client.post("/cambiar-vista", data={"usuario_id": 1})
    assert resp.status_code == 403


def test_admin_si_puede_cambiar_de_perfil(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/cambiar-vista", data={"usuario_id": user_id})
    assert resp.status_code == 302


def test_datos_quedan_aislados_entre_usuarios(client, app_ctx):
    _, admin_id, user_id = app_ctx

    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data={
        "fecha": "2026-01-15", "tipo": "gasto", "monto": "10000",
        "descripcion": "Prueba admin", "categoria": "otros",
        "moneda": "COP", "entidad": "Test",
    })
    assert resp.get_json()["nuevos"] == 1
    client.get("/logout")

    conn = db.conectar()
    movs_admin = db.obtener_movimientos(conn, usuario_id=admin_id)
    movs_user = db.obtener_movimientos(conn, usuario_id=user_id)
    conn.close()

    assert len(movs_admin) == 1
    assert len(movs_user) == 0


def test_dedup_no_duplica_mismo_dia_y_monto(client):
    login(client, "admin_test", "clave-admin-123")
    datos = {
        "fecha": "2026-02-01", "tipo": "gasto", "monto": "5000",
        "descripcion": "Primero", "categoria": "otros",
        "moneda": "COP", "entidad": "Test",
    }
    r1 = client.post("/api/registrar-movimiento", data=datos)
    datos["descripcion"] = "Segundo, pero mismo monto y fecha"
    r2 = client.post("/api/registrar-movimiento", data=datos)

    assert r1.get_json()["nuevos"] == 1
    assert r2.get_json()["duplicados"] == 1


# ---------------------------------------------------------------------------
# Validación de /api/registrar-movimiento (más allá del happy path y dedup)
# ---------------------------------------------------------------------------

def test_registrar_movimiento_sin_fecha_da_error_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data={
        "fecha": "", "tipo": "gasto", "monto": "1000",
        "descripcion": "Sin fecha", "categoria": "otros",
        "moneda": "COP", "entidad": "Test",
    })
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_registrar_movimiento_sin_descripcion_da_error_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data={
        "fecha": "2026-03-01", "tipo": "gasto", "monto": "1000",
        "descripcion": "", "categoria": "otros",
        "moneda": "COP", "entidad": "Test",
    })
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_registrar_movimiento_con_monto_no_numerico_da_error_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data={
        "fecha": "2026-03-01", "tipo": "gasto", "monto": "no-es-un-numero",
        "descripcion": "Monto inválido", "categoria": "otros",
        "moneda": "COP", "entidad": "Test",
    })
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_registrar_movimiento_con_monto_cero_o_negativo_da_error_400(client):
    login(client, "admin_test", "clave-admin-123")
    for monto in ("0", "-500"):
        resp = client.post("/api/registrar-movimiento", data={
            "fecha": "2026-03-01", "tipo": "gasto", "monto": monto,
            "descripcion": "Monto no positivo", "categoria": "otros",
            "moneda": "COP", "entidad": "Test",
        })
        assert resp.status_code == 400
        assert resp.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# Control de acceso por rol en rutas de usuarios (blueprint "usuarios")
# ---------------------------------------------------------------------------

def test_usuario_normal_no_puede_ver_pagina_crear_usuario(client):
    """La página /crear-usuario redirige (no da 403) cuando el rol no es
    admin -- así es como está implementado en routes/usuarios.py."""
    login(client, "user_test", "clave-user-456")
    resp = client.get("/crear-usuario")
    assert resp.status_code == 302
    assert "/login" not in resp.headers["Location"]


def test_usuario_normal_no_puede_llamar_api_crear_usuario(client):
    login(client, "user_test", "clave-user-456")
    resp = client.post("/api/crear-usuario", data={
        "username": "nuevo_x", "nombre": "Nuevo X",
        "password": "clave-nueva", "rol": "usuario",
    })
    assert resp.status_code == 403


def test_usuario_normal_no_puede_llamar_api_editar_usuario(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "user_test", "clave-user-456")
    resp = client.post(f"/api/editar-usuario/{admin_id}", data={
        "username": "hackeado", "nombre": "Hackeado", "password": "", "rol": "admin",
    })
    assert resp.status_code == 403


def test_admin_puede_crear_usuario_nuevo_via_api(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/crear-usuario", data={
        "username": "user_nuevo", "nombre": "Usuario Nuevo",
        "password": "clave-nueva-123", "rol": "usuario",
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert isinstance(body["id"], int)


def test_admin_puede_editar_usuario_creado_por_el(client):
    login(client, "admin_test", "clave-admin-123")
    creado = client.post("/api/crear-usuario", data={
        "username": "user_editable", "nombre": "Antes de editar",
        "password": "clave-nueva-123", "rol": "usuario",
    })
    nuevo_id = creado.get_json()["id"]

    resp = client.post(f"/api/editar-usuario/{nuevo_id}", data={
        "username": "user_editable", "nombre": "Después de editar",
        "password": "", "rol": "usuario",
    })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


# ---------------------------------------------------------------------------
# /mi-perfil y /api/actualizar-perfil
# ---------------------------------------------------------------------------

def test_usuario_puede_editar_su_propio_perfil(client):
    login(client, "user_test", "clave-user-456")
    resp = client.post("/api/actualizar-perfil", data={
        "username": "user_test_renombrado",
        "nombre": "Usuario Renombrado",
        "password": "clave-nueva-789",
    })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_editar_perfil_actualiza_nombre_en_sesion_sin_relogin(client):
    """El cambio de nombre debe reflejarse en session['nombre'] de una,
    sin que el usuario tenga que volver a loguearse."""
    login(client, "user_test", "clave-user-456")

    resp = client.post("/api/actualizar-perfil", data={
        "username": "user_test",
        "nombre": "Nombre Actualizado En Sesion",
        "password": "",
    })
    assert resp.status_code == 200

    with client.session_transaction() as sess:
        assert sess["nombre"] == "Nombre Actualizado En Sesion"


# ---------------------------------------------------------------------------
# /editar-usuario/<id> con un id que no existe
# ---------------------------------------------------------------------------

def test_editar_usuario_inexistente_redirige_en_vez_de_reventar(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.get("/editar-usuario/999999")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/crear-usuario")


# ---------------------------------------------------------------------------
# Rutas protegidas sin sesión (regresión de blueprints: que a nadie se le
# haya olvidado el decorador @login_required al mover la ruta)
# ---------------------------------------------------------------------------

def test_registrar_redirige_a_login_sin_sesion(client):
    resp = client.get("/registrar")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_crear_usuario_redirige_a_login_sin_sesion(client):
    resp = client.get("/crear-usuario")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_mi_perfil_redirige_a_login_sin_sesion(client):
    resp = client.get("/mi-perfil")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
