"""
Pruebas de integración de la app Flask: login, control de acceso, y
aislamiento de datos entre usuarios.

IMPORTANTE: usan una base de datos temporal (tmp_path de pytest), nunca
finanzas.db real. La fixture "client" parchea db_finanzas.DATA_DIR ANTES
de importar app.py por primera vez -- por eso ningún otro archivo de
test debe hacer "import app" fuera de esta fixture (los valores como
UPLOADS_DIR se calculan una sola vez, al importar).
"""
import pytest
import db_finanzas as db


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "finanzas.db")
    monkeypatch.setattr(db, "XLSX_PATH", tmp_path / "finanzas_personales.xlsx")

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
