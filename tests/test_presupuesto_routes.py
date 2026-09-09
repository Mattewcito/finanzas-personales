"""
Pruebas de routes/presupuesto.py (blueprint "presupuesto": presupuesto por
3 baldes, mapeo categoría->balde, metas de ahorro -- 2026-09-08, ver
requisitos/2026-09-08_presupuesto-ahorro-deudas.md) y de la extensión de
routes/dashboard.py para este mismo feature (meta_ahorro_id opcional en
/api/registrar-movimiento, y las claves "presupuesto"/"categoria_balde"/
"metas_ahorro" en /api/dashboard-data).

IMPORTANTE -- reutiliza las fixtures app_ctx/client/login definidas en
tests/test_app_integration.py en vez de volver a hacer "import app": ese
import solo puede pasar en un único archivo de toda la corrida. Ver el
docstring de tests/test_app_integration.py para el detalle, y
tests/test_tarjetas_routes.py para el mismo patrón ya usado con otro
blueprint.

El contrato completo de 9 claves de /api/dashboard-data (incluidas
"presupuesto"/"categoria_balde"/"metas_ahorro" con sus defaults para una
cuenta nueva) ya lo cubre
test_app_integration.py::test_dashboard_data_con_sesion_devuelve_json_con_las_nueve_claves
-- no se duplica acá. Este archivo se enfoca en lo específico de
presupuesto/metas: CRUD, aislamiento por viendo_id(), validaciones, y que
/api/dashboard-data refleje datos reales ya configurados.
"""
import db_finanzas as db

from test_app_integration import app_ctx, client, login  # noqa: F401 (fixtures reutilizadas)


# ============================================================================
# GET /api/presupuesto
# ============================================================================

def test_api_obtener_presupuesto_redirige_a_login_sin_sesion(client):
    resp = client.get("/api/presupuesto")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_api_obtener_presupuesto_cuenta_sin_configurar_devuelve_default(client):
    login(client, "user_test", "clave-user-456")
    resp = client.get("/api/presupuesto")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["presupuesto"]["configurado"] is False
    assert body["presupuesto"]["pct_necesidades"] == 50.0
    assert body["presupuesto"]["pct_gustos"] == 30.0
    assert body["presupuesto"]["pct_ahorro_deudas"] == 20.0
    assert body["categoria_balde"] == {}
    assert body["baldes"] == db.BALDES_PRESUPUESTO


def test_api_obtener_presupuesto_incluye_mapeo_autopoblado_de_categorias_usadas(client):
    login(client, "admin_test", "clave-admin-123")
    client.post("/api/registrar-movimiento", data={
        "fecha": "2026-09-01", "tipo": "gasto", "monto": "20000",
        "descripcion": "Mercado", "categoria": "comida",
        "moneda": "COP", "entidad": "Exito",
    })

    resp = client.get("/api/presupuesto")
    body = resp.get_json()

    assert body["categoria_balde"]["comida"] == "necesidades"


def test_api_obtener_presupuesto_aisla_entre_usuarios(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.guardar_presupuesto(conn, admin_id, 70, 20, 10)
    conn.close()

    login(client, "user_test", "clave-user-456")
    resp = client.get("/api/presupuesto")
    body = resp.get_json()

    assert body["presupuesto"]["configurado"] is False
    assert body["presupuesto"]["pct_necesidades"] == 50.0


def test_api_obtener_presupuesto_admin_viendo_otro_perfil_ve_el_de_esa_cuenta(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.guardar_presupuesto(conn, user_id, 60, 25, 15)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})
    resp = client.get("/api/presupuesto")

    assert resp.get_json()["presupuesto"]["pct_necesidades"] == 60.0


# ============================================================================
# POST /api/presupuesto/guardar
# ============================================================================

def test_guardar_presupuesto_caso_feliz(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/presupuesto/guardar", data={
        "pct_necesidades": "50", "pct_gustos": "30", "pct_ahorro_deudas": "20",
    })

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["presupuesto"]["suma_pct"] == 100.0
    assert body["presupuesto"]["configurado"] is True


def test_guardar_presupuesto_no_bloquea_suma_distinta_de_100(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/presupuesto/guardar", data={
        "pct_necesidades": "45", "pct_gustos": "45", "pct_ahorro_deudas": "45",
    })

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["presupuesto"]["suma_pct"] == 135.0


