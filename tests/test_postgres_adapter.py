"""
Pruebas de la CAPA DE ADAPTACIÓN a PostgreSQL (db_finanzas._PGConn /
_adapt_sql_pg).

POR QUÉ ESTE ARCHIVO EXISTE: el resto de la suite corre sobre SQLite (el
fallback de conectar() cuando no hay DATABASE_URL), así que toda esta
capa quedaba SIN cobertura -- y ahí aparecieron, uno tras otro, bugs que
la suite en verde nunca vio: _PGConn sin cursor(), bool de Python contra
columna INTEGER, el ':' de 'HH24:MI:SS' convertido en placeholder, y el
'RETURNING id' agregado a tablas que no tienen columna id (que dejó el
panel de "Visibilidad de vistas" sin guardar nada, 2026-09-17).

Se saltan enteras si no hay DATABASE_URL: en local la suite sigue
corriendo sobre SQLite como siempre. Para correrlas de verdad hay que
hacerlo donde SÍ hay PostgreSQL -- el contenedor dev:

    docker exec finanzas-app-dev python -m pytest tests/test_postgres_adapter.py -q

AISLAMIENTO: nunca tocan las tablas reales. Cada prueba trabaja sobre dos
tablas propias con prefijo _qa_adapter_*, creadas y borradas en la
fixture.
"""
import os

import pytest

import db_finanzas as db


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip(),
    reason="Requiere PostgreSQL (DATABASE_URL); en local la suite corre sobre SQLite.",
)


@pytest.fixture
def pg():
    """Conexión PostgreSQL real + dos tablas desechables: una con columna
    `id` y otra identificada por una PK natural (sin `id`), que es el caso
    que rompía."""
    conn = db.conectar()
    assert isinstance(conn, db._PGConn), "DATABASE_URL está seteada pero conectar() no dio un _PGConn"
    conn.execute("DROP TABLE IF EXISTS _qa_adapter_sin_id")
    conn.execute("DROP TABLE IF EXISTS _qa_adapter_con_id")
    conn.execute(
        "CREATE TABLE _qa_adapter_sin_id ("
        "  usuario_id INTEGER NOT NULL,"
        "  clave TEXT NOT NULL,"
        "  bandera INTEGER NOT NULL DEFAULT 0,"
        f"  creado_en TEXT NOT NULL DEFAULT {db._NOW_PG},"
        "  PRIMARY KEY (usuario_id, clave))"
    )
    conn.execute("CREATE TABLE _qa_adapter_con_id (id SERIAL PRIMARY KEY, valor TEXT)")
    conn.commit()
    yield conn
    conn.execute("DROP TABLE IF EXISTS _qa_adapter_sin_id")
    conn.execute("DROP TABLE IF EXISTS _qa_adapter_con_id")
    conn.commit()
    conn.close()


def test_insert_en_tabla_sin_columna_id_no_aborta_la_transaccion(pg):
    """_PGConn.execute() agrega "RETURNING id" a todo INSERT para emular
    cursor.lastrowid de sqlite3. En una tabla sin columna `id` eso falla, y
    en PostgreSQL un statement fallido ABORTA la transacción entera: sin el
    SAVEPOINT, el reintento moría con InFailedSqlTransaction y se perdía la
    operación completa."""
    pg.execute("INSERT INTO _qa_adapter_sin_id (usuario_id, clave) VALUES (?, ?)", (1, "correo_automatico"))
    pg.commit()

    filas = pg.execute("SELECT clave FROM _qa_adapter_sin_id WHERE usuario_id = ?", (1,)).fetchall()
    assert [f["clave"] for f in filas] == ["correo_automatico"]

    # La transacción sigue utilizable después del INSERT (lo que fallaba).
    pg.execute("INSERT INTO _qa_adapter_sin_id (usuario_id, clave) VALUES (?, ?)", (1, "otra_vista"))
    pg.commit()
    assert pg.execute("SELECT COUNT(*) AS n FROM _qa_adapter_sin_id").fetchone()["n"] == 2


