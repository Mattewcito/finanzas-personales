"""
Configuración compartida de pytest.

Dos cosas: agrega src/ al path (para poder hacer "import db_finanzas" sin
instalar el proyecto como paquete), y decide CONTRA QUÉ MOTOR corre la
suite.

MOTOR DE BASE DE DATOS
======================
Por defecto la suite corre sobre SQLite, igual que siempre: cada fixture
`conn` monkeypatchea db.DB_PATH a un archivo en tmp_path y llama a
db.conectar().

Si está seteada TEST_DATABASE_URL, la suite entera corre sobre
PostgreSQL -- el motor REAL de la app. Esto existe porque la capa de
adaptación a PostgreSQL (_PGConn/_adapt_sql_pg) no tenía cobertura
ninguna, y ahí aparecieron cinco bugs seguidos que la suite en verde
nunca vio: _PGConn sin cursor(), bool de Python contra columna INTEGER,
el ':' de 'HH24:MI:SS' convertido en placeholder, timestamps corruptos, y
el 'RETURNING id' agregado a tablas sin columna id (que dejó el panel de
"Visibilidad de vistas" sin guardar nada).

    # levantar el motor y correr todo contra él
    docker compose up -d postgres
    TEST_DATABASE_URL=postgresql://finanzas:finanzas_local@localhost:5433/finanzas_test pytest -q

AISLAMIENTO: cada test corre en su PROPIO esquema de PostgreSQL, creado
antes y borrado después (`CREATE SCHEMA` + `search_path`). Ningún test ve
las tablas de otro, igual que hoy cada uno tiene su propio archivo SQLite.
No hace falta tocar las fixtures `conn` que ya existen en cada archivo:
se intercepta db.conectar(), que es por donde pasan todas (incluida la
que usa la app Flask vía db.conexion()).

SEGURIDAD: _verificar_bd_de_test() se niega a correr si la URL no apunta
a una base cuyo nombre termina en "_test". La base real de la app se
llama "finanzas": apuntar la suite ahí borraría datos reales, y estos
tests crean y destruyen esquemas sin preguntar.
"""
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

def _sin_localhost(url: str) -> str:
    """Reescribe 'localhost' a '127.0.0.1'.

    No es cosmético: en Windows 'localhost' resuelve primero a ::1, y el
    puerto del contenedor está bindeado a 127.0.0.1, así que cada conexión
    espera a que el intento IPv6 falle antes de reintentar por IPv4. Son
    ~2 segundos POR CONEXIÓN (medido: 2.07s vs 0.027s), y la suite abre
    varias por test: la diferencia es correr en ~1 minuto o en ~50. Es el
    mismo destino, así que no cambia contra qué se testea."""
    return url.replace("@localhost:", "@127.0.0.1:")


TEST_DATABASE_URL = _sin_localhost(os.environ.get("TEST_DATABASE_URL", "").strip())


def _verificar_bd_de_test(url: str) -> None:
    """Barrera dura: la suite crea y DESTRUYE esquemas, así que solo puede
    apuntar a una base dedicada a tests. La base real de la app se llama
    'finanzas' -- si alguien exporta esa URL por error (copiar/pegar de
    docker-compose.yml es lo más fácil del mundo), esto corta antes de
    tocar nada en vez de descubrirlo cuando ya no hay datos."""
    nombre = urlparse(url).path.lstrip("/")
    if not nombre.endswith("_test"):
        pytest.exit(
            f"TEST_DATABASE_URL apunta a la base {nombre!r}, que no termina en '_test'.\n"
            "La suite crea y borra esquemas: solo puede correr contra una base dedicada.\n"
            "Creala con:  docker exec finanzas-postgres psql -U finanzas -d postgres "
            "-c 'CREATE DATABASE finanzas_test OWNER finanzas'",
            returncode=1,
        )


if TEST_DATABASE_URL:
    _verificar_bd_de_test(TEST_DATABASE_URL)


def pytest_report_header(config):
    if TEST_DATABASE_URL:
        nombre = urlparse(TEST_DATABASE_URL).path.lstrip("/")
        return f"motor de BD: PostgreSQL ({nombre}) -- un esquema aislado por test"
    return "motor de BD: SQLite (exportá TEST_DATABASE_URL para correr contra PostgreSQL)"


@pytest.fixture
def columnas_de():
    """Nombres de columna de una tabla, en el motor que sea.

    Las pruebas de migración necesitan comprobar "esta columna no estaba
    y después de migrar sí" -- y `PRAGMA table_info(...)` es exclusivo de
    SQLite, así que contra PostgreSQL ese chequeo explotaba. Justamente
    esas pruebas son las que MÁS interesa correr contra PostgreSQL:
    _agregar_columna_si_falta() tiene una rama distinta por motor."""
    import db_finanzas as db

    def _columnas(conn, tabla: str) -> list[str]:
        if isinstance(conn, db._PGConn):
            filas = conn.execute(
                "SELECT column_name AS name FROM information_schema.columns "
                "WHERE table_name = %s AND table_schema = current_schema() "
                "ORDER BY ordinal_position",
                (tabla,),
            ).fetchall()
        else:
            filas = conn.execute(f"PRAGMA table_info({tabla})").fetchall()
        return [f["name"] for f in filas]

    return _columnas


@pytest.fixture
def tablas_de():
    """Nombres de las tablas existentes, en el motor que sea -- el
    equivalente portable de "SELECT name FROM sqlite_master WHERE
    type='table'" (ver columnas_de para el porqué)."""
    import db_finanzas as db

    def _tablas(conn) -> list[str]:
        if isinstance(conn, db._PGConn):
            filas = conn.execute(
                "SELECT table_name AS name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
            ).fetchall()
        else:
            filas = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return [f["name"] for f in filas]

    return _tablas


@pytest.fixture(autouse=True)
def _motor_postgres(monkeypatch):
    """Cuando hay TEST_DATABASE_URL, cada test recibe su propio esquema y
    db.conectar() queda apuntado ahí. Sin la variable no hace nada y la
    suite sigue sobre SQLite exactamente como antes."""
    if not TEST_DATABASE_URL:
        yield
        return

    import psycopg2
    import db_finanzas as db

    esquema = f"t_{uuid.uuid4().hex[:20]}"

    def _admin(sql: str) -> None:
        raw = psycopg2.connect(TEST_DATABASE_URL)
        raw.autocommit = True
        try:
            with raw.cursor() as cur:
                cur.execute(sql)
        finally:
            raw.close()

    _admin(f'CREATE SCHEMA "{esquema}"')

    def conectar_en_esquema():
        raw = psycopg2.connect(TEST_DATABASE_URL)
        raw.autocommit = False
        with raw.cursor() as cur:
            # El esquema va PRIMERO en el search_path; public queda de
            # respaldo para las extensiones/tipos del sistema.
            cur.execute(f'SET search_path TO "{esquema}", public')
        raw.commit()
        return db._PGConn(raw)

    monkeypatch.setattr(db, "conectar", conectar_en_esquema)
    try:
        yield
    finally:
        _admin(f'DROP SCHEMA "{esquema}" CASCADE')
