"""
Pruebas de la extensión de "vistas ocultas por usuario" a las sub-vistas
del dashboard: "dashboard", "perfil_financiero" e "insights" (ver
db_finanzas.py::VISTAS_DISPONIBLES, auth.py::requiere_vista_visible /
inyectar_globales, routes/dashboard.py::api_dashboard_data).

Diferencia central respecto de "correo_automatico" (ver
tests/test_correo_routes.py): estas tres se chequean por viendo_id()
(`requiere_vista_visible(..., por_viendo=True)`), no por
session["usuario_id"] -- lo que importa es DE QUÉ CUENTA se muestran
datos, no quién inició sesión. Un admin "viendo" el perfil de un usuario
restringido queda tan bloqueado como ese usuario; y si el admin se
restringe a sí mismo pero está viendo a otro sin restricciones, no queda
bloqueado.

IMPORTANTE -- reutiliza las fixtures app_ctx/client/login definidas en
tests/test_app_integration.py en vez de volver a hacer "import app": ese
import solo puede pasar en un único archivo de toda la corrida. Ver el
docstring de tests/test_app_integration.py para el detalle.
"""
import db_finanzas as db

from test_app_integration import app_ctx, client, login  # noqa: F401 (fixtures reutilizadas)


def ocultar(usuario_id, vista):
    with db.conexion() as conn:
        db.ocultar_vista(conn, usuario_id, vista)


def mostrar(usuario_id, vista):
    with db.conexion() as conn:
        db.mostrar_vista(conn, usuario_id, vista)


# ---------------------------------------------------------------------------
# a. Caso central: "dashboard" oculta para un usuario no-admin bloquea las
# tres rutas y le quita el link del menú.
# ---------------------------------------------------------------------------

def test_usuario_no_admin_con_dashboard_oculto_pierde_el_link_y_las_tres_rutas(client, app_ctx):
    _, admin_id, user_id = app_ctx
    ocultar(user_id, "dashboard")

    login(client, "user_test", "clave-user-456")

    resp_get = client.get("/api/dashboard-data")
    # /api/... -> 403 JSON, no redirect (request.path.startswith("/api/"))
    assert resp_get.status_code == 403
    assert resp_get.get_json()["ok"] is False

    resp_home = client.get("/")
    assert resp_home.status_code == 302
    assert resp_home.headers["Location"].endswith("/mi-perfil")

    resp_vista = client.get("/vista/dashboard")
    assert resp_vista.status_code == 302
    assert resp_vista.headers["Location"].endswith("/mi-perfil")

    # el link del menú también desaparece (vistas_ocultas_viendo, ya que
    # para un no-admin viendo_id() == session["usuario_id"] siempre)
    resp_mi_perfil = client.get("/mi-perfil")
    assert resp_mi_perfil.status_code == 200
    assert b"Dashboard</span>" not in resp_mi_perfil.data


# ---------------------------------------------------------------------------
# b. Caso central de por_viendo=True: un admin "viendo" a un usuario
# restringido queda igual de bloqueado, sin importar que su propia cuenta
# no tenga restricción alguna.
# ---------------------------------------------------------------------------

def test_admin_viendo_a_usuario_con_dashboard_oculto_tambien_queda_bloqueado(client, app_ctx):
    _, admin_id, user_id = app_ctx
    ocultar(user_id, "dashboard")

    login(client, "admin_test", "clave-admin-123")
    cambio = client.post("/cambiar-vista", data={"usuario_id": user_id})
    assert cambio.status_code == 302

    # mientras viendo_id() == user_id, el admin también pierde el link...
    resp_mi_perfil = client.get("/mi-perfil")
    assert b"Dashboard</span>" not in resp_mi_perfil.data

    # ...y la ruta también lo bloquea a él, aunque su propia cuenta de
    # admin no tenga nada oculto
    resp_home = client.get("/")
    assert resp_home.status_code == 302
    assert resp_home.headers["Location"].endswith("/mi-perfil")

    resp_data = client.get("/api/dashboard-data")
    assert resp_data.status_code == 403

    # al volver a verse a sí mismo (sin restricción), recupera el acceso
    # de inmediato
    vuelta = client.post("/cambiar-vista", data={"usuario_id": admin_id})
    assert vuelta.status_code == 302

    resp_home_propio = client.get("/")
    assert resp_home_propio.status_code == 200


# ---------------------------------------------------------------------------
# c. Al revés: restricción sobre la cuenta del admin no lo afecta mientras
# está viendo a otro usuario sin restricciones -- viaja con la cuenta
# vista, no con quien inició sesión.
# ---------------------------------------------------------------------------

