"""
Pruebas de conectar() en db_finanzas.py -- journal_mode forzado a DELETE
(2026-09-10).

Contexto del bug real: conectar() dejaba que SQLite usara el
journal_mode que ya tuviera el archivo .db en disco (WAL en este caso).
`data/` está montada como bind mount de Docker Desktop en Windows, que
no soporta bien la memoria compartida (mmap) que WAL necesita entre
procesos -- al recrear el contenedor `finanzas-app-dev` el 2026-09-10,
esto causó "disk I/O error" y una caída real de dev. El fix agrega
`PRAGMA journal_mode = DELETE` en cada conexión nueva; estas pruebas
verifican que journal_mode queda en 'delete' incluso si el archivo fue
dejado en 'wal' por una conexión anterior (simulando el escenario que
rompió dev), y que esto no rompe operaciones normales sobre la BD.

IMPORTANTE -- aislamiento de filesystem: BD aislada en tmp_path (mismo
patrón que tests/test_tarjetas.py). Nunca toca data/finanzas.db real.
Este archivo NO hace "import app" (reservado a
tests/test_app_integration.py).
"""
import sqlite3

import pytest

import db_finanzas as db


# ----------------------------- Fixtures -----------------------------

@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Redirige DATA_DIR/DB_PATH/XLSX_PATH de db_finanzas a tmp_path,
    sin abrir ninguna conexión todavía (para poder manipular el modo del
    archivo .db a mano antes de la primera llamada a conectar())."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(db, "DATA_DIR", d)
    monkeypatch.setattr(db, "DB_PATH", d / "finanzas.db")
    monkeypatch.setattr(db, "XLSX_PATH", d / "finanzas_personales.xlsx")
    return d


def _journal_mode(conn: sqlite3.Connection) -> str:
    return conn.execute("PRAGMA journal_mode").fetchone()[0]


# ----------------------------- Tests -----------------------------

def test_conectar_deja_journal_mode_en_delete_en_bd_nueva(data_dir):
    """Caso feliz: un archivo .db recién creado (sin journal_mode previo
    explícito) queda en modo 'delete' tras conectar()."""
    conn = db.conectar()
    try:
        assert _journal_mode(conn) == "delete"
    finally:
        conn.close()


def test_conectar_fuerza_delete_aunque_el_archivo_ya_estaba_en_wal(data_dir):
    """Reproduce el escenario real que causó la caída de dev: el archivo
    .db fue dejado en modo WAL por una conexión anterior (ej. antes del
    fix, o por una herramienta externa como DB Browser). conectar() debe
    corregirlo a 'delete' en la siguiente conexión, sin necesidad de
    tocar el archivo a mano."""
    # Primero dejamos el archivo .db realmente en WAL, sin pasar por
    # db.conectar() (que ya tiene el fix) -- así el test no depende del
    # propio código bajo prueba para preparar el escenario.
    conn_previa = sqlite3.connect(db.DB_PATH)
    conn_previa.execute("PRAGMA journal_mode = WAL")
    assert _journal_mode(conn_previa) == "wal"
    conn_previa.close()

    # Ahora sí, la conexión bajo prueba: debe corregir el modo a 'delete'.
    conn = db.conectar()
    try:
        assert _journal_mode(conn) == "delete"
    finally:
        conn.close()

    # Y una tercera conexión (ya con el archivo corregido) también debe
    # quedar en 'delete' -- no es un efecto de una sola vez.
    conn2 = db.conectar()
    try:
        assert _journal_mode(conn2) == "delete"
    finally:
        conn2.close()


def test_conectar_en_modo_delete_no_rompe_operaciones_normales(data_dir):
    """El journal_mode DELETE no debe romper el flujo normal de
    crear_esquema + crear_usuario + insertar_movimientos + consultas --
    es decir, el fix no tiene efectos secundarios sobre operaciones
    típicas de la app."""
    conn = db.conectar()
    try:
        assert _journal_mode(conn) == "delete"

        db.crear_esquema(conn)
        usuario_id = db.crear_usuario(conn, "ana", "clave-123", "usuario", "Ana")

        movimientos = [{
            "fecha": "2026-09-10",
            "tipo": "gasto",
            "categoria": "comida",
            "monto": 15000,
            "descripcion": "Almuerzo",
            "medio_pago": "debito",
            "entidad": "Bancolombia",
            "moneda": "COP",
        }]
        resultado = db.insertar_movimientos(conn, movimientos, "app_manual", usuario_id)
        # No debe lanzar ni comportarse distinto por estar en DELETE en
        # vez de WAL: el movimiento se inserta y queda consultable.
        assert resultado["nuevos"] == 1

        filas = conn.execute(
            "SELECT COUNT(*) FROM movimientos WHERE usuario_id = ?",
            (usuario_id,),
        ).fetchone()[0]
        assert filas == 1

        # journal_mode sigue en delete después de todas estas operaciones
        # (no vuelve a WAL solo por hacer escrituras/commits normales).
        assert _journal_mode(conn) == "delete"
    finally:
        conn.close()


def test_conexion_context_manager_tambien_queda_en_delete(data_dir):
    """El context manager db.conexion() (usado en la mayoría de las
    rutas de app.py) delega en conectar(), así que también debe heredar
    journal_mode = delete."""
    with db.conexion() as conn:
        assert _journal_mode(conn) == "delete"
