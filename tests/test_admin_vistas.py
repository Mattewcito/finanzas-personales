"""
Pruebas de routes/admin_vistas.py (blueprint "admin_vistas"): panel de
administración para ocultar/mostrar secciones del menú/dashboard por
usuario (ver db_finanzas.py::VISTAS_DISPONIBLES para el catálogo
completo -- hoy "dashboard", "perfil_financiero", "insights", "deuda",
"analisis", "movimientos" y "correo_automatico"). La mayoría de estos
tests usan "correo_automatico" como vista de ejemplo porque la
validación/el toggle son genéricos y no distinguen por id; ver
test_toggle_acepta_cada_una_de_las_tres_vistas_nuevas_como_valor_valido
para el caso explícito de las 3 vistas agregadas más recientemente.

IMPORTANTE -- reutiliza las fixtures app_ctx/client/login definidas en
tests/test_app_integration.py en vez de volver a hacer "import app": ese
import solo puede pasar en un único archivo de toda la corrida. Ver el
docstring de tests/test_app_integration.py para el detalle.
"""
import pytest

import db_finanzas as db

from test_app_integration import app_ctx, client, login  # noqa: F401 (fixtures reutilizadas)


# ---------------------------------------------------------------------------
# GET /admin/vistas -- control de acceso
# ---------------------------------------------------------------------------

def test_get_admin_vistas_redirige_a_login_sin_sesion(client):
    resp = client.get("/admin/vistas")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_get_admin_vistas_con_usuario_no_admin_redirige_a_dashboard_no_403(client):
    login(client, "user_test", "clave-user-456")
    resp = client.get("/admin/vistas")
    assert resp.status_code == 302
    assert "/login" not in resp.headers["Location"]


def test_get_admin_vistas_con_admin_da_200_e_incluye_a_todos_los_usuarios(client, app_ctx):
    flaskapp, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")

    resp = client.get("/admin/vistas")

    assert resp.status_code == 200
    assert b"admin_test" in resp.data
    assert b"user_test" in resp.data


# ---------------------------------------------------------------------------
# POST /api/admin/vistas/toggle -- control de acceso
# ---------------------------------------------------------------------------

def test_toggle_sin_sesion_redirige_a_login(client):
    """@login_required corre ANTES que el chequeo de rol admin: sin
    sesión, lo que se dispara es el redirect a /login (302), no el 403
    de "no sos admin" -- ese 403 es solo para cuando SÍ hay sesión pero
    el rol no es admin (ver test_toggle_con_usuario_no_admin_da_403)."""
    resp = client.post("/api/admin/vistas/toggle", data={
        "usuario_id": "1", "vista": "correo_automatico", "visible": "0",
    })
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_toggle_con_usuario_no_admin_da_403(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "user_test", "clave-user-456")

    resp = client.post("/api/admin/vistas/toggle", data={
        "usuario_id": str(admin_id), "vista": "correo_automatico", "visible": "0",
    })

    assert resp.status_code == 403
    assert resp.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/admin/vistas/toggle -- caso feliz (ocultar / mostrar)
# ---------------------------------------------------------------------------

def test_toggle_visible_0_oculta_la_vista_para_ese_usuario(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")

    resp = client.post("/api/admin/vistas/toggle", data={
        "usuario_id": str(user_id), "vista": "correo_automatico", "visible": "0",
    })

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    with db.conexion() as conn:
        assert db.vistas_ocultas_de(conn, user_id) == {"correo_automatico"}


def test_toggle_visible_1_sobre_algo_ya_oculto_lo_vuelve_a_mostrar(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")

    client.post("/api/admin/vistas/toggle", data={
        "usuario_id": str(user_id), "vista": "correo_automatico", "visible": "0",
    })
    resp = client.post("/api/admin/vistas/toggle", data={
        "usuario_id": str(user_id), "vista": "correo_automatico", "visible": "1",
    })

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    with db.conexion() as conn:
        assert db.vistas_ocultas_de(conn, user_id) == set()


@pytest.mark.parametrize("vista_id", ["deuda", "analisis", "movimientos"])
def test_toggle_acepta_cada_una_de_las_tres_vistas_nuevas_como_valor_valido(client, app_ctx, vista_id):
    """La validación de /api/admin/vistas/toggle es genérica (vistas_validas
    = {v["id"] for v in db.VISTAS_DISPONIBLES}), así que "debería andar"
    para deuda/analisis/movimientos sin tocar la ruta -- este test lo
    ejercita explícitamente en vez de confiar en esa suposición."""
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")

    resp = client.post("/api/admin/vistas/toggle", data={
        "usuario_id": str(user_id), "vista": vista_id, "visible": "0",
    })

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    with db.conexion() as conn:
        assert db.vistas_ocultas_de(conn, user_id) == {vista_id}

    resp = client.post("/api/admin/vistas/toggle", data={
        "usuario_id": str(user_id), "vista": vista_id, "visible": "1",
    })

    assert resp.status_code == 200
    with db.conexion() as conn:
        assert db.vistas_ocultas_de(conn, user_id) == set()


# ---------------------------------------------------------------------------
# POST /api/admin/vistas/toggle -- validaciones
# ---------------------------------------------------------------------------

def test_toggle_con_vista_desconocida_da_400_y_no_inserta_nada(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")

    resp = client.post("/api/admin/vistas/toggle", data={
        "usuario_id": str(user_id), "vista": "vista_que_no_existe", "visible": "0",
    })

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    with db.conexion() as conn:
        assert db.vistas_ocultas_de(conn, user_id) == set()
        # tampoco quedó ninguna fila "rara" en la tabla en general
        total = conn.execute("SELECT COUNT(*) AS n FROM vistas_ocultas").fetchone()["n"]
        assert total == 0


def test_toggle_con_usuario_id_inexistente_da_400(client, app_ctx):
    login(client, "admin_test", "clave-admin-123")

    resp = client.post("/api/admin/vistas/toggle", data={
        "usuario_id": "999999", "vista": "correo_automatico", "visible": "0",
    })

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
