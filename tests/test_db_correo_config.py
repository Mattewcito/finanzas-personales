"""
Pruebas de las funciones de db_finanzas.py relacionadas con la tabla
`correo_config` (configuración de lectura de correo por usuario, Fase 1,
ver leer_correo.py y routes/correo.py):

  - obtener_correo_config
  - listar_correo_configs_activos
  - guardar_correo_config (upsert, incluida la semántica de
    app_password=None/"" = "no cambiar")
  - actualizar_estado_correo
  - eliminar_correo_config

IMPORTANTE -- aislamiento de filesystem: BD aislada en tmp_path (mismo
patrón que dashboard_ctx en tests/test_actualizar_dashboard.py). Nunca
toca data/finanzas.db real.

Este archivo NO hace "import app" (reservado a tests/test_app_integration.py).
"""
import pytest

import db_finanzas as db


# ----------------------------- Fixtures y helpers -----------------------------

@pytest.fixture
def conn(tmp_path, monkeypatch):
    """BD aislada en tmp_path, con el esquema ya creado."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "DB_PATH", data_dir / "finanzas.db")
    monkeypatch.setattr(db, "XLSX_PATH", data_dir / "finanzas_personales.xlsx")

    c = db.conectar()
    db.crear_esquema(c)
    yield c
    c.close()


def crear_usuario(conn, username):
    return db.crear_usuario(conn, username, "clave-123", "usuario", username)


# ----------------------------- guardar_correo_config: alta -----------------------------

def test_guardar_correo_config_crea_fila_nueva_con_todos_los_campos(conn):
    """Caso feliz: primera vez que un usuario configura su correo, con
    contraseña incluida (obligatoria)."""
    uid = crear_usuario(conn, "maria")

    db.guardar_correo_config(
        conn, uid,
        email="maria@example.com", app_password="clave-app-123",
        imap_host="imap.gmail.com", imap_port=993,
        frecuencia_tipo="intervalo", frecuencia_minutos=45,
        frecuencia_hora=None, activo=True,
    )

    fila = db.obtener_correo_config(conn, uid)
    assert fila is not None
    assert fila["email"] == "maria@example.com"
    assert fila["app_password"] == "clave-app-123"
    assert fila["imap_host"] == "imap.gmail.com"
    assert fila["imap_port"] == 993
    assert fila["frecuencia_tipo"] == "intervalo"
    assert fila["frecuencia_minutos"] == 45
    assert fila["frecuencia_hora"] is None
    assert fila["activo"] == 1


def test_guardar_correo_config_sin_contrasena_y_sin_fila_previa_lanza_valueerror(conn):
    """La contraseña es obligatoria la primera vez -- sin ella no puede
    crearse la fila, para no dejar una automatización sin credenciales."""
    uid = crear_usuario(conn, "carlos")

    with pytest.raises(ValueError):
        db.guardar_correo_config(conn, uid, email="carlos@example.com", app_password=None)

    assert db.obtener_correo_config(conn, uid) is None


def test_guardar_correo_config_con_password_vacia_y_sin_fila_previa_tambien_lanza_valueerror(conn):
    """Una cadena vacía cuenta como "no se dio contraseña", igual que None."""
    uid = crear_usuario(conn, "carlos2")

    with pytest.raises(ValueError):
        db.guardar_correo_config(conn, uid, email="carlos2@example.com", app_password="")


# ----------------------------- guardar_correo_config: update / upsert -----------------------------

def test_guardar_correo_config_con_password_none_sobre_fila_existente_mantiene_la_anterior(conn):
    """app_password=None en una edición NO debe pisar la contraseña ya
    guardada -- así el formulario no obliga a reescribirla cada vez que se
    cambia solo la frecuencia."""
    uid = crear_usuario(conn, "maria")
    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-original")

    db.guardar_correo_config(
        conn, uid, email="maria@example.com", app_password=None,
        frecuencia_tipo="diario", frecuencia_hora="08:00",
    )

    fila = db.obtener_correo_config(conn, uid)
    assert fila["app_password"] == "clave-original"
    assert fila["frecuencia_tipo"] == "diario"


def test_guardar_correo_config_con_password_vacia_sobre_fila_existente_mantiene_la_anterior(conn):
    """Mismo caso que con None, pero con cadena vacía (lo que en la
    práctica llega desde el formulario cuando el campo se deja en blanco)."""
    uid = crear_usuario(conn, "maria")
    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-original")

    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="")

    fila = db.obtener_correo_config(conn, uid)
    assert fila["app_password"] == "clave-original"


def test_guardar_correo_config_con_password_nueva_si_la_actualiza(conn):
    uid = crear_usuario(conn, "maria")
    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-original")

    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-nueva")

    fila = db.obtener_correo_config(conn, uid)
    assert fila["app_password"] == "clave-nueva"


def test_guardar_correo_config_llamado_dos_veces_actualiza_la_misma_fila_no_crea_otra(conn):
    """Upsert real: dos llamadas para el mismo usuario_id deben resultar en
    UNA sola fila en correo_config, no dos."""
    uid = crear_usuario(conn, "maria")
    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-1")
    db.guardar_correo_config(conn, uid, email="maria-nuevo@example.com", app_password="clave-2")

    total = conn.execute("SELECT COUNT(*) AS n FROM correo_config WHERE usuario_id = ?", (uid,)).fetchone()["n"]
    assert total == 1

    fila = db.obtener_correo_config(conn, uid)
    assert fila["email"] == "maria-nuevo@example.com"
    assert fila["app_password"] == "clave-2"


# ----------------------------- guardar_correo_config: cedula (opcional) -----------------------------

def test_guardar_correo_config_con_cedula_la_guarda(conn):
    uid = crear_usuario(conn, "maria")

    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-app", cedula="123456789")

    fila = db.obtener_correo_config(conn, uid)
    assert fila["cedula"] == "123456789"


def test_guardar_correo_config_sin_cedula_nunca_configurada_queda_none(conn):
    """La cédula es opcional -- a diferencia de app_password, no hace
    falta nunca para poder guardar la configuración."""
    uid = crear_usuario(conn, "maria")

    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-app")

    fila = db.obtener_correo_config(conn, uid)
    assert fila["cedula"] is None


def test_guardar_correo_config_sin_cedula_no_lanza_valueerror_ni_en_el_alta(conn):
    """A diferencia de app_password, faltar la cédula la primera vez que
    se configura la cuenta nunca debe lanzar -- solo app_password es
    obligatoria."""
    uid = crear_usuario(conn, "maria")

    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-app", cedula=None)

    assert db.obtener_correo_config(conn, uid) is not None


def test_guardar_correo_config_con_cedula_vacia_sobre_fila_existente_mantiene_la_anterior(conn):
    uid = crear_usuario(conn, "maria")
    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-app", cedula="111222333")

    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password=None, cedula="")

    fila = db.obtener_correo_config(conn, uid)
    assert fila["cedula"] == "111222333"


def test_guardar_correo_config_con_cedula_none_sobre_fila_existente_mantiene_la_anterior(conn):
    uid = crear_usuario(conn, "maria")
    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-app", cedula="111222333")

    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password=None, cedula=None)

    fila = db.obtener_correo_config(conn, uid)
    assert fila["cedula"] == "111222333"


def test_guardar_correo_config_con_cedula_nueva_la_actualiza(conn):
    uid = crear_usuario(conn, "maria")
    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-app", cedula="111222333")

    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password=None, cedula="999888777")

    fila = db.obtener_correo_config(conn, uid)
    assert fila["cedula"] == "999888777"


# ----------------------------- obtener_correo_config -----------------------------

def test_obtener_correo_config_de_usuario_sin_config_devuelve_none(conn):
    uid = crear_usuario(conn, "sin_config")
    assert db.obtener_correo_config(conn, uid) is None


# ----------------------------- listar_correo_configs_activos -----------------------------

def test_listar_correo_configs_activos_ignora_las_pausadas(conn):
    """Con varios usuarios, solo deben listarse las cuentas con
    activo=1 -- las pausadas (activo=0) quedan afuera del recorrido de
    leer_correo.py."""
    id_activa = crear_usuario(conn, "activa")
    id_pausada = crear_usuario(conn, "pausada")
    db.guardar_correo_config(conn, id_activa, email="activa@example.com", app_password="x", activo=True)
    db.guardar_correo_config(conn, id_pausada, email="pausada@example.com", app_password="x", activo=False)

    activos = db.listar_correo_configs_activos(conn)

    usuarios_ids = {c["usuario_id"] for c in activos}
    assert id_activa in usuarios_ids
    assert id_pausada not in usuarios_ids


def test_listar_correo_configs_activos_devuelve_las_de_todos_los_usuarios_activos(conn):
    """No debe devolver solo la primera -- con varias cuentas activas,
    deben aparecer todas."""
    id_1 = crear_usuario(conn, "uno")
    id_2 = crear_usuario(conn, "dos")
    id_3 = crear_usuario(conn, "tres")
    db.guardar_correo_config(conn, id_1, email="uno@example.com", app_password="x", activo=True)
    db.guardar_correo_config(conn, id_2, email="dos@example.com", app_password="x", activo=True)
    db.guardar_correo_config(conn, id_3, email="tres@example.com", app_password="x", activo=False)

    activos = db.listar_correo_configs_activos(conn)

    usuarios_ids = {c["usuario_id"] for c in activos}
    assert usuarios_ids == {id_1, id_2}


def test_listar_correo_configs_activos_sin_ninguna_cuenta_configurada_devuelve_lista_vacia(conn):
    """Caso disperso: BD recién creada, sin ninguna fila en correo_config."""
    assert db.listar_correo_configs_activos(conn) == []


# ----------------------------- actualizar_estado_correo -----------------------------

def test_actualizar_estado_correo_actualiza_solo_los_campos_de_estado(conn):
    """No debe tocar email/app_password/frecuencia -- solo
    ultima_corrida/ultima_corrida_ok/ultimo_error."""
    uid = crear_usuario(conn, "maria")
    db.guardar_correo_config(
        conn, uid, email="maria@example.com", app_password="clave-original",
        frecuencia_tipo="intervalo", frecuencia_minutos=60,
    )

    db.actualizar_estado_correo(conn, uid, ok=True, error=None)

    fila = db.obtener_correo_config(conn, uid)
    assert fila["ultima_corrida"] is not None
    assert fila["ultima_corrida_ok"] == 1
    assert fila["ultimo_error"] is None
    # el resto de los campos, intactos:
    assert fila["email"] == "maria@example.com"
    assert fila["app_password"] == "clave-original"
    assert fila["frecuencia_tipo"] == "intervalo"
    assert fila["frecuencia_minutos"] == 60


def test_actualizar_estado_correo_con_error_guarda_ok_falso_y_el_mensaje(conn):
    uid = crear_usuario(conn, "maria")
    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-original")

    db.actualizar_estado_correo(conn, uid, ok=False, error="fallo de conexión IMAP simulado")

    fila = db.obtener_correo_config(conn, uid)
    assert fila["ultima_corrida_ok"] == 0
    assert fila["ultimo_error"] == "fallo de conexión IMAP simulado"


# ----------------------------- eliminar_correo_config -----------------------------

def test_eliminar_correo_config_borra_la_fila(conn):
    uid = crear_usuario(conn, "maria")
    db.guardar_correo_config(conn, uid, email="maria@example.com", app_password="clave-original")

    db.eliminar_correo_config(conn, uid)

    assert db.obtener_correo_config(conn, uid) is None


def test_eliminar_correo_config_no_afecta_la_fila_de_otro_usuario(conn):
    """Aislamiento entre usuarios: borrar la config de uno no debe tocar
    la del otro."""
    id_1 = crear_usuario(conn, "uno")
    id_2 = crear_usuario(conn, "dos")
    db.guardar_correo_config(conn, id_1, email="uno@example.com", app_password="x")
    db.guardar_correo_config(conn, id_2, email="dos@example.com", app_password="y")

    db.eliminar_correo_config(conn, id_1)

    assert db.obtener_correo_config(conn, id_1) is None
    fila_2 = db.obtener_correo_config(conn, id_2)
    assert fila_2 is not None
    assert fila_2["email"] == "dos@example.com"
