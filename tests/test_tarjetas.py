"""
Pruebas de tarjetas de crédito con cupo (2026-09-07, ver
requisitos/2026-09-07_tarjetas-credito-cupo.md) en la capa de datos
(db_finanzas.py): CRUD de tarjetas_credito, migración idempotente de la
columna movimientos.tarjeta_id, auto-asociación por últimos-4 dígitos
dentro de insertar_movimientos(), y el cálculo de deuda/cupo disponible
por tarjeta (obtener_tarjetas_con_deuda).

IMPORTANTE -- aislamiento de filesystem: BD aislada en tmp_path (mismo
patrón que tests/test_conciliacion.py). Nunca toca data/finanzas.db
real. Este archivo NO hace "import app" (reservado a
tests/test_app_integration.py) -- las pruebas de las rutas HTTP de
routes/tarjetas.py viven en tests/test_tarjetas_routes.py, reutilizando
las fixtures app_ctx/client/login ya existentes.
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


@pytest.fixture
def conn_sin_esquema(tmp_path, monkeypatch):
    """BD aislada en tmp_path, SIN crear el esquema todavía -- para poder
    crear a mano una versión "vieja" de las tablas antes de migrar (mismo
    patrón que tests/test_conciliacion.py)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "DB_PATH", data_dir / "finanzas.db")
    monkeypatch.setattr(db, "XLSX_PATH", data_dir / "finanzas_personales.xlsx")

    c = db.conectar()
    yield c
    c.close()


def crear_usuario(conn, username):
    return db.crear_usuario(conn, username, "clave-123", "usuario", username)


def mov(fecha, tipo, categoria, monto, descripcion, entidad="Bancolombia", moneda="COP", **extra):
    """Movimiento crudo listo para insertar_movimientos(). `extra` permite
    pasar tarjeta_id/ultimos4 sin ensuciar la firma con más posicionales
    (mismo criterio que ya usa test_conciliacion.py::mov, extendido)."""
    d = {
        "fecha": fecha, "tipo": tipo, "categoria": categoria, "moneda": moneda,
        "monto": monto, "descripcion": descripcion, "entidad": entidad,
    }
    d.update(extra)
    return d


def mov_tarjeta(fecha, monto, descripcion_extra="Tienda", ultimos4="2011", **extra):
    """Movimiento de compra a crédito -- la descripción SIEMPRE incluye
    "T.Cred" para que clasificar_medio_pago() lo reconozca como
    medio_pago='credito' (lo que hace que cuente en v_deuda_ledger /
    obtener_tarjetas_con_deuda). El campo real "ultimos4" que usa el
    matching automático (ver _resolver_tarjeta_por_ultimos4) es un campo
    APARTE del dict, no se re-parsea de la descripción (ver requisitos) --
    por default es el mismo valor que aparece en el texto, pero se puede
    pisar vía `extra["ultimos4"]` en los tests que necesiten que difieran."""
    extra.setdefault("ultimos4", ultimos4)
    return mov(fecha, "gasto", "compras", monto,
               f"Compra en {descripcion_extra} con T.Cred *{ultimos4}", **extra)


def mov_pago_tarjeta(fecha, monto, ultimos4="2011", **extra):
    return mov(fecha, "gasto", "pago_tarjeta_credito", monto,
               f"Pago tarjeta Visa *{ultimos4}", **extra)


# ============================================================================
# crear_tarjeta(): cupo obligatorio y > 0 (ver requisitos, "Cupo total es
# obligatorio")
# ============================================================================

def test_crear_tarjeta_caso_feliz_con_todos_los_campos(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, usuario_id=uid, nombre="Bancolombia Visa Gold",
                            cupo_total=5_000_000, entidad="Bancolombia", ultimos4="2011")

    tarjeta = db.obtener_tarjeta(conn, uid, tid)

    assert tarjeta["nombre"] == "Bancolombia Visa Gold"
    assert tarjeta["entidad"] == "Bancolombia"
    assert tarjeta["cupo_total"] == 5_000_000
    assert tarjeta["ultimos4"] == "2011"
    assert tarjeta["activa"] is True


