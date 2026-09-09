"""
Pruebas de las funciones de db_finanzas.py relacionadas con la tabla
`vistas_ocultas` (panel de administración que permite ocultar/mostrar
secciones del menú/dashboard por usuario, ver routes/admin_vistas.py):

  - vistas_ocultas_de
  - vistas_ocultas_todos
  - ocultar_vista (idempotente -- INSERT OR IGNORE)
  - mostrar_vista (idempotente -- DELETE de algo que puede no existir)

La AUSENCIA de una fila en `vistas_ocultas` significa "visible" (default)
-- ocultar = INSERT, volver a mostrar = DELETE. Ver el comentario de la
tabla en db_finanzas.py::ESQUEMA_SQL.

IMPORTANTE -- aislamiento de filesystem: BD aislada en tmp_path (mismo
patrón que tests/test_db_correo_config.py). Nunca toca data/finanzas.db
real. Este archivo NO hace "import app" (reservado a
tests/test_app_integration.py).
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


# ----------------------------- vistas_ocultas_de -----------------------------

def test_vistas_ocultas_de_usuario_sin_ninguna_restriccion_devuelve_set_vacio(conn):
    uid = crear_usuario(conn, "sin_restricciones")
    assert db.vistas_ocultas_de(conn, uid) == set()


def test_ocultar_vista_seguido_de_vistas_ocultas_de_refleja_la_vista_oculta(conn):
    uid = crear_usuario(conn, "restringido")

    db.ocultar_vista(conn, uid, "correo_automatico")

    assert db.vistas_ocultas_de(conn, uid) == {"correo_automatico"}


def test_ocultar_vista_dos_veces_con_la_misma_vista_no_revienta(conn):
    """El PRIMARY KEY compuesto (usuario_id, vista) podría chocar si no se
    usara INSERT OR IGNORE -- ocultar algo ya oculto debe ser un no-op,
    no lanzar sqlite3.IntegrityError."""
    uid = crear_usuario(conn, "restringido2")

    db.ocultar_vista(conn, uid, "correo_automatico")
    db.ocultar_vista(conn, uid, "correo_automatico")  # no debe lanzar

    assert db.vistas_ocultas_de(conn, uid) == {"correo_automatico"}
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM vistas_ocultas WHERE usuario_id = ? AND vista = ?",
        (uid, "correo_automatico"),
    ).fetchone()["n"]
    assert total == 1


def test_mostrar_vista_sobre_algo_que_no_estaba_oculto_no_revienta(conn):
    """DELETE de una fila que no existe: debe ser un no-op silencioso."""
    uid = crear_usuario(conn, "nunca_restringido")

    db.mostrar_vista(conn, uid, "correo_automatico")  # no debe lanzar

    assert db.vistas_ocultas_de(conn, uid) == set()


def test_mostrar_vista_despues_de_ocultar_vista_vuelve_a_dejar_el_set_vacio(conn):
    uid = crear_usuario(conn, "vaiven")

    db.ocultar_vista(conn, uid, "correo_automatico")
    db.mostrar_vista(conn, uid, "correo_automatico")

    assert db.vistas_ocultas_de(conn, uid) == set()


# ----------------------------- vistas_ocultas_todos -----------------------------

def test_vistas_ocultas_todos_con_varios_usuarios_algunos_restringidos_devuelve_el_mapa_correcto(conn):
    id_restringido = crear_usuario(conn, "restringido3")
    id_libre = crear_usuario(conn, "libre")

    db.ocultar_vista(conn, id_restringido, "correo_automatico")

    mapa = db.vistas_ocultas_todos(conn)

    assert mapa[id_restringido] == {"correo_automatico"}
    # un usuario sin ninguna restricción NO aparece como key del mapa
    # (comportamiento real: el SELECT solo trae filas de vistas_ocultas,
    # y ese usuario no tiene ninguna) -- vistas_ocultas_todos(...).get(id, set())
    # es la forma correcta de consultarlo del lado de quien lo usa.
    assert id_libre not in mapa


def test_vistas_ocultas_todos_sin_ninguna_restriccion_en_toda_la_bd_devuelve_mapa_vacio(conn):
    """Caso disperso: BD recién creada, sin ninguna fila en vistas_ocultas."""
    crear_usuario(conn, "cualquiera")
    assert db.vistas_ocultas_todos(conn) == {}


# ----------------------------- Aislamiento entre usuarios -----------------------------

def test_ocultar_vista_para_un_usuario_no_afecta_a_otro(conn):
    id_a = crear_usuario(conn, "usuario_a")
    id_b = crear_usuario(conn, "usuario_b")

    db.ocultar_vista(conn, id_a, "correo_automatico")

    assert db.vistas_ocultas_de(conn, id_a) == {"correo_automatico"}
    assert db.vistas_ocultas_de(conn, id_b) == set()
