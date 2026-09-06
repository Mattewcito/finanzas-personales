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
from flask import session

import db_finanzas as db
import actualizar_dashboard as ad
from auth import inyectar_globales


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


def test_inyectar_globales_deja_al_admin_logueado_primero_aunque_no_sea_el_de_menor_id(client, app_ctx):
    """usuarios_disponibles debe traer SIEMPRE primero la cuenta del
    admin logueado (session['usuario_id']), sin importar su orden de
    creación en la BD -- acá el admin logueado es el tercer usuario
    creado (el de mayor id), para que un `sort` que ordenara por id (en
    vez de anclar al propio) haga fallar el test."""
    flaskapp, admin_id, user_id = app_ctx
    conn = db.conectar()
    otro_admin_id = db.crear_usuario(conn, "admin2_test", "clave-admin2-000", "admin", "Admin Dos")
    conn.close()
    assert otro_admin_id > user_id > admin_id  # nace en tercer lugar, con el id más alto

    with flaskapp.app.test_request_context():
        session["usuario_id"] = otro_admin_id
        session["rol"] = "admin"
        session["nombre"] = "Admin Dos"
        session["viendo_id"] = otro_admin_id
        ctx = inyectar_globales()

    ids_en_orden = [u["id"] for u in ctx["usuarios_disponibles"]]
    assert ids_en_orden[0] == otro_admin_id
    # el resto conserva su orden relativo original (por id ascendente)
    assert ids_en_orden[1:] == [admin_id, user_id]


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


# ---------------------------------------------------------------------------
# GET /api/dashboard-data -- el dashboard ahora es dinámico: el navegador
# pide sus datos por AJAX en vez de leer un HTML pre-generado (ver
# routes/dashboard.py::api_dashboard_data y tests/test_actualizar_dashboard.py
# para el cambio en actualizar_dashboard.py que esto reemplazó).
# ---------------------------------------------------------------------------

def test_dashboard_data_redirige_a_login_sin_sesion(client):
    resp = client.get("/api/dashboard-data")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_dashboard_data_con_sesion_devuelve_json_con_las_cuatro_claves(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.get("/api/dashboard-data")

    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"movimientos", "ledger_deuda", "perfil", "generated_at"}


def test_dashboard_data_usuario_sin_movimientos_devuelve_listas_vacias_sin_reventar(client):
    """Caso disperso: un usuario recién creado, sin ningún movimiento
    cargado todavía. No debe reventar (NaN%, división por cero) -- debe
    devolver listas vacías y un perfil con arquetipo 'Sin datos
    suficientes' (ver perfil_financiero.clasificar_perfil)."""
    login(client, "user_test", "clave-user-456")
    resp = client.get("/api/dashboard-data")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["movimientos"] == []
    assert body["ledger_deuda"] == []
    assert body["perfil"]["arquetipo"] == "Sin datos suficientes"


def test_dashboard_data_aisla_movimientos_entre_usuarios(client, app_ctx):
    """Los movimientos que registra un usuario no deben aparecer en la
    respuesta de /api/dashboard-data de otro (fuga de datos entre
    usuarios, el bug de regresión ya visto antes en este proyecto)."""
    _, admin_id, user_id = app_ctx

    login(client, "admin_test", "clave-admin-123")
    client.post("/api/registrar-movimiento", data={
        "fecha": "2026-01-15", "tipo": "gasto", "monto": "10000",
        "descripcion": "Solo del admin", "categoria": "otros",
        "moneda": "COP", "entidad": "Test",
    })
    resp_admin = client.get("/api/dashboard-data")
    client.get("/logout")

    login(client, "user_test", "clave-user-456")
    resp_user = client.get("/api/dashboard-data")

    descripciones_admin = {m["descripcion"] for m in resp_admin.get_json()["movimientos"]}
    descripciones_user = {m["descripcion"] for m in resp_user.get_json()["movimientos"]}

    assert "Solo del admin" in descripciones_admin
    assert "Solo del admin" not in descripciones_user
    assert descripciones_user == set()


def test_dashboard_data_tras_cambiar_vista_muestra_datos_de_la_cuenta_vista(client, app_ctx):
    """Si el admin cambia de perfil vía /cambiar-vista, /api/dashboard-data
    debe devolver los datos de la cuenta que está viendo ahora, no los
    propios del admin (viendo_id(), no usuario_id de sesión)."""
    _, admin_id, user_id = app_ctx

    login(client, "admin_test", "clave-admin-123")
    client.post("/api/registrar-movimiento", data={
        "fecha": "2026-01-15", "tipo": "gasto", "monto": "5000",
        "descripcion": "Movimiento del admin", "categoria": "otros",
        "moneda": "COP", "entidad": "Test",
    })

    conn = db.conectar()
    db.insertar_movimientos(
        conn,
        [{
            "fecha": "2026-01-20", "tipo": "gasto", "categoria": "otros", "moneda": "COP",
            "monto": 7000.0, "descripcion": "Movimiento del usuario normal", "entidad": "Test",
        }],
        origen="manual",
        usuario_id=user_id,
    )
    conn.close()

    cambio = client.post("/cambiar-vista", data={"usuario_id": user_id})
    assert cambio.status_code == 302

    resp = client.get("/api/dashboard-data")
    descripciones = {m["descripcion"] for m in resp.get_json()["movimientos"]}

    assert "Movimiento del usuario normal" in descripciones
    assert "Movimiento del admin" not in descripciones