def test_crear_tarjeta_con_solo_los_campos_obligatorios(conn):
    """entidad y últimos4 son opcionales -- deben quedar en None, no en
    cadena vacía."""
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, usuario_id=uid, nombre="Tarjeta simple", cupo_total=100000)

    tarjeta = db.obtener_tarjeta(conn, uid, tid)

    assert tarjeta["entidad"] is None
    assert tarjeta["ultimos4"] is None


def test_crear_tarjeta_sin_nombre_rechaza(conn):
    uid = crear_usuario(conn, "ana")
    with pytest.raises(ValueError):
        db.crear_tarjeta(conn, usuario_id=uid, nombre="   ", cupo_total=100000)


@pytest.mark.parametrize("cupo_invalido", [0, -1, -100000, None])
def test_crear_tarjeta_sin_cupo_o_con_cupo_no_positivo_rechaza(conn, cupo_invalido):
    uid = crear_usuario(conn, "ana")
    with pytest.raises(ValueError):
        db.crear_tarjeta(conn, usuario_id=uid, nombre="Tarjeta", cupo_total=cupo_invalido)


# ============================================================================
# obtener_tarjetas() / obtener_tarjeta(): aislamiento y filtro solo_activas
# ============================================================================

def test_obtener_tarjetas_aisla_entre_usuarios(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    db.crear_tarjeta(conn, uid1, "Tarjeta de Ana", 100000)
    db.crear_tarjeta(conn, uid2, "Tarjeta de Beto", 200000)

    tarjetas_ana = db.obtener_tarjetas(conn, uid1)

    assert [t["nombre"] for t in tarjetas_ana] == ["Tarjeta de Ana"]


def test_obtener_tarjetas_usuario_sin_tarjetas_devuelve_lista_vacia(conn):
    uid = crear_usuario(conn, "ana")
    assert db.obtener_tarjetas(conn, uid) == []


def test_obtener_tarjetas_solo_activas_excluye_archivadas(conn):
    uid = crear_usuario(conn, "ana")
    activa_id = db.crear_tarjeta(conn, uid, "Activa", 100000)
    archivada_id = db.crear_tarjeta(conn, uid, "Archivada", 100000)
    db.archivar_tarjeta(conn, uid, archivada_id)

    todas = db.obtener_tarjetas(conn, uid, solo_activas=False)
    solo_activas = db.obtener_tarjetas(conn, uid, solo_activas=True)

    assert {t["id"] for t in todas} == {activa_id, archivada_id}
    assert {t["id"] for t in solo_activas} == {activa_id}


def test_obtener_tarjeta_de_otro_usuario_devuelve_none(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    tid = db.crear_tarjeta(conn, uid1, "Tarjeta de Ana", 100000)

    assert db.obtener_tarjeta(conn, uid2, tid) is None


def test_obtener_tarjeta_inexistente_devuelve_none(conn):
    uid = crear_usuario(conn, "ana")
    assert db.obtener_tarjeta(conn, uid, 999999) is None


# ============================================================================
# actualizar_tarjeta(): edición parcial, validaciones y aislamiento
# ============================================================================

def test_actualizar_tarjeta_edicion_parcial_solo_toca_campos_presentes(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Original", 100000, entidad="Nu", ultimos4="1111")

    ok = db.actualizar_tarjeta(conn, uid, tid, cupo_total=500000)  # solo sube el cupo

    assert ok is True
    tarjeta = db.obtener_tarjeta(conn, uid, tid)
    assert tarjeta["cupo_total"] == 500000
    assert tarjeta["nombre"] == "Original"
    assert tarjeta["entidad"] == "Nu"
    assert tarjeta["ultimos4"] == "1111"


def test_actualizar_tarjeta_string_vacio_limpia_campo_opcional(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Original", 100000, entidad="Nu", ultimos4="1111")

    db.actualizar_tarjeta(conn, uid, tid, entidad="", ultimos4="")

    tarjeta = db.obtener_tarjeta(conn, uid, tid)
    assert tarjeta["entidad"] is None
    assert tarjeta["ultimos4"] is None


def test_actualizar_tarjeta_nombre_vacio_rechaza(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Original", 100000)
    with pytest.raises(ValueError):
        db.actualizar_tarjeta(conn, uid, tid, nombre="   ")


@pytest.mark.parametrize("cupo_invalido", [0, -1])
def test_actualizar_tarjeta_cupo_no_positivo_rechaza(conn, cupo_invalido):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Original", 100000)
    with pytest.raises(ValueError):
        db.actualizar_tarjeta(conn, uid, tid, cupo_total=cupo_invalido)


def test_actualizar_tarjeta_de_otro_usuario_devuelve_false_sin_tocar_nada(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    tid = db.crear_tarjeta(conn, uid1, "Tarjeta de Ana", 100000)

    ok = db.actualizar_tarjeta(conn, uid2, tid, nombre="Hackeada", cupo_total=999999999)

    assert ok is False
    tarjeta = db.obtener_tarjeta(conn, uid1, tid)
    assert tarjeta["nombre"] == "Tarjeta de Ana"
    assert tarjeta["cupo_total"] == 100000


def test_actualizar_tarjeta_inexistente_devuelve_false(conn):
    uid = crear_usuario(conn, "ana")
    assert db.actualizar_tarjeta(conn, uid, 999999, nombre="x") is False


def test_actualizar_tarjeta_cupo_se_refleja_de_inmediato_en_cupo_disponible(conn):
    """El cambio de cupo_total no requiere recalcular ni reprocesar
    movimientos -- obtener_tarjetas_con_deuda() siempre lee el cupo
    actual de la tabla."""
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Original", 100000)
    db.insertar_movimientos(conn, [mov_tarjeta("2026-09-01", 40000, tarjeta_id=tid)],
                             origen="app_manual", usuario_id=uid)

    antes = db.obtener_tarjetas_con_deuda(conn, uid)["activas"][0]
    assert antes["cupo_disponible"] == 60000

    db.actualizar_tarjeta(conn, uid, tid, cupo_total=200000)

    despues = db.obtener_tarjetas_con_deuda(conn, uid)["activas"][0]
    assert despues["cupo_disponible"] == 160000


# ============================================================================
# archivar_tarjeta(): soft delete, conserva historial
# ============================================================================

def test_archivar_tarjeta_caso_feliz(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Vieja", 100000)

    assert db.archivar_tarjeta(conn, uid, tid) is True
    assert db.obtener_tarjeta(conn, uid, tid)["activa"] is False


def test_archivar_tarjeta_no_borra_el_historial_de_movimientos(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Vieja", 100000)
    db.insertar_movimientos(conn, [mov_tarjeta("2026-09-01", 40000, tarjeta_id=tid)],
                             origen="app_manual", usuario_id=uid)

    db.archivar_tarjeta(conn, uid, tid)

    assert len(db.obtener_movimientos(conn, usuario_id=uid)) == 1


def test_archivar_tarjeta_de_otro_usuario_devuelve_false(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    tid = db.crear_tarjeta(conn, uid1, "Tarjeta de Ana", 100000)

    assert db.archivar_tarjeta(conn, uid2, tid) is False
    assert db.obtener_tarjeta(conn, uid1, tid)["activa"] is True


def test_archivar_tarjeta_inexistente_devuelve_false(conn):
    uid = crear_usuario(conn, "ana")
    assert db.archivar_tarjeta(conn, uid, 999999) is False


# ============================================================================
# borrar_tarjeta(): borrado definitivo SOLO si nunca tuvo movimientos
# ============================================================================

def test_borrar_tarjeta_sin_movimientos_la_elimina(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Sin usar", 100000)

    ok, error = db.borrar_tarjeta(conn, uid, tid)

    assert ok is True
    assert error is None
    assert db.obtener_tarjeta(conn, uid, tid) is None


def test_borrar_tarjeta_con_movimientos_asociados_falla_y_sugiere_archivar(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Con historial", 100000)
    db.insertar_movimientos(conn, [mov_tarjeta("2026-09-01", 40000, tarjeta_id=tid)],
                             origen="app_manual", usuario_id=uid)

    ok, error = db.borrar_tarjeta(conn, uid, tid)

    assert ok is False
    assert "archiv" in error.lower()
    assert db.obtener_tarjeta(conn, uid, tid) is not None  # sigue existiendo, no quedó a medio borrar


def test_borrar_tarjeta_de_otro_usuario_no_la_borra(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    tid = db.crear_tarjeta(conn, uid1, "Tarjeta de Ana", 100000)

    ok, error = db.borrar_tarjeta(conn, uid2, tid)

    assert ok is False
    assert db.obtener_tarjeta(conn, uid1, tid) is not None


def test_borrar_tarjeta_inexistente_devuelve_false(conn):
    uid = crear_usuario(conn, "ana")
    ok, error = db.borrar_tarjeta(conn, uid, 999999)
    assert ok is False
    assert error is not None


# ============================================================================
# _migrar_columna_tarjeta_id(): idempotencia sobre una BD vieja, y las
# filas históricas NUNCA se reasignan retroactivamente
# ============================================================================

def _crear_tabla_movimientos_vieja(conn):
    conn.execute("""
        CREATE TABLE movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            tipo TEXT NOT NULL,
            categoria TEXT,
            moneda TEXT NOT NULL DEFAULT 'COP',
            monto REAL NOT NULL,
            descripcion TEXT,
            entidad TEXT,
            medio_pago TEXT NOT NULL DEFAULT 'debito',
            es_deuda INTEGER NOT NULL DEFAULT 0,
            origen TEXT NOT NULL DEFAULT 'gmail_bot_excel',
            usuario_id INTEGER,
            creado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()


def test_migrar_columna_tarjeta_id_agrega_tabla_y_columna_a_bd_vieja(conn_sin_esquema):
    conn = conn_sin_esquema
    _crear_tabla_movimientos_vieja(conn)
    columnas_antes = [r["name"] for r in conn.execute("PRAGMA table_info(movimientos)")]
    assert "tarjeta_id" not in columnas_antes

    db.crear_esquema(conn)  # crea tarjetas_credito Y agrega la columna, en ese orden

    columnas_despues = [r["name"] for r in conn.execute("PRAGMA table_info(movimientos)")]
    assert "tarjeta_id" in columnas_despues
    tablas = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert "tarjetas_credito" in tablas

    # Idempotencia: correrlo de nuevo no debe romper nada ni duplicar la columna.
    db.crear_esquema(conn)
    columnas_final = [r["name"] for r in conn.execute("PRAGMA table_info(movimientos)")]
    assert columnas_final.count("tarjeta_id") == 1


def test_movimientos_historicos_preexistentes_quedan_con_tarjeta_id_null_tras_migrar(conn_sin_esquema):
    """Movimientos ya cargados ANTES de esta feature nunca se reasignan
    retroactivamente a ninguna tarjeta -- ni con la migración, ni después,
    aunque el usuario termine registrando una tarjeta con el mismo
    último-4 que aparece en su descripción (ver requisitos, "Migración de
    datos existentes")."""
    conn = conn_sin_esquema
    conn.execute("""
        CREATE TABLE usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL, password_hash TEXT NOT NULL,
            rol TEXT NOT NULL DEFAULT 'usuario', nombre_mostrado TEXT,
            creado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    _crear_tabla_movimientos_vieja(conn)
    conn.execute("INSERT INTO usuarios (username, password_hash, nombre_mostrado) VALUES ('ana', 'x', 'Ana')")
    conn.execute(
        "INSERT INTO movimientos (fecha, tipo, categoria, moneda, monto, descripcion, entidad, medio_pago, "
        "es_deuda, usuario_id) VALUES ('2026-01-01', 'gasto', 'credito', 'COP', 50000, "
        "'Compra vieja con T.Cred *2011', 'Bancolombia', 'credito', 1, 1)"
    )
    conn.commit()

    db.crear_esquema(conn)  # corre la migración de tarjeta_id sobre la fila ya existente

    fila = conn.execute("SELECT tarjeta_id FROM movimientos WHERE id = 1").fetchone()
    assert fila["tarjeta_id"] is None

    # Registrar HOY una tarjeta con ese mismo último-4 tampoco reasigna
    # el histórico -- no existe ninguna función que lo haga.
    db.crear_tarjeta(conn, usuario_id=1, nombre="Visa", cupo_total=1000000, ultimos4="2011")
    fila = conn.execute("SELECT tarjeta_id FROM movimientos WHERE id = 1").fetchone()
    assert fila["tarjeta_id"] is None


# ============================================================================
# _resolver_tarjeta_por_ultimos4(): matching automático, nunca ambiguo
# ============================================================================

def test_resolver_tarjeta_por_ultimos4_sin_valor_devuelve_none(conn):
    uid = crear_usuario(conn, "ana")
    assert db._resolver_tarjeta_por_ultimos4(conn, uid, None) is None
    assert db._resolver_tarjeta_por_ultimos4(conn, uid, "") is None


def test_resolver_tarjeta_por_ultimos4_una_sola_coincidencia_activa(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Visa", 100000, ultimos4="2011")

    assert db._resolver_tarjeta_por_ultimos4(conn, uid, "2011") == tid


def test_resolver_tarjeta_por_ultimos4_sin_ninguna_coincidencia_devuelve_none(conn):
    uid = crear_usuario(conn, "ana")
    db.crear_tarjeta(conn, uid, "Visa", 100000, ultimos4="2011")

    assert db._resolver_tarjeta_por_ultimos4(conn, uid, "9999") is None


def test_resolver_tarjeta_por_ultimos4_ambiguedad_dos_tarjetas_activas_devuelve_none(conn):
    """Dos tarjetas activas del mismo usuario con el mismo último-4 (ej.
    tarjeta reemplazada con el mismo número final) -- nunca se adivina."""
    uid = crear_usuario(conn, "ana")
    db.crear_tarjeta(conn, uid, "Visa vieja", 100000, ultimos4="2011")
    db.crear_tarjeta(conn, uid, "Visa nueva (reposicion)", 100000, ultimos4="2011")

    assert db._resolver_tarjeta_por_ultimos4(conn, uid, "2011") is None


def test_resolver_tarjeta_por_ultimos4_ignora_tarjetas_archivadas(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Vieja", 100000, ultimos4="2011")
    db.archivar_tarjeta(conn, uid, tid)

    assert db._resolver_tarjeta_por_ultimos4(conn, uid, "2011") is None


def test_resolver_tarjeta_por_ultimos4_no_matchea_tarjeta_de_otro_usuario(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    db.crear_tarjeta(conn, uid2, "Tarjeta de Beto", 100000, ultimos4="2011")

    assert db._resolver_tarjeta_por_ultimos4(conn, uid1, "2011") is None


# ============================================================================
# insertar_movimientos(): resolución de tarjeta_id -- explícito, auto por
# últimos4, y NUNCA reasignación retroactiva de un duplicado
# ============================================================================

def _tarjeta_id_de(conn, mov_id):
    return conn.execute("SELECT tarjeta_id FROM movimientos WHERE id = ?", (mov_id,)).fetchone()["tarjeta_id"]


def test_insertar_movimientos_resuelve_tarjeta_id_por_ultimos4_automaticamente(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Visa", 100000, ultimos4="2011")

    db.insertar_movimientos(conn, [mov_tarjeta("2026-09-01", 40000, ultimos4="2011")],
                             origen="correo_imap", usuario_id=uid)

    fila_id = db.obtener_movimientos(conn, usuario_id=uid)[0]["id"]
    assert _tarjeta_id_de(conn, fila_id) == tid


def test_insertar_movimientos_sin_ultimos4_deja_tarjeta_id_null(conn):
    """Un movimiento que no trae 'ultimos4' (histórico, o un parser que no
    lo detectó) queda sin tarjeta -- nunca se adivina."""
    uid = crear_usuario(conn, "ana")
    db.crear_tarjeta(conn, uid, "Visa", 100000, ultimos4="2011")

    db.insertar_movimientos(conn, [mov("2026-09-01", "gasto", "compras", 40000, "Compra en Tienda con T.Cred *2011")],
                             origen="correo_imap", usuario_id=uid)

    fila_id = db.obtener_movimientos(conn, usuario_id=uid)[0]["id"]
    assert _tarjeta_id_de(conn, fila_id) is None


def test_insertar_movimientos_con_ultimos4_ambiguo_deja_tarjeta_id_null(conn):
    uid = crear_usuario(conn, "ana")
    db.crear_tarjeta(conn, uid, "Visa vieja", 100000, ultimos4="2011")
    db.crear_tarjeta(conn, uid, "Visa nueva", 100000, ultimos4="2011")

    db.insertar_movimientos(conn, [mov_tarjeta("2026-09-01", 40000, ultimos4="2011")],
                             origen="correo_imap", usuario_id=uid)

    fila_id = db.obtener_movimientos(conn, usuario_id=uid)[0]["id"]
    assert _tarjeta_id_de(conn, fila_id) is None


def test_insertar_movimientos_tarjeta_id_explicito_nunca_se_pisa(conn):
    """Un movimiento manual con tarjeta_id ya elegido explícitamente (ver
    routes/dashboard.py::api_registrar_movimiento) nunca se recalcula, ni
    siquiera si también trae 'ultimos4' apuntando a otra tarjeta
    distinta."""
    uid = crear_usuario(conn, "ana")
    tid_elegida = db.crear_tarjeta(conn, uid, "Elegida a mano", 100000, ultimos4="1111")
    tid_por_ultimos4 = db.crear_tarjeta(conn, uid, "La que matchea el ultimos4", 100000, ultimos4="2011")

    db.insertar_movimientos(
        conn, [mov_tarjeta("2026-09-01", 40000, ultimos4="2011", tarjeta_id=tid_elegida)],
        origen="app_manual", usuario_id=uid,
    )

    fila_id = db.obtener_movimientos(conn, usuario_id=uid)[0]["id"]
    assert _tarjeta_id_de(conn, fila_id) == tid_elegida
    assert _tarjeta_id_de(conn, fila_id) != tid_por_ultimos4


def test_insertar_movimientos_duplicado_nunca_reasigna_tarjeta_id_a_la_fila_existente(conn):
    """Un movimiento ya cargado SIN tarjeta (ej. histórico) que después
    "matchea" como duplicado de un movimiento nuevo que sí trae
    ultimos4 nunca debe reasignarse retroactivamente -- ver requisitos,
    "nada se reasigna retroactivamente, ni siquiera implícitamente"."""
    uid = crear_usuario(conn, "ana")
    db.crear_tarjeta(conn, uid, "Visa", 100000, ultimos4="2011")

    db.insertar_movimientos(conn, [mov("2026-09-01", "gasto", "compras", 40000, "Compra vieja")],
                             origen="app_manual", usuario_id=uid)
    fila_original_id = db.obtener_movimientos(conn, usuario_id=uid)[0]["id"]

    stats = db.insertar_movimientos(conn, [mov_tarjeta("2026-09-01", 40000, ultimos4="2011")],
                                     origen="correo_imap", usuario_id=uid)

    assert stats["nuevos"] == 0
    assert stats["duplicados_bd"] == 1
    assert _tarjeta_id_de(conn, fila_original_id) is None


# ============================================================================
# obtener_tarjetas_con_deuda(): cupo/deuda/disponible por tarjeta, y el
# bloque aparte "sin_asignar"
# ============================================================================

def test_obtener_tarjetas_con_deuda_usuario_sin_tarjetas_ni_movimientos(conn):
    """Estado vacío total: 0 tarjetas, 0 movimientos -- el Dashboard debe
    verse igual que antes de esta feature, sin listas rotas."""
    uid = crear_usuario(conn, "ana")
    assert db.obtener_tarjetas_con_deuda(conn, uid) == {"activas": [], "sin_asignar": 0.0}


def test_obtener_tarjetas_con_deuda_usuario_sin_tarjetas_registradas_pero_con_deuda_historica(conn):
    """0 tarjetas registradas, con movimientos de tarjeta ya existentes:
    'activas' vacío (nada roto), toda la deuda cae en 'sin_asignar'."""
    uid = crear_usuario(conn, "ana")
    db.insertar_movimientos(conn, [mov("2026-09-01", "gasto", "compras", 40000, "Compra en Tienda con T.Cred *2011")],
                             origen="correo_imap", usuario_id=uid)

    resultado = db.obtener_tarjetas_con_deuda(conn, uid)

    assert resultado["activas"] == []
    assert resultado["sin_asignar"] == 40000


def test_obtener_tarjetas_con_deuda_calcula_cupo_disponible_y_porcentaje_de_uso(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Visa", 200000, ultimos4="2011")
    db.insertar_movimientos(conn, [mov_tarjeta("2026-09-01", 50000, tarjeta_id=tid)],
                             origen="app_manual", usuario_id=uid)

    tarjeta = db.obtener_tarjetas_con_deuda(conn, uid)["activas"][0]

    assert tarjeta["deuda_actual"] == 50000
    assert tarjeta["cupo_disponible"] == 150000
    assert tarjeta["porcentaje_uso"] == 25.0


def test_obtener_tarjetas_con_deuda_cupo_disponible_negativo_no_se_trunca_a_cero(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Visa", 100000, ultimos4="2011")
    db.insertar_movimientos(conn, [mov_tarjeta("2026-09-01", 150000, tarjeta_id=tid)],
                             origen="app_manual", usuario_id=uid)

    tarjeta = db.obtener_tarjetas_con_deuda(conn, uid)["activas"][0]

    assert tarjeta["cupo_disponible"] == -50000
    assert tarjeta["porcentaje_uso"] == 150.0


def test_obtener_tarjetas_con_deuda_resta_los_pagos_de_esa_tarjeta(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Visa", 200000, ultimos4="2011")
    db.insertar_movimientos(
        conn,
        [
            mov_tarjeta("2026-09-01", 80000, tarjeta_id=tid),
            mov_pago_tarjeta("2026-09-05", 30000, tarjeta_id=tid),
        ],
        origen="app_manual", usuario_id=uid,
    )

    tarjeta = db.obtener_tarjetas_con_deuda(conn, uid)["activas"][0]

    assert tarjeta["deuda_actual"] == 50000  # 80000 - 30000


def test_obtener_tarjetas_con_deuda_ignora_movimientos_en_moneda_distinta_de_cop(conn):
    """Una compra en USD de la misma tarjeta no debe mezclarse en la
    deuda/%uso de esa tarjeta -- mismo filtro moneda='COP' que
    v_deuda_ledger."""
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Visa", 200000, ultimos4="2011")
    db.insertar_movimientos(
        conn,
        [
            mov_tarjeta("2026-09-01", 50000, tarjeta_id=tid, moneda="COP"),
            mov_tarjeta("2026-09-02", 100, tarjeta_id=tid, moneda="USD"),
        ],
        origen="app_manual", usuario_id=uid,
    )

    tarjeta = db.obtener_tarjetas_con_deuda(conn, uid)["activas"][0]

    assert tarjeta["deuda_actual"] == 50000


def test_obtener_tarjetas_con_deuda_aisla_entre_usuarios(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    tid1 = db.crear_tarjeta(conn, uid1, "Visa de Ana", 200000, ultimos4="2011")
    db.crear_tarjeta(conn, uid2, "Visa de Beto", 300000, ultimos4="3333")
    db.insertar_movimientos(conn, [mov_tarjeta("2026-09-01", 50000, tarjeta_id=tid1)],
                             origen="app_manual", usuario_id=uid1)

    resultado_ana = db.obtener_tarjetas_con_deuda(conn, uid1)
    resultado_beto = db.obtener_tarjetas_con_deuda(conn, uid2)

    assert resultado_ana["activas"][0]["deuda_actual"] == 50000
    assert resultado_beto["activas"][0]["deuda_actual"] == 0.0


def test_obtener_tarjetas_con_deuda_suma_todas_las_tarjetas_mas_sin_asignar_igual_al_agregado(conn):
    """Consistencia aritmética central del feature: deuda por tarjeta
    (todas las activas) + sin_asignar == el agregado global que ya
    devuelve v_deuda_ledger/obtener_ledger_deuda (mismo saldo, mismo
    signo, mismo filtro moneda='COP')."""
    uid = crear_usuario(conn, "ana")
    tid1 = db.crear_tarjeta(conn, uid, "Visa", 200000, ultimos4="2011")
    tid2 = db.crear_tarjeta(conn, uid, "Mastercard", 300000, ultimos4="4444")
    db.insertar_movimientos(
        conn,
        [
            mov_tarjeta("2026-09-01", 50000, ultimos4="2011"),  # auto-matchea tid1
            mov_tarjeta("2026-09-02", 70000, ultimos4="4444"),  # auto-matchea tid2
            mov_tarjeta("2026-09-03", 20000, ultimos4="9999"),  # sin match -> sin_asignar
        ],
        origen="correo_imap", usuario_id=uid,
    )

    resultado = db.obtener_tarjetas_con_deuda(conn, uid)
    total_por_tarjeta = sum(t["deuda_actual"] for t in resultado["activas"])
    total_desglosado = total_por_tarjeta + resultado["sin_asignar"]

    ledger = db.obtener_ledger_deuda(conn, usuario_id=uid)
    total_agregado = ledger[-1]["saldo_acumulado"] if ledger else 0.0

    assert total_desglosado == total_agregado == 140000


def test_obtener_tarjetas_con_deuda_tarjeta_archivada_con_movimientos_desaparece_del_desglose(conn):
    """Chequeo de consistencia aritmética con una tarjeta ARCHIVADA que ya
    tenía movimientos asociados: deja de listarse en 'activas' (correcto,
    es lo esperado al archivar), pero esos movimientos tampoco caen en
    'sin_asignar' porque su tarjeta_id no es NULL (apunta a la tarjeta
    archivada, que sigue existiendo). Si esto no cuadra con el agregado
    global (v_deuda_ledger), es una inconsistencia aritmética real -- el
    documento de requisitos pide explícitamente evitarla ("verificar esto
    con datos de prueba reales... antes de dar por buena la
    implementación")."""
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Visa vieja", 200000, ultimos4="2011")
    db.insertar_movimientos(conn, [mov_tarjeta("2026-09-01", 50000, tarjeta_id=tid)],
                             origen="app_manual", usuario_id=uid)
    db.archivar_tarjeta(conn, uid, tid)

    resultado = db.obtener_tarjetas_con_deuda(conn, uid)
    total_desglosado = sum(t["deuda_actual"] for t in resultado["activas"]) + resultado["sin_asignar"]

    ledger = db.obtener_ledger_deuda(conn, usuario_id=uid)
    total_agregado = ledger[-1]["saldo_acumulado"]

    assert total_desglosado == total_agregado