def test_guardar_presupuesto_sin_un_porcentaje_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/presupuesto/guardar", data={
        "pct_necesidades": "50", "pct_gustos": "30",
    })  # falta pct_ahorro_deudas

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_guardar_presupuesto_con_porcentaje_negativo_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/presupuesto/guardar", data={
        "pct_necesidades": "-10", "pct_gustos": "60", "pct_ahorro_deudas": "50",
    })
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_guardar_presupuesto_con_porcentaje_no_numerico_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/presupuesto/guardar", data={
        "pct_necesidades": "no-es-numero", "pct_gustos": "30", "pct_ahorro_deudas": "20",
    })
    assert resp.status_code == 400


def test_guardar_presupuesto_se_guarda_para_viendo_id_no_para_la_sesion_del_admin(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})

    client.post("/api/presupuesto/guardar", data={
        "pct_necesidades": "40", "pct_gustos": "40", "pct_ahorro_deudas": "20",
    })

    conn = db.conectar()
    p_user = db.obtener_presupuesto(conn, user_id)
    p_admin = db.obtener_presupuesto(conn, admin_id)
    conn.close()

    assert p_user["configurado"] is True
    assert p_user["pct_necesidades"] == 40.0
    assert p_admin["configurado"] is False


# ============================================================================
# POST /api/presupuesto/categoria/asignar
# ============================================================================

def test_asignar_categoria_balde_caso_feliz(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/presupuesto/categoria/asignar", data={
        "categoria": "comida", "balde": "gustos",
    })

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["categoria_balde"]["comida"] == "gustos"


def test_asignar_categoria_balde_persiste_y_no_se_pisa_al_repedir_presupuesto(client):
    """La reasignación manual persiste incluso al volver a pedir
    /api/presupuesto (que autopobla lo que falte, pero nunca lo que ya
    estaba asignado explícitamente)."""
    login(client, "admin_test", "clave-admin-123")
    client.post("/api/registrar-movimiento", data={
        "fecha": "2026-09-01", "tipo": "gasto", "monto": "20000",
        "descripcion": "Mercado", "categoria": "comida",
        "moneda": "COP", "entidad": "Exito",
    })
    client.post("/api/presupuesto/categoria/asignar", data={"categoria": "comida", "balde": "gustos"})

    resp = client.get("/api/presupuesto")
    assert resp.get_json()["categoria_balde"]["comida"] == "gustos"


def test_asignar_categoria_balde_invalido_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/presupuesto/categoria/asignar", data={
        "categoria": "comida", "balde": "balde_inventado",
    })
    assert resp.status_code == 400


def test_asignar_categoria_sin_categoria_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/presupuesto/categoria/asignar", data={"balde": "gustos"})
    assert resp.status_code == 400


def test_asignar_categoria_balde_se_aplica_a_viendo_id_no_a_la_sesion_del_admin(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})
    client.post("/api/presupuesto/categoria/asignar", data={"categoria": "comida", "balde": "gustos"})

    conn = db.conectar()
    mapeo_user = db.obtener_mapeo_categorias(conn, user_id)
    mapeo_admin = db.obtener_mapeo_categorias(conn, admin_id)
    conn.close()

    assert mapeo_user.get("comida") == "gustos"
    assert "comida" not in mapeo_admin


# ============================================================================
# GET /api/metas-ahorro
# ============================================================================

def test_api_listar_metas_ahorro_redirige_a_login_sin_sesion(client):
    resp = client.get("/api/metas-ahorro")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_api_listar_metas_ahorro_usuario_sin_metas_devuelve_lista_vacia(client):
    login(client, "user_test", "clave-user-456")
    resp = client.get("/api/metas-ahorro")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["metas"] == []


