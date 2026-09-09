"""
Pruebas de routes/tarjetas.py (blueprint "tarjetas": CRUD de tarjetas de
crédito con cupo, 2026-09-07, ver
requisitos/2026-09-07_tarjetas-credito-cupo.md) y de la extensión de
routes/dashboard.py para este mismo feature (tarjeta_id opcional en
/api/registrar-movimiento, tarjetas activas pasadas a /registrar, y la
clave "tarjetas" en /api/dashboard-data).

IMPORTANTE -- reutiliza las fixtures app_ctx/client/login definidas en
tests/test_app_integration.py en vez de volver a hacer "import app": ese
import solo puede pasar en un único archivo de toda la corrida. Ver el
docstring de tests/test_app_integration.py para el detalle, y
tests/test_correo_routes.py para el mismo patrón ya usado con otro
blueprint.

El contrato completo de 6 claves de /api/dashboard-data (incluida
"tarjetas") ya lo cubre
test_app_integration.py::test_dashboard_data_con_sesion_devuelve_json_con_las_seis_claves
-- no se duplica acá. Este archivo se enfoca en lo específico de
tarjetas: CRUD, aislamiento por viendo_id(), y la validación de
tarjeta_id en /api/registrar-movimiento.
"""
import db_finanzas as db
from routes.tarjetas import _parsear_cupo, _validar_ultimos4

from test_app_integration import app_ctx, client, login  # noqa: F401 (fixtures reutilizadas)


# ============================================================================
# Helpers puros de routes/tarjetas.py (sin necesidad de contexto Flask)
# ============================================================================

def test_parsear_cupo_valor_ausente_o_vacio_es_valido_none_none():
    """None/'' significa 'no se mandó este campo' -- válido en edición
    parcial (cada endpoint decide si además es obligatorio, ver
    api_crear_tarjeta)."""
    assert _parsear_cupo(None) == (None, None)
    assert _parsear_cupo("") == (None, None)
    assert _parsear_cupo("   ") == (None, None)


def test_parsear_cupo_no_numerico_da_error():
    cupo, error = _parsear_cupo("no-es-un-numero")
    assert cupo is None
    assert error is not None


def test_parsear_cupo_cero_o_negativo_da_error():
    for crudo in ("0", "-1", "-500000"):
        cupo, error = _parsear_cupo(crudo)
        assert cupo is None
        assert error is not None


def test_parsear_cupo_valido_devuelve_float_sin_error():
    assert _parsear_cupo("500000") == (500000.0, None)


def test_validar_ultimos4_ausente_o_vacio_es_valido():
    assert _validar_ultimos4(None) is None
    assert _validar_ultimos4("") is None
    assert _validar_ultimos4("   ") is None


def test_validar_ultimos4_valido_de_4_digitos():
    assert _validar_ultimos4("2011") is None


def test_validar_ultimos4_con_letras_o_longitud_distinta_da_error():
    for crudo in ("12a4", "123", "12345", "abcd"):
        assert _validar_ultimos4(crudo) is not None


# ============================================================================
# GET /api/tarjetas
# ============================================================================

def test_api_listar_tarjetas_redirige_a_login_sin_sesion(client):
    resp = client.get("/api/tarjetas")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_api_listar_tarjetas_usuario_sin_tarjetas_devuelve_lista_vacia(client):
    login(client, "user_test", "clave-user-456")
    resp = client.get("/api/tarjetas")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["tarjetas"] == []


def test_api_listar_tarjetas_aisla_entre_usuarios(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.crear_tarjeta(conn, admin_id, "Tarjeta del admin", 100000)
    db.crear_tarjeta(conn, user_id, "Tarjeta del usuario", 200000)
    conn.close()

    login(client, "user_test", "clave-user-456")
    resp = client.get("/api/tarjetas")

    nombres = [t["nombre"] for t in resp.get_json()["tarjetas"]]
    assert nombres == ["Tarjeta del usuario"]


def test_api_listar_tarjetas_admin_viendo_otro_perfil_ve_las_tarjetas_de_ese_perfil(client, app_ctx):
    """Un admin viendo el perfil de otro usuario (POST /cambiar-vista)
    gestiona LAS TARJETAS DE ESA CUENTA, no las propias -- mismo criterio
    que "Registrar movimiento" (ver docstring de routes/tarjetas.py)."""
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.crear_tarjeta(conn, admin_id, "Tarjeta del admin", 100000)
    db.crear_tarjeta(conn, user_id, "Tarjeta del usuario", 200000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})

    resp = client.get("/api/tarjetas")

    nombres = [t["nombre"] for t in resp.get_json()["tarjetas"]]
    assert nombres == ["Tarjeta del usuario"]


