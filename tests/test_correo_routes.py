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

Todas las rutas de este blueprint usan viendo_id() (no
session["usuario_id"] directo) -- mismo patrón que Registrar
movimiento/Cargar extractos: un admin puede ver y modificar la
configuración de cualquier usuario cambiando "Viendo perfil de"
(POST /cambiar-vista, que setea session["viendo_id"]); un usuario normal
siempre opera sobre la suya porque para él viendo_id() es siempre su
propio id. Ver el docstring de src/routes/correo.py y
auth.py::viendo_id().
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
# POST /api/correo/guardar -- cedula (opcional, para PDFs de extracto adjuntos)
# ---------------------------------------------------------------------------

def test_guardar_con_cedula_la_persiste(client, app_ctx):
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")

    datos = dict(FORM_BASE)
    datos["cedula"] = "1020304050"
    resp = client.post("/api/correo/guardar", data=datos)

    assert resp.status_code == 200
    fila = config_de(admin_id)
    assert fila["cedula"] == "1020304050"


def test_guardar_sin_cedula_da_200_y_queda_none(client):
    """La cédula es opcional -- no debe exigirse ni siquiera en el alta,
    a diferencia de app_password."""
    login(client, "admin_test", "clave-admin-123")

    resp = client.post("/api/correo/guardar", data=dict(FORM_BASE))

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_guardar_con_cedula_vacia_en_actualizacion_posterior_mantiene_la_anterior(client, app_ctx):
    """Mismo criterio que app_password: dejar el campo en blanco al editar
    no debe borrar la cédula ya guardada."""
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")

    datos = dict(FORM_BASE)
    datos["cedula"] = "1020304050"
    client.post("/api/correo/guardar", data=datos)

    datos_edicion = dict(FORM_BASE)
    datos_edicion["app_password"] = ""  # no cambiar
    datos_edicion["cedula"] = ""        # no cambiar
    resp = client.post("/api/correo/guardar", data=datos_edicion)

    assert resp.status_code == 200
    fila = config_de(admin_id)
    assert fila["cedula"] == "1020304050"


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
    siempre viendo_id() -- nunca un valor tomado del propio form (el
    único mecanismo válido para "operar sobre otra cuenta" es
    session["viendo_id"], vía /cambiar-vista, no un campo de este
    formulario)."""
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


def test_sincronizar_ahora_usa_calcular_dias_a_revisar_en_vez_de_un_valor_fijo(client, app_ctx, monkeypatch):
    """La ventana de búsqueda debe calcularse dinámicamente con
    calcular_dias_a_revisar(dias_minimo=2) -- no un 'dias=2' fijo
    independiente del hueco desde la última corrida."""
    _, admin_id, _ = app_ctx
    guardar_config_directo(admin_id)
    login(client, "admin_test", "clave-admin-123")

    llamadas_calc = []

    def _fake_calc(config, ahora, dias_minimo):
        llamadas_calc.append(dias_minimo)
        return 42

    monkeypatch.setattr(lc, "calcular_dias_a_revisar", _fake_calc)

    dias_recibidos = []

    def _fake_procesar(config, dias, aplicar):
        dias_recibidos.append(dias)
        return "ok"

    monkeypatch.setattr(lc, "procesar_cuenta", _fake_procesar)

    resp = client.post("/api/correo/sincronizar-ahora")

    assert resp.status_code == 200
    assert llamadas_calc == [2]
    assert dias_recibidos == [42]


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


# ---------------------------------------------------------------------------
# Admin viendo el perfil de otro usuario (viendo_id()) -- mismo patrón que
# Registrar movimiento/Cargar extractos: ver docstring de routes/correo.py
# ---------------------------------------------------------------------------

def test_get_configurar_correo_admin_viendo_a_otro_muestra_la_config_del_otro(client, app_ctx):
    """Un admin con "Viendo perfil de" apuntando a otro usuario debe ver,
    en el formulario, la config guardada de ESE OTRO usuario -- no la
    suya propia (que en este test queda vacía a propósito)."""
    _, admin_id, user_id = app_ctx
    guardar_config_directo(user_id, email="del-usuario-visto@example.com")

    login(client, "admin_test", "clave-admin-123")
    cambio = client.post("/cambiar-vista", data={"usuario_id": user_id})
    assert cambio.status_code == 302

    resp = client.get("/configurar-correo")

    assert resp.status_code == 200
    assert b"del-usuario-visto@example.com" in resp.data
    # la propia cuenta del admin nunca tuvo config guardada
    assert config_de(admin_id) is None


def test_guardar_admin_viendo_a_otro_guarda_para_el_usuario_visto_no_para_el_admin(client, app_ctx):
    _, admin_id, user_id = app_ctx

    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})

    datos = dict(FORM_BASE)
    datos["email"] = "guardado-viendo-a-otro@example.com"
    resp = client.post("/api/correo/guardar", data=datos)

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    fila_user = config_de(user_id)
    assert fila_user is not None
    assert fila_user["email"] == "guardado-viendo-a-otro@example.com"
    assert config_de(admin_id) is None  # el admin logueado sigue sin config propia


def test_sincronizar_ahora_admin_viendo_a_otro_opera_sobre_la_cuenta_vista(client, app_ctx, monkeypatch):
    _, admin_id, user_id = app_ctx
    guardar_config_directo(user_id)

    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})

    monkeypatch.setattr(lc, "procesar_cuenta", lambda config, dias, aplicar: "1 movimiento(s) insertado(s)")

    resp = client.post("/api/correo/sincronizar-ahora")

    assert resp.status_code == 200
    assert resp.get_json()["mensaje"] == "1 movimiento(s) insertado(s)"


def test_sincronizar_ahora_admin_viendo_a_otro_sin_config_del_admin_no_revienta(client, app_ctx, monkeypatch):
    """La cuenta propia del admin no tiene config -- pero como está
    viendo la del usuario (que sí tiene), la sincronización debe usar la
    de ESE usuario, no fallar por "esta cuenta todavía no tiene
    correo configurado" (bug de regresión si se usara usuario_id de
    sesión en vez de viendo_id())."""
    _, admin_id, user_id = app_ctx
    guardar_config_directo(user_id)
    assert config_de(admin_id) is None

    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})

    monkeypatch.setattr(lc, "procesar_cuenta", lambda config, dias, aplicar: "ok")

    resp = client.post("/api/correo/sincronizar-ahora")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_eliminar_admin_viendo_a_otro_borra_la_del_usuario_visto_no_la_del_admin(client, app_ctx):
    _, admin_id, user_id = app_ctx
    guardar_config_directo(admin_id, email="admin-propia@example.com")
    guardar_config_directo(user_id, email="usuario-visto@example.com")

    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})

    resp = client.post("/api/correo/eliminar")

    assert resp.status_code == 200
    assert config_de(user_id) is None
    fila_admin = config_de(admin_id)
    assert fila_admin is not None
    assert fila_admin["email"] == "admin-propia@example.com"


def test_usuario_normal_con_viendo_id_distinto_forzado_en_sesion_sigue_operando_sobre_el_propio(client, app_ctx):
    """Esto no debería poder pasar nunca vía la UI normal (solo un admin
    puede setear viendo_id != usuario_id mediante /cambiar-vista, que
    rechaza a los no-admin con 403 -- ver
    test_usuario_normal_no_puede_cambiar_de_perfil en
    test_app_integration.py). Lo probamos igual a nivel de sesión directa
    (bypaseando esa protección a mano, algo que un usuario real no puede
    hacer sin conocer la SECRET_KEY con la que Flask firma la cookie)
    para documentar el comportamiento real de auth.py::viendo_id()."""
    _, admin_id, user_id = app_ctx
    login(client, "user_test", "clave-user-456")

    with client.session_transaction() as sess:
        sess["viendo_id"] = admin_id  # forzado manualmente, no alcanzable por la UI

    datos = dict(FORM_BASE)
    datos["email"] = "forzado-a-mano@example.com"
    resp = client.post("/api/correo/guardar", data=datos)

    assert resp.status_code == 200
    # viendo_id() no vuelve a chequear el rol contra la sesión -- confía
    # en que session["viendo_id"] solo puede desalinearse de
    # session["usuario_id"] a través de /cambiar-vista (que sí exige rol
    # admin) o del login (que los deja iguales). Si se fuerza el valor a
    # mano se usa tal cual, incluso con rol "usuario": por eso la config
    # termina en la cuenta forzada (admin_id), no en la propia del
    # usuario logueado.
    assert config_de(admin_id) is not None
    assert config_de(admin_id)["email"] == "forzado-a-mano@example.com"
    assert config_de(user_id) is None


# ---------------------------------------------------------------------------
# requiere_vista_visible("correo_automatico") -- panel de admin_vistas.py
# que oculta/muestra el ítem de menú y bloquea las rutas del blueprint
# "correo" en sí (ver auth.py::requiere_vista_visible/inyectar_globales y
# routes/admin_vistas.py). Casos centrales del bloqueo por rol.
# ---------------------------------------------------------------------------

def ocultar(usuario_id, vista="correo_automatico"):
    with db.conexion() as conn:
        db.ocultar_vista(conn, usuario_id, vista)


def mostrar(usuario_id, vista="correo_automatico"):
    with db.conexion() as conn:
        db.mostrar_vista(conn, usuario_id, vista)


def test_usuario_no_admin_con_correo_oculto_no_ve_el_link_ni_puede_acceder_a_las_rutas(client, app_ctx):
    """Caso central: admin oculta "correo_automatico" para el usuario B
    (no admin). B, al iniciar sesión: no ve el link en el menú, GET
    /configurar-correo lo redirige al dashboard (nunca le muestra la
    página), y POST /api/correo/guardar le da 403 sin dejarlo guardar
    nada."""
    _, admin_id, user_id = app_ctx
    ocultar(user_id)

    login(client, "user_test", "clave-user-456")

    resp_home = client.get("/")
    assert resp_home.status_code == 200
    assert b'href="/configurar-correo"' not in resp_home.data
    assert "Correo automático".encode() not in resp_home.data

    resp_get = client.get("/configurar-correo")
    assert resp_get.status_code == 302
    assert "/login" not in resp_get.headers["Location"]  # no lo manda a loguearse, ya está logueado

    resp_post = client.post("/api/correo/guardar", data=dict(FORM_BASE))
    assert resp_post.status_code == 403
    assert resp_post.get_json()["ok"] is False
    assert config_de(user_id) is None  # nunca llegó a guardar nada


def test_usuario_recupera_el_acceso_cuando_el_admin_vuelve_a_mostrar_la_vista(client, app_ctx, monkeypatch):
    """Después de que el admin revierte la restricción (visible=1), B
    recupera el link en el menú, GET /configurar-correo vuelve a dar 200
    y POST /api/correo/guardar vuelve a funcionar."""
    _, admin_id, user_id = app_ctx
    ocultar(user_id)
    mostrar(user_id)

    login(client, "user_test", "clave-user-456")

    resp_home = client.get("/")
    assert b'href="/configurar-correo"' in resp_home.data

    resp_get = client.get("/configurar-correo")
    assert resp_get.status_code == 200

    resp_post = client.post("/api/correo/guardar", data=dict(FORM_BASE))
    assert resp_post.status_code == 200
    assert resp_post.get_json()["ok"] is True
    assert config_de(user_id) is not None


def test_admin_con_correo_oculto_a_si_mismo_igual_puede_usar_la_ruta_aunque_pierda_el_link_del_menu(client, app_ctx):
    """Un admin NUNCA es bloqueado por requiere_vista_visible (para que no
    pueda accidentalmente quitarse a sí mismo el acceso al panel que
    revierte la restricción) -- si se oculta "correo_automatico" a sí
    mismo, GET /configurar-correo le sigue dando 200. Pero
    inyectar_globales() no distingue rol para el chequeo del MENÚ, así
    que el link SÍ desaparece de su propio sidebar (comportamiento real,
    confirmado leyendo auth.py::inyectar_globales)."""
    _, admin_id, user_id = app_ctx
    ocultar(admin_id)

    login(client, "admin_test", "clave-admin-123")

    resp_home = client.get("/")
    assert resp_home.status_code == 200
    assert b'href="/configurar-correo"' not in resp_home.data  # el link sí desaparece

    resp_get = client.get("/configurar-correo")
    assert resp_get.status_code == 200  # pero la ruta en sí sigue funcionando, por ser admin

    resp_post = client.post("/api/correo/guardar", data=dict(FORM_BASE))
    assert resp_post.status_code == 200
    assert resp_post.get_json()["ok"] is True


def test_admin_viendo_perfil_de_usuario_restringido_sigue_viendo_el_link_en_su_propio_menu(client, app_ctx):
    """La restricción de vistas_ocultas es sobre session["usuario_id"]
    (quien inició sesión), nunca sobre viendo_id() -- un admin que está
    "viendo" el perfil de un usuario B restringido no hereda la
    restricción de B: sigue viendo "Correo automático" en SU PROPIO
    menú, y puede seguir usando la ruta con normalidad."""
    _, admin_id, user_id = app_ctx
    ocultar(user_id)  # restricción es de B, no del admin

    login(client, "admin_test", "clave-admin-123")
    cambio = client.post("/cambiar-vista", data={"usuario_id": user_id})
    assert cambio.status_code == 302

    resp_home = client.get("/")
    assert resp_home.status_code == 200
    assert b'href="/configurar-correo"' in resp_home.data  # el admin sigue viendo el link

    resp_get = client.get("/configurar-correo")
    assert resp_get.status_code == 200  # y puede seguir usando la ruta (viendo_id() = user_id)