def test_api_listar_metas_ahorro_aisla_entre_usuarios(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.crear_meta_ahorro(conn, admin_id, "Meta del admin", 100000)
    db.crear_meta_ahorro(conn, user_id, "Meta del usuario", 200000)
    conn.close()

    login(client, "user_test", "clave-user-456")
    resp = client.get("/api/metas-ahorro")

    nombres = [m["nombre"] for m in resp.get_json()["metas"]]
    assert nombres == ["Meta del usuario"]


def test_api_listar_metas_ahorro_admin_viendo_otro_perfil_ve_las_de_ese_perfil(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.crear_meta_ahorro(conn, admin_id, "Meta del admin", 100000)
    db.crear_meta_ahorro(conn, user_id, "Meta del usuario", 200000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})
    resp = client.get("/api/metas-ahorro")

    nombres = [m["nombre"] for m in resp.get_json()["metas"]]
    assert nombres == ["Meta del usuario"]


# ============================================================================
# POST /api/metas-ahorro/crear
# ============================================================================

def test_crear_meta_ahorro_caso_feliz(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/metas-ahorro/crear", data={
        "nombre": "Vacaciones", "monto_objetivo": "1000000", "fecha_objetivo": "2026-12-31",
    })

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert isinstance(body["id"], int)


def test_crear_meta_ahorro_sin_fecha_objetivo(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/metas-ahorro/crear", data={
        "nombre": "Fondo de emergencia", "monto_objetivo": "500000",
    })
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_crear_meta_ahorro_sin_nombre_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/metas-ahorro/crear", data={"monto_objetivo": "500000"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_crear_meta_ahorro_sin_monto_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/metas-ahorro/crear", data={"nombre": "Sin monto"})
    assert resp.status_code == 400


def test_crear_meta_ahorro_con_monto_cero_o_negativo_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    for monto in ("0", "-1000"):
        resp = client.post("/api/metas-ahorro/crear", data={"nombre": "Monto invalido", "monto_objetivo": monto})
        assert resp.status_code == 400
        assert resp.get_json()["ok"] is False


def test_crear_meta_ahorro_con_monto_no_numerico_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/metas-ahorro/crear", data={"nombre": "x", "monto_objetivo": "no-es-numero"})
    assert resp.status_code == 400


def test_crear_meta_ahorro_con_fecha_objetivo_invalida_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/metas-ahorro/crear", data={
        "nombre": "Meta", "monto_objetivo": "100000", "fecha_objetivo": "31-12-2026",
    })
    assert resp.status_code == 400


def test_crear_meta_ahorro_se_crea_para_viendo_id_no_para_la_sesion_del_admin(client, app_ctx):
    _, admin_id, user_id = app_ctx
    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})

    client.post("/api/metas-ahorro/crear", data={"nombre": "Meta para el usuario", "monto_objetivo": "100000"})

    conn = db.conectar()
    metas_user = db.obtener_metas_ahorro(conn, user_id)
    metas_admin = db.obtener_metas_ahorro(conn, admin_id)
    conn.close()

    assert [m["nombre"] for m in metas_user] == ["Meta para el usuario"]
    assert metas_admin == []


# ============================================================================
# POST /api/metas-ahorro/<id>/editar
# ============================================================================

def test_editar_meta_ahorro_caso_feliz(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, admin_id, "Original", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/metas-ahorro/{mid}/editar", data={"monto_objetivo": "300000"})

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    conn = db.conectar()
    assert db.obtener_meta_ahorro(conn, admin_id, mid)["monto_objetivo"] == 300000
    conn.close()


def test_editar_meta_ahorro_con_monto_y_fecha_a_la_vez_aplica_ambos(client, app_ctx):
    """Combinación de 2 parámetros a la vez -- ninguno debe ignorarse
    silenciosamente por venir junto al otro."""
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, admin_id, "Original", 100000, fecha_objetivo="2026-06-30")
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/metas-ahorro/{mid}/editar", data={
        "monto_objetivo": "300000", "fecha_objetivo": "2026-12-31",
    })

    assert resp.status_code == 200
    conn = db.conectar()
    meta = db.obtener_meta_ahorro(conn, admin_id, mid)
    conn.close()
    assert meta["monto_objetivo"] == 300000
    assert meta["fecha_objetivo"] == "2026-12-31"