# ============================================================================
# POST /api/tarjetas/crear
# ============================================================================

def test_crear_tarjeta_caso_feliz_solo_con_campos_obligatorios(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/tarjetas/crear", data={"nombre": "Visa simple", "cupo_total": "500000"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert isinstance(body["id"], int)


def test_crear_tarjeta_caso_feliz_con_todos_los_campos(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/tarjetas/crear", data={
        "nombre": "Bancolombia Visa Gold", "entidad": "Bancolombia",
        "cupo_total": "5000000", "ultimos4": "2011",
    })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_crear_tarjeta_sin_nombre_da_error_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/tarjetas/crear", data={"cupo_total": "500000"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_crear_tarjeta_sin_cupo_da_error_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/tarjetas/crear", data={"nombre": "Sin cupo"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_crear_tarjeta_con_cupo_cero_o_negativo_da_error_400(client):
    login(client, "admin_test", "clave-admin-123")
    for cupo in ("0", "-1000"):
        resp = client.post("/api/tarjetas/crear", data={"nombre": "Cupo invalido", "cupo_total": cupo})
        assert resp.status_code == 400
        assert resp.get_json()["ok"] is False


def test_crear_tarjeta_con_cupo_no_numerico_da_error_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/tarjetas/crear", data={"nombre": "x", "cupo_total": "no-es-numero"})
    assert resp.status_code == 400


def test_crear_tarjeta_con_ultimos4_invalido_da_error_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/tarjetas/crear", data={
        "nombre": "x", "cupo_total": "100000", "ultimos4": "12a4",
    })
    assert resp.status_code == 400


def test_crear_tarjeta_se_crea_para_viendo_id_no_para_la_sesion_del_admin(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})

    client.post("/api/tarjetas/crear", data={"nombre": "Tarjeta para el usuario", "cupo_total": "100000"})

    conn = db.conectar()
    tarjetas_user = db.obtener_tarjetas(conn, user_id)
    tarjetas_admin = db.obtener_tarjetas(conn, admin_id)
    conn.close()

    assert [t["nombre"] for t in tarjetas_user] == ["Tarjeta para el usuario"]
    assert tarjetas_admin == []


# ============================================================================
# POST /api/tarjetas/<id>/editar
# ============================================================================