def test_admin_con_dashboard_oculto_a_si_mismo_puede_verlo_mientras_ve_a_otro_sin_restricciones(client, app_ctx):
    _, admin_id, user_id = app_ctx
    ocultar(admin_id, "dashboard")

    login(client, "admin_test", "clave-admin-123")

    # viendo su propia cuenta (restringida): bloqueado
    resp_propio = client.get("/")
    assert resp_propio.status_code == 302

    # cambia a ver a user_id (sin restricciones): accede sin problema
    cambio = client.post("/cambiar-vista", data={"usuario_id": user_id})
    assert cambio.status_code == 302

    resp_viendo_otro = client.get("/")
    assert resp_viendo_otro.status_code == 200

    resp_data = client.get("/api/dashboard-data")
    assert resp_data.status_code == 200


# ---------------------------------------------------------------------------
# d. Independencia entre "dashboard"/"perfil_financiero"/"insights" (por
# viendo_id()) y "correo_automatico" (por session["usuario_id"]).
# ---------------------------------------------------------------------------

def test_ocultar_dashboard_no_afecta_correo_automatico_y_viceversa(client, app_ctx):
    _, admin_id, user_id = app_ctx
    ocultar(user_id, "dashboard")

    login(client, "user_test", "clave-user-456")

    # dashboard bloqueado...
    assert client.get("/").status_code == 302
    # ...pero correo_automatico sigue accesible
    assert client.get("/configurar-correo").status_code == 200

    client.get("/logout")

    ocultar(admin_id, "correo_automatico")
    login(client, "admin_test", "clave-admin-123")

    # correo bloqueado...
    assert client.get("/configurar-correo").status_code == 302
    # ...pero el dashboard sigue accesible
    assert client.get("/").status_code == 200


# ---------------------------------------------------------------------------
# e/f/g. api_dashboard_data() con "perfil_financiero"/"insights" ocultas
# ---------------------------------------------------------------------------

def test_api_dashboard_data_con_perfil_financiero_oculto_da_200_con_perfil_null(client, app_ctx):
    _, admin_id, user_id = app_ctx
    ocultar(admin_id, "perfil_financiero")

    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data={
        "fecha": "2026-01-15", "tipo": "gasto", "monto": "10000",
        "descripcion": "Con perfil oculto", "categoria": "otros",
        "moneda": "COP", "entidad": "Test",
    })
    assert resp.get_json()["nuevos"] == 1

    resp = client.get("/api/dashboard-data")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["perfil"] is None
    assert "perfil_financiero" in body["vistas_ocultas"]
    assert len(body["movimientos"]) == 1
    assert body["ledger_deuda"] == []


def test_api_dashboard_data_con_insights_oculto_da_200_sin_afectar_perfil(client, app_ctx):
    _, admin_id, user_id = app_ctx
    ocultar(admin_id, "insights")

    login(client, "admin_test", "clave-admin-123")
    resp = client.get("/api/dashboard-data")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["perfil"] is not None
    assert "insights" in body["vistas_ocultas"]


def test_api_dashboard_data_sin_ninguna_restriccion_devuelve_vistas_ocultas_vacia(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")

    resp = client.get("/api/dashboard-data")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["vistas_ocultas"] == []
    assert body["perfil"] is not None


# ---------------------------------------------------------------------------
# h. Aislamiento entre usuarios: ocultar algo para A no afecta a B.
# ---------------------------------------------------------------------------

def test_ocultar_vistas_de_dashboard_para_un_usuario_no_afecta_a_otro(client, app_ctx):
    _, admin_id, user_id = app_ctx
    for vista in ("dashboard", "perfil_financiero", "insights"):
        ocultar(admin_id, vista)

    login(client, "user_test", "clave-user-456")

    resp_home = client.get("/")
    assert resp_home.status_code == 200
    assert b"Dashboard</span>" in resp_home.data

    resp_data = client.get("/api/dashboard-data")
    assert resp_data.status_code == 200
    body = resp_data.get_json()
    assert body["vistas_ocultas"] == []
    assert body["perfil"] is not None


# ---------------------------------------------------------------------------
# i/j. Panel /admin/vistas con el catálogo ampliado (4 vistas)
# ---------------------------------------------------------------------------

def test_admin_vistas_muestra_las_cuatro_vistas_en_la_tabla(client, app_ctx):
    login(client, "admin_test", "clave-admin-123")

    resp = client.get("/admin/vistas")

    assert resp.status_code == 200
    for label in ("Dashboard", "Tu perfil financiero", "Insights automáticos", "Correo automático"):
        assert label.encode() in resp.data


def test_toggle_funciona_igual_para_una_vista_nueva_como_perfil_financiero(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")

    resp = client.post("/api/admin/vistas/toggle", data={
        "usuario_id": str(user_id), "vista": "perfil_financiero", "visible": "0",
    })

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    with db.conexion() as conn:
        assert db.vistas_ocultas_de(conn, user_id) == {"perfil_financiero"}

    resp = client.post("/api/admin/vistas/toggle", data={
        "usuario_id": str(user_id), "vista": "perfil_financiero", "visible": "1",
    })

    assert resp.status_code == 200
    with db.conexion() as conn:
        assert db.vistas_ocultas_de(conn, user_id) == set()