def test_insert_or_ignore_en_tabla_sin_id_es_idempotente(pg):
    """El toggle de vistas re-inserta la misma fila sin querer duplicarla
    (ver db.ocultar_vista): INSERT OR IGNORE tiene que traducir a
    ON CONFLICT DO NOTHING y no reventar la segunda vez."""
    for _ in range(2):
        pg.execute(
            "INSERT OR IGNORE INTO _qa_adapter_sin_id (usuario_id, clave) VALUES (?, ?)",
            (7, "correo_automatico"),
        )
    pg.commit()
    assert pg.execute("SELECT COUNT(*) AS n FROM _qa_adapter_sin_id").fetchone()["n"] == 1


def test_insert_en_tabla_con_id_sigue_devolviendo_lastrowid(pg):
    """El SAVEPOINT no debe costar la funcionalidad que motivaba el
    "RETURNING id": crear_tarjeta()/crear_usuario() dependen de lastrowid."""
    cur = pg.execute("INSERT INTO _qa_adapter_con_id (valor) VALUES (?)", ("x",))
    pg.commit()
    assert isinstance(cur.lastrowid, int) and cur.lastrowid > 0


def test_bool_de_python_se_guarda_en_columna_integer(pg):
    """psycopg2 adapta bool a boolean de SQL, pero el esquema guarda esos
    campos como INTEGER (es_deuda, activa, activo...) igual que SQLite.
    Sin la coerción, el INSERT muere con DatatypeMismatch -- rompía la
    carga de CUALQUIER extracto."""
    pg.execute(
        "INSERT INTO _qa_adapter_sin_id (usuario_id, clave, bandera) VALUES (?, ?, ?)",
        (2, "con_bool", True),
    )
    pg.commit()
    assert pg.execute("SELECT bandera FROM _qa_adapter_sin_id WHERE usuario_id = ?", (2,)).fetchone()["bandera"] == 1


def test_executemany_con_parametros_nombrados_y_bool(pg):
    """insertar_movimientos() usa executemany con :nombre y es_deuda bool."""
    pg.executemany(
        "INSERT INTO _qa_adapter_sin_id (usuario_id, clave, bandera) VALUES (:usuario_id, :clave, :bandera)",
        [{"usuario_id": 3, "clave": "a", "bandera": True},
         {"usuario_id": 3, "clave": "b", "bandera": False}],
    )
    pg.commit()
    filas = pg.execute("SELECT clave, bandera FROM _qa_adapter_sin_id WHERE usuario_id = ? ORDER BY clave", (3,)).fetchall()
    assert [(f["clave"], f["bandera"]) for f in filas] == [("a", 1), ("b", 0)]


def test_el_formato_de_to_char_no_se_convierte_en_placeholder(pg):
    """_NOW_PG lleva 'YYYY-MM-DD HH24:MI:SS'. Sustituir ':nombre' sin
    respetar los literales lo dejaba en 'HH24%(MI)s%(SS)s' y el DEFAULT
    guardaba horas corruptas del tipo '2026-09-16 23%(50)s%(56)s'."""
    pg.execute("INSERT INTO _qa_adapter_sin_id (usuario_id, clave) VALUES (?, ?)", (4, "ts"))
    pg.commit()
    creado = pg.execute("SELECT creado_en FROM _qa_adapter_sin_id WHERE usuario_id = ?", (4,)).fetchone()["creado_en"]
    assert "%(" not in creado, f"timestamp corrupto: {creado!r}"
    # 'YYYY-MM-DD HH:MM:SS'
    assert len(creado) == 19 and creado[4] == "-" and creado[13] == ":", creado


def test_los_casts_de_postgres_no_se_rompen(pg):
    """'texto'::int lleva '::', que el regex de parámetros nombrados podía
    confundir con ':int'."""
    assert pg.execute("SELECT '42'::int AS n").fetchone()["n"] == 42