def test_editar_tarjeta_caso_feliz(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, admin_id, "Original", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/tarjetas/{tid}/editar", data={"cupo_total": "300000"})

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    conn = db.conectar()
    assert db.obtener_tarjeta(conn, admin_id, tid)["cupo_total"] == 300000
    conn.close()


def test_editar_tarjeta_de_otro_usuario_da_404(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, user_id, "Del usuario", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")  # admin viendo SU propio perfil, no el del usuario
    resp = client.post(f"/api/tarjetas/{tid}/editar", data={"cupo_total": "999999"})

    assert resp.status_code == 404
    conn = db.conectar()
    assert db.obtener_tarjeta(conn, user_id, tid)["cupo_total"] == 100000  # sin tocar
    conn.close()


def test_editar_tarjeta_inexistente_da_404(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/tarjetas/999999/editar", data={"cupo_total": "100000"})
    assert resp.status_code == 404


def test_editar_tarjeta_con_cupo_no_positivo_da_400(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, admin_id, "Original", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/tarjetas/{tid}/editar", data={"cupo_total": "0"})

    assert resp.status_code == 400


def test_editar_tarjeta_con_ultimos4_invalido_da_400(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, admin_id, "Original", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/tarjetas/{tid}/editar", data={"ultimos4": "abc"})

    assert resp.status_code == 400


# ============================================================================
# POST /api/tarjetas/<id>/archivar
# ============================================================================

def test_archivar_tarjeta_caso_feliz(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, admin_id, "Vieja", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/tarjetas/{tid}/archivar")

    assert resp.status_code == 200
    conn = db.conectar()
    assert db.obtener_tarjeta(conn, admin_id, tid)["activa"] is False
    conn.close()


def test_archivar_tarjeta_de_otro_usuario_da_404(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, user_id, "Del usuario", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/tarjetas/{tid}/archivar")

    assert resp.status_code == 404
    conn = db.conectar()
    assert db.obtener_tarjeta(conn, user_id, tid)["activa"] is True
    conn.close()


def test_archivar_tarjeta_inexistente_da_404(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/tarjetas/999999/archivar")
    assert resp.status_code == 404


# ============================================================================
# POST /api/tarjetas/<id>/borrar
# ============================================================================

def test_borrar_tarjeta_sin_movimientos_la_elimina(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, admin_id, "Sin usar", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/tarjetas/{tid}/borrar")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    conn = db.conectar()
    assert db.obtener_tarjeta(conn, admin_id, tid) is None
    conn.close()


def test_borrar_tarjeta_con_movimientos_asociados_da_400_y_no_la_borra(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, admin_id, "Con historial", 100000)
    db.insertar_movimientos(
        conn,
        [{"fecha": "2026-09-01", "tipo": "gasto", "categoria": "compras", "moneda": "COP",
          "monto": 40000, "descripcion": "Compra con T.Cred *1111", "entidad": "Bancolombia",
          "tarjeta_id": tid}],
        origen="app_manual", usuario_id=admin_id,
    )
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/tarjetas/{tid}/borrar")

    assert resp.status_code == 400
    assert "archiv" in resp.get_json()["error"].lower()
    conn = db.conectar()
    assert db.obtener_tarjeta(conn, admin_id, tid) is not None
    conn.close()


def test_borrar_tarjeta_de_otro_usuario_da_404(client, app_ctx):
    """Mismo criterio que editar/archivar: "no existe / es ajena" es 404,
    no 400 -- el 400 queda reservado para la falla de negocio real
    (tarjeta propia con movimientos asociados, ver test de arriba)."""
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, user_id, "Del usuario", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/tarjetas/{tid}/borrar")

    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False
    conn = db.conectar()
    assert db.obtener_tarjeta(conn, user_id, tid) is not None  # sigue existiendo, intacta
    conn.close()


def test_borrar_tarjeta_inexistente_da_404(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/tarjetas/999999/borrar")
    assert resp.status_code == 404


# ============================================================================
# /api/registrar-movimiento con tarjeta_id opcional
# ============================================================================

def datos_movimiento(**overrides):
    datos = {
        "fecha": "2026-09-01", "tipo": "gasto", "monto": "40000",
        "descripcion": "Compra con T.Cred *1111", "categoria": "compras",
        "moneda": "COP", "entidad": "Bancolombia",
    }
    datos.update(overrides)
    return datos


def test_registrar_movimiento_con_tarjeta_activa_propia_la_asocia(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, admin_id, "Visa", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data=datos_movimiento(tarjeta_id=str(tid)))

    assert resp.status_code == 200
    assert resp.get_json()["nuevos"] == 1
    conn = db.conectar()
    fila = db.obtener_movimientos(conn, usuario_id=admin_id)[0]
    tarjeta_id_guardado = conn.execute(
        "SELECT tarjeta_id FROM movimientos WHERE id = ?", (fila["id"],)
    ).fetchone()["tarjeta_id"]
    conn.close()
    assert tarjeta_id_guardado == tid


def test_registrar_movimiento_sin_tarjeta_id_sigue_funcionando_igual_que_antes(client):
    """Retrocompatibilidad: tarjeta_id es opcional -- no mandarlo no debe
    romper nada."""
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data=datos_movimiento())
    assert resp.status_code == 200
    assert resp.get_json()["nuevos"] == 1


def test_registrar_movimiento_con_tarjeta_id_no_numerico_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data=datos_movimiento(tarjeta_id="no-es-un-id"))
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_registrar_movimiento_con_tarjeta_id_de_otro_usuario_da_400_y_no_inserta_con_esa_tarjeta(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    tid_ajena = db.crear_tarjeta(conn, user_id, "Tarjeta del usuario", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data=datos_movimiento(tarjeta_id=str(tid_ajena)))

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    conn = db.conectar()
    assert db.obtener_movimientos(conn, usuario_id=admin_id) == []  # no se insertó nada
    conn.close()


def test_registrar_movimiento_con_tarjeta_archivada_da_400(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, admin_id, "Archivada", 100000)
    db.archivar_tarjeta(conn, admin_id, tid)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data=datos_movimiento(tarjeta_id=str(tid)))

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_registrar_movimiento_con_tarjeta_id_inexistente_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data=datos_movimiento(tarjeta_id="999999"))
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# ============================================================================
# GET /tarjetas (vista_tarjetas): página de gestión (alta/edición/archivado/
# borrado) -- smoke test y aislamiento del datalist de entidades vía
# viendo_id() (agregada por frontend-dataviz en routes/tarjetas.py; revisada
# acá como cualquier ruta Flask nueva, ver requisitos/2026-09-07_tarjetas-
# credito-cupo.md). El listado de tarjetas en sí se pide por AJAX a
# GET /api/tarjetas, ya cubierto arriba -- esta sección cubre solo lo propio
# de esta ruta: requiere sesión, renderiza 200, y el único dato propio que
# arma el handler (entidades para el datalist) respeta viendo_id().
# ============================================================================

def test_vista_tarjetas_redirige_a_login_sin_sesion(client):
    resp = client.get("/tarjetas")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_vista_tarjetas_con_sesion_da_200(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.get("/tarjetas")
    assert resp.status_code == 200


def test_vista_tarjetas_usuario_sin_movimientos_da_200_sin_reventar(client):
    """Estado vacío: 0 movimientos (por lo tanto 0 entidades para el
    datalist) no debe romper el render -- mismo tipo de caso borde que ya
    se prueba para /registrar."""
    login(client, "user_test", "clave-user-456")
    resp = client.get("/tarjetas")
    assert resp.status_code == 200


def test_vista_tarjetas_admin_viendo_otro_perfil_ve_entidades_de_esa_cuenta(client, app_ctx):
    """El datalist de entidades de /tarjetas usa viendo_id(), igual que
    /registrar y que /api/tarjetas -- un admin viendo el perfil de otro
    usuario ve las entidades de ESA cuenta (para el autocompletado al dar de
    alta una tarjeta), no las propias. Mismo criterio de aislamiento que
    test_api_listar_tarjetas_admin_viendo_otro_perfil_ve_las_tarjetas_de_ese_perfil."""
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")
    client.post("/api/registrar-movimiento", data=datos_movimiento(entidad="EntidadDelAdmin"))

    client.post("/cambiar-vista", data={"usuario_id": user_id})
    client.post("/api/registrar-movimiento", data=datos_movimiento(entidad="EntidadDelUsuario"))

    resp = client.get("/tarjetas")

    assert b"EntidadDelUsuario" in resp.data
    assert b"EntidadDelAdmin" not in resp.data


# ============================================================================
# GET /registrar: no debe reventar con o sin tarjetas activas del usuario
# ============================================================================

def test_get_registrar_con_sesion_da_200_sin_tarjetas(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.get("/registrar")
    assert resp.status_code == 200


def test_get_registrar_con_sesion_da_200_con_tarjetas_activas_y_archivadas(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    tid_activa = db.crear_tarjeta(conn, admin_id, "Activa", 100000)
    tid_archivada = db.crear_tarjeta(conn, admin_id, "Archivada", 100000)
    db.archivar_tarjeta(conn, admin_id, tid_archivada)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.get("/registrar")

    assert resp.status_code == 200  # smoke test: no debe reventar con una mezcla de activas/archivadas
    conn = db.conectar()
    activas = db.obtener_tarjetas(conn, admin_id, solo_activas=True)
    conn.close()
    assert [t["id"] for t in activas] == [tid_activa]  # la archivada no se ofrece como destino de movimientos nuevos


# ============================================================================
# /api/dashboard-data: aislamiento específico de la clave "tarjetas"
# (el contrato completo de 6 claves ya se prueba en test_app_integration.py)
# ============================================================================

def test_dashboard_data_aisla_tarjetas_entre_usuarios(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.crear_tarjeta(conn, admin_id, "Tarjeta del admin", 500000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp_admin = client.get("/api/dashboard-data")
    client.get("/logout")

    login(client, "user_test", "clave-user-456")
    resp_user = client.get("/api/dashboard-data")

    nombres_admin = [t["nombre"] for t in resp_admin.get_json()["tarjetas"]["activas"]]
    nombres_user = [t["nombre"] for t in resp_user.get_json()["tarjetas"]["activas"]]

    assert nombres_admin == ["Tarjeta del admin"]
    assert nombres_user == []


def test_dashboard_data_tarjetas_con_deuda_y_cupo_refleja_los_campos_esperados(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, admin_id, "Visa", 200000, ultimos4="2011")
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    client.post("/api/registrar-movimiento", data=datos_movimiento(
        descripcion="Compra con T.Cred *2011", monto="50000", tarjeta_id=str(tid),
    ))

    resp = client.get("/api/dashboard-data")
    tarjeta = resp.get_json()["tarjetas"]["activas"][0]

    assert tarjeta["id"] == tid
    assert tarjeta["cupo_total"] == 200000
    assert tarjeta["deuda_actual"] == 50000
    assert tarjeta["cupo_disponible"] == 150000
    assert tarjeta["porcentaje_uso"] == 25.0