def test_editar_meta_ahorro_de_otro_usuario_da_404(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, user_id, "Del usuario", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")  # admin viendo SU propio perfil, no el del usuario
    resp = client.post(f"/api/metas-ahorro/{mid}/editar", data={"monto_objetivo": "999999"})

    assert resp.status_code == 404
    conn = db.conectar()
    assert db.obtener_meta_ahorro(conn, user_id, mid)["monto_objetivo"] == 100000  # sin tocar
    conn.close()


def test_editar_meta_ahorro_inexistente_da_404(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/metas-ahorro/999999/editar", data={"monto_objetivo": "100000"})
    assert resp.status_code == 404


def test_editar_meta_ahorro_con_monto_no_positivo_da_400(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, admin_id, "Original", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/metas-ahorro/{mid}/editar", data={"monto_objetivo": "0"})
    assert resp.status_code == 400


def test_editar_meta_ahorro_con_fecha_objetivo_invalida_da_400(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, admin_id, "Original", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/metas-ahorro/{mid}/editar", data={"fecha_objetivo": "fecha-mala"})
    assert resp.status_code == 400


def test_editar_meta_ahorro_string_vacio_en_fecha_la_limpia(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, admin_id, "Original", 100000, fecha_objetivo="2026-12-31")
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/metas-ahorro/{mid}/editar", data={"fecha_objetivo": ""})

    assert resp.status_code == 200
    conn = db.conectar()
    assert db.obtener_meta_ahorro(conn, admin_id, mid)["fecha_objetivo"] is None
    conn.close()


# ============================================================================
# POST /api/metas-ahorro/<id>/archivar
# ============================================================================

def test_archivar_meta_ahorro_caso_feliz(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, admin_id, "Vieja", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/metas-ahorro/{mid}/archivar")

    assert resp.status_code == 200
    conn = db.conectar()
    assert db.obtener_meta_ahorro(conn, admin_id, mid)["activa"] is False
    conn.close()


def test_archivar_meta_ahorro_de_otro_usuario_da_404(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, user_id, "Del usuario", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/metas-ahorro/{mid}/archivar")

    assert resp.status_code == 404
    conn = db.conectar()
    assert db.obtener_meta_ahorro(conn, user_id, mid)["activa"] is True
    conn.close()


def test_archivar_meta_ahorro_inexistente_da_404(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/metas-ahorro/999999/archivar")
    assert resp.status_code == 404


# ============================================================================
# POST /api/metas-ahorro/<id>/borrar
# ============================================================================

def test_borrar_meta_ahorro_sin_aportes_la_elimina(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, admin_id, "Sin usar", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/metas-ahorro/{mid}/borrar")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    conn = db.conectar()
    assert db.obtener_meta_ahorro(conn, admin_id, mid) is None
    conn.close()


def test_borrar_meta_ahorro_con_aportes_asociados_da_400_y_no_la_borra(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, admin_id, "Con historial", 100000)
    db.insertar_movimientos(
        conn,
        [{"fecha": "2026-09-01", "tipo": "gasto", "categoria": "ahorro", "moneda": "COP",
          "monto": 50000, "descripcion": "Aporte a meta", "entidad": "Manual",
          "meta_ahorro_id": mid}],
        origen="app_manual", usuario_id=admin_id,
    )
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/metas-ahorro/{mid}/borrar")

    assert resp.status_code == 400
    assert "archiv" in resp.get_json()["error"].lower()
    conn = db.conectar()
    assert db.obtener_meta_ahorro(conn, admin_id, mid) is not None
    conn.close()


def test_borrar_meta_ahorro_de_otro_usuario_da_404(client, app_ctx):
    """Mismo criterio que editar/archivar: "no existe / es ajena" es 404,
    no 400 -- el 400 queda reservado para la falla de negocio real
    (meta propia con aportes asociados, ver test de arriba)."""
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, user_id, "Del usuario", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/metas-ahorro/{mid}/borrar")

    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False
    conn = db.conectar()
    assert db.obtener_meta_ahorro(conn, user_id, mid) is not None  # sigue existiendo, intacta
    conn.close()


def test_borrar_meta_ahorro_inexistente_da_404(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/metas-ahorro/999999/borrar")
    assert resp.status_code == 404


# ============================================================================
# /api/registrar-movimiento con meta_ahorro_id opcional (mismo criterio
# que tarjeta_id, ver tests/test_tarjetas_routes.py)
# ============================================================================

def datos_movimiento(**overrides):
    datos = {
        "fecha": "2026-09-01", "tipo": "gasto", "monto": "40000",
        "descripcion": "Aporte manual", "categoria": "ahorro",
        "moneda": "COP", "entidad": "Manual",
    }
    datos.update(overrides)
    return datos


def test_registrar_movimiento_con_meta_activa_propia_la_asocia(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, admin_id, "Vacaciones", 1000000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data=datos_movimiento(meta_ahorro_id=str(mid)))

    assert resp.status_code == 200
    assert resp.get_json()["nuevos"] == 1
    conn = db.conectar()
    meta = db.obtener_meta_ahorro(conn, admin_id, mid)
    conn.close()
    assert meta["ahorrado"] == 40000


def test_registrar_movimiento_sin_meta_ahorro_id_sigue_funcionando_igual_que_antes(client):
    """Retrocompatibilidad: meta_ahorro_id es opcional -- no mandarlo no
    debe romper nada."""
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data=datos_movimiento())
    assert resp.status_code == 200
    assert resp.get_json()["nuevos"] == 1


def test_registrar_movimiento_con_meta_ahorro_id_no_numerico_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data=datos_movimiento(meta_ahorro_id="no-es-un-id"))
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_registrar_movimiento_con_meta_ahorro_id_de_otro_usuario_da_400_y_no_inserta(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    mid_ajena = db.crear_meta_ahorro(conn, user_id, "Meta del usuario", 100000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data=datos_movimiento(meta_ahorro_id=str(mid_ajena)))

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    conn = db.conectar()
    assert db.obtener_movimientos(conn, usuario_id=admin_id) == []  # no se insertó nada
    conn.close()


def test_registrar_movimiento_con_meta_archivada_da_400(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, admin_id, "Archivada", 100000)
    db.archivar_meta_ahorro(conn, admin_id, mid)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data=datos_movimiento(meta_ahorro_id=str(mid)))

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_registrar_movimiento_con_meta_ahorro_id_inexistente_da_400(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/registrar-movimiento", data=datos_movimiento(meta_ahorro_id="999999"))
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# ============================================================================
# /api/dashboard-data: contenido real de presupuesto/categoria_balde/
# metas_ahorro y aislamiento (el contrato de las 9 claves y los defaults de
# una cuenta nueva ya se prueban en test_app_integration.py)
# ============================================================================

def test_dashboard_data_refleja_presupuesto_configurado_y_categoria_balde(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    db.guardar_presupuesto(conn, admin_id, 55, 25, 20)
    db.asignar_categoria_balde(conn, admin_id, "comida", "necesidades")
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.get("/api/dashboard-data")
    body = resp.get_json()

    assert body["presupuesto"]["configurado"] is True
    assert body["presupuesto"]["pct_necesidades"] == 55.0
    assert body["presupuesto"]["suma_pct"] == 100.0
    assert body["categoria_balde"]["comida"] == "necesidades"


def test_dashboard_data_refleja_avance_de_metas_de_ahorro(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    mid = db.crear_meta_ahorro(conn, admin_id, "Vacaciones", 1000000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    client.post("/api/registrar-movimiento", data=datos_movimiento(meta_ahorro_id=str(mid), monto="100000"))

    resp = client.get("/api/dashboard-data")
    meta = resp.get_json()["metas_ahorro"][0]

    assert meta["id"] == mid
    assert meta["ahorrado"] == 100000
    assert meta["restante"] == 900000
    assert meta["porcentaje"] == 10.0


def test_dashboard_data_aisla_presupuesto_y_metas_entre_usuarios(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.guardar_presupuesto(conn, admin_id, 60, 25, 15)
    db.crear_meta_ahorro(conn, admin_id, "Meta del admin", 500000)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp_admin = client.get("/api/dashboard-data")
    client.get("/logout")

    login(client, "user_test", "clave-user-456")
    resp_user = client.get("/api/dashboard-data")

    assert resp_admin.get_json()["presupuesto"]["configurado"] is True
    assert resp_user.get_json()["presupuesto"]["configurado"] is False
    assert [m["nombre"] for m in resp_admin.get_json()["metas_ahorro"]] == ["Meta del admin"]
    assert resp_user.get_json()["metas_ahorro"] == []


def test_dashboard_data_tras_cambiar_vista_muestra_presupuesto_de_la_cuenta_vista(client, app_ctx):
    """Mismo criterio que ya prueba test_app_integration.py para
    movimientos: /api/dashboard-data debe usar viendo_id(), no el
    usuario_id de sesión."""
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.guardar_presupuesto(conn, user_id, 45, 35, 20)
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})

    resp = client.get("/api/dashboard-data")
    body = resp.get_json()

    assert body["presupuesto"]["configurado"] is True
    assert body["presupuesto"]["pct_necesidades"] == 45.0
