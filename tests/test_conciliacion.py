"""
Pruebas del motor de conciliación de `insertar_movimientos` en
db_finanzas.py (2026-09-06): dedup real por (moneda, monto, tipo) + fecha
±1 día, con desempate por palabras compartidas, multiset de "consumo" por
fila existente, y enriquecimiento de registros manuales con la
descripción bancaria real cuando una fuente automática los reconcilia.

Cubre también:
  - _mejor_coincidencia() / _palabras() de forma unitaria (white-box).
  - obtener_movimientos() trayendo id/origen/referencia_bancaria.
  - Las dos migraciones nuevas de esquema: _migrar_columna_referencia_bancaria
    y _migrar_columna_cedula_correo_config, sobre una BD que ya tenía las
    tablas SIN esas columnas.

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


def mov(fecha, tipo, categoria, monto, descripcion, entidad="Bancolombia", moneda="COP"):
    return {
        "fecha": fecha, "tipo": tipo, "categoria": categoria, "moneda": moneda,
        "monto": monto, "descripcion": descripcion, "entidad": entidad,
    }


# ============================================================================
# _palabras()
# ============================================================================

def test_palabras_extrae_en_minusculas_de_varios_textos():
    assert db._palabras("Hola Mundo", "MUNDO Feliz") == {"hola", "mundo", "feliz"}


def test_palabras_con_none_no_rompe():
    assert db._palabras(None, None) == set()


def test_palabras_con_texto_vacio_da_set_vacio():
    assert db._palabras("", "") == set()


# ============================================================================
# _mejor_coincidencia()
# ============================================================================

def test_mejor_coincidencia_sin_candidatos_devuelve_none():
    m = {"fecha": "2026-09-06", "descripcion": "x", "entidad": "y"}
    assert db._mejor_coincidencia(m, []) is None


def test_mejor_coincidencia_fuera_de_ventana_de_un_dia_devuelve_none():
    m = {"fecha": "2026-09-06", "descripcion": "x", "entidad": "y"}
    candidato_lejano = {"id": 1, "fecha": "2026-09-10", "descripcion": "x", "entidad": "y"}
    assert db._mejor_coincidencia(m, [candidato_lejano]) is None


def test_mejor_coincidencia_a_un_dia_de_diferencia_matchea():
    m = {"fecha": "2026-09-06", "descripcion": "", "entidad": ""}
    candidato_dia_siguiente = {"id": 1, "fecha": "2026-09-07", "descripcion": "", "entidad": ""}
    assert db._mejor_coincidencia(m, [candidato_dia_siguiente])["id"] == 1

    candidato_dia_anterior = {"id": 2, "fecha": "2026-09-05", "descripcion": "", "entidad": ""}
    assert db._mejor_coincidencia(m, [candidato_dia_anterior])["id"] == 2


def test_mejor_coincidencia_a_dos_dias_de_diferencia_no_matchea():
    m = {"fecha": "2026-09-06", "descripcion": "", "entidad": ""}
    candidato = {"id": 1, "fecha": "2026-09-08", "descripcion": "", "entidad": ""}
    assert db._mejor_coincidencia(m, [candidato]) is None


def test_mejor_coincidencia_prefiere_fecha_exacta_sobre_un_dia_de_diferencia():
    """Con dos candidatos posibles, uno en la fecha exacta y otro a 1 día,
    debe ganar siempre el de la fecha exacta -- sin importar palabras."""
    m = {"fecha": "2026-09-06", "descripcion": "algo sin relacion", "entidad": "Nada"}
    candidato_un_dia = {"id": 1, "fecha": "2026-09-05", "descripcion": "algo sin relacion", "entidad": "Nada"}
    candidato_exacto = {"id": 2, "fecha": "2026-09-06", "descripcion": "", "entidad": ""}

    resultado = db._mejor_coincidencia(m, [candidato_un_dia, candidato_exacto])

    assert resultado["id"] == 2


def test_mejor_coincidencia_sin_palabras_compartidas_igual_matchea_por_gate_duro():
    """Un registro manual ('almuerzo') y uno de correo ('Transferiste...')
    pueden no compartir NINGUNA palabra y aun así ser la misma transacción
    real -- las palabras son solo desempate, nunca requisito."""
    m = {"fecha": "2026-09-06", "descripcion": "Transferiste $30.000 de tu cuenta *5360", "entidad": "Bancolombia"}
    candidato = {"id": 1, "fecha": "2026-09-06", "descripcion": "almuerzo", "entidad": "Manual"}

    assert db._mejor_coincidencia(m, [candidato])["id"] == 1


def test_mejor_coincidencia_en_misma_fecha_desempata_por_palabras_compartidas():
    m = {"fecha": "2026-09-06", "descripcion": "Transferiste a Juan Perez", "entidad": "Bancolombia"}
    candidato_pocas_palabras = {"id": 1, "fecha": "2026-09-06", "descripcion": "Pago tarjeta", "entidad": "Nu"}
    candidato_muchas_palabras = {"id": 2, "fecha": "2026-09-06", "descripcion": "Transferiste a Juan", "entidad": "Bancolombia"}

    resultado = db._mejor_coincidencia(m, [candidato_pocas_palabras, candidato_muchas_palabras])

    assert resultado["id"] == 2


# ============================================================================
# insertar_movimientos(): casos base
# ============================================================================

def test_insertar_movimientos_lista_vacia_no_rompe_y_no_inserta_nada(conn):
    uid = crear_usuario(conn, "ana")

    stats = db.insertar_movimientos(conn, [], origen="app_manual", usuario_id=uid)

    assert stats == {"nuevos": 0, "duplicados": 0, "duplicados_bd": 0, "duplicados_lote": 0}
    assert db.obtener_movimientos(conn, usuario_id=uid) == []


def test_insertar_movimientos_caso_feliz_sin_existentes_inserta_todos(conn):
    uid = crear_usuario(conn, "ana")
    movimientos = [
        mov("2026-09-01", "gasto", "comida", 20000, "Almuerzo", "Rappi"),
        mov("2026-09-02", "ingreso", "salario", 2000000, "Pago nomina", "Empresa"),
    ]

    stats = db.insertar_movimientos(conn, movimientos, origen="app_manual", usuario_id=uid)

    assert stats["nuevos"] == 2
    assert stats["duplicados"] == 0
    assert len(db.obtener_movimientos(conn, usuario_id=uid)) == 2


def test_gate_de_tipo_ingreso_y_gasto_mismo_dia_y_monto_no_se_concilian_entre_si(conn):
    """El tipo es parte del gate duro: un ingreso y un gasto con la misma
    fecha+monto nunca deben tratarse como la misma transacción."""
    uid = crear_usuario(conn, "ana")
    db.insertar_movimientos(conn, [mov("2026-09-06", "gasto", "otros", 30000, "gasto x")], origen="app_manual", usuario_id=uid)

    stats = db.insertar_movimientos(conn, [mov("2026-09-06", "ingreso", "otros", 30000, "ingreso x")], origen="app_manual", usuario_id=uid)

    assert stats["nuevos"] == 1
    assert stats["duplicados"] == 0
    assert len(db.obtener_movimientos(conn, usuario_id=uid)) == 2


def test_duplicados_lote_dentro_del_mismo_batch_sigue_funcionando(conn):
    """Dos filas idénticas (mismo fecha+moneda+monto+tipo) DENTRO del
    mismo lote no deben insertarse dos veces -- caso preexistente, no
    debe haberse roto con el nuevo motor de conciliación."""
    uid = crear_usuario(conn, "ana")
    movimientos = [
        mov("2026-09-01", "gasto", "comida", 20000, "Almuerzo"),
        mov("2026-09-01", "gasto", "comida", 20000, "Almuerzo repetido en el mismo lote"),
    ]

    stats = db.insertar_movimientos(conn, movimientos, origen="app_manual", usuario_id=uid)

    assert stats["nuevos"] == 1
    assert stats["duplicados_lote"] == 1
    assert stats["duplicados_bd"] == 0
    assert stats["duplicados"] == 1


def test_insertar_movimientos_no_concilia_contra_movimientos_de_otro_usuario(conn):
    """Aislamiento entre usuarios: la misma transacción exacta para dos
    usuarios distintos no debe conciliarse entre sí -- cada quien tiene
    sus propias finanzas separadas."""
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    movimiento = mov("2026-09-06", "gasto", "comida", 30000, "almuerzo", "Manual")

    db.insertar_movimientos(conn, [dict(movimiento)], origen="app_manual", usuario_id=uid1)
    stats = db.insertar_movimientos(conn, [dict(movimiento)], origen="app_manual", usuario_id=uid2)

    assert stats["nuevos"] == 1
    assert stats["duplicados"] == 0
    assert len(db.obtener_movimientos(conn, usuario_id=uid1)) == 1
    assert len(db.obtener_movimientos(conn, usuario_id=uid2)) == 1


# ============================================================================
# Escenario central: reconciliación manual <-> automático a través de
# llamadas SEPARADAS (cada corrida de leer_correo.py es una llamada distinta)
# ============================================================================

def test_reconciliacion_manual_correo_segunda_transaccion_y_re_escaneo(conn):
    uid = crear_usuario(conn, "ana")

    # 1) Usuario carga a mano "almuerzo" por $30.000.
    stats0 = db.insertar_movimientos(
        conn,
        [mov("2026-09-06", "gasto", "comida", 30000, "almuerzo", "Manual")],
        origen="app_manual", usuario_id=uid,
    )
    assert stats0["nuevos"] == 1

    # 2) Llega por correo la MISMA transacción real, descrita distinto ->
    #    debe reconciliar (0 nuevos, 1 duplicado), y la fila manual debe
    #    quedar con referencia_bancaria = la descripción del correo, SIN
    #    tocar su propia descripción/categoría.
    stats1 = db.insertar_movimientos(
        conn,
        [mov("2026-09-06", "gasto", "transferencias", 30000,
             "Transferiste $30.000.00 de tu cuenta *5360 a *1234")],
        origen="correo_imap", usuario_id=uid,
    )
    assert stats1["nuevos"] == 0
    assert stats1["duplicados"] == 1
    assert stats1["duplicados_bd"] == 1

    filas = db.obtener_movimientos(conn, usuario_id=uid)
    assert len(filas) == 1
    fila_manual = filas[0]
    assert fila_manual["descripcion"] == "almuerzo"
    assert fila_manual["categoria"] == "comida"
    assert fila_manual["referencia_bancaria"] == "Transferiste $30.000.00 de tu cuenta *5360 a *1234"

    # 3) SEGUNDA transacción real de $30.000 el MISMO día, en una llamada
    #    SEPARADA (otra corrida) -> debe insertarse como NUEVA, no perderse
    #    contra la fila manual ya conciliada.
    stats2 = db.insertar_movimientos(
        conn,
        [mov("2026-09-06", "gasto", "transferencias", 30000,
             "Transferiste $30.000.00 de tu cuenta *5360 a *9999")],
        origen="correo_imap", usuario_id=uid,
    )
    assert stats2["nuevos"] == 1
    assert stats2["duplicados"] == 0

    filas = db.obtener_movimientos(conn, usuario_id=uid)
    assert len(filas) == 2

    # 4) RE-ESCANEAR la misma transacción de correo de nuevo (ventana
    #    solapada) -> debe seguir dando 0 nuevos (sigue siendo duplicado).
    stats3 = db.insertar_movimientos(
        conn,
        [mov("2026-09-06", "gasto", "transferencias", 30000,
             "Transferiste $30.000.00 de tu cuenta *5360 a *9999")],
        origen="correo_imap", usuario_id=uid,
    )
    assert stats3["nuevos"] == 0
    assert stats3["duplicados"] == 1

    filas = db.obtener_movimientos(conn, usuario_id=uid)
    assert len(filas) == 2


def test_avance_de_credito_no_se_duplica_entre_corridas_por_reclasificacion_de_tipo(conn):
    """Bug corregido: enriquecer_movimiento() se aplica ANTES de armar la
    clave de match porque puede reclasificar 'tipo' (avance de crédito:
    'gasto' crudo -> 'ingreso' final). Si se comparara con el tipo crudo,
    un avance nunca encontraría su propia fila ya guardada y se
    insertaría de nuevo en cada corrida."""
    uid = crear_usuario(conn, "ana")
    avance = mov("2026-09-06", "gasto", "avance_credito", 200000,
                 "Avance T.Credito *2011 a cuenta *5360")

    stats1 = db.insertar_movimientos(conn, [dict(avance)], origen="correo_imap", usuario_id=uid)
    stats2 = db.insertar_movimientos(conn, [dict(avance)], origen="correo_imap", usuario_id=uid)

    assert stats1["nuevos"] == 1
    assert stats2["nuevos"] == 0
    assert stats2["duplicados_bd"] == 1

    filas = db.obtener_movimientos(conn, usuario_id=uid)
    assert len(filas) == 1
    assert filas[0]["tipo"] == "ingreso"
    assert filas[0]["es_deuda"] is True


def test_enriquecimiento_no_pisa_una_referencia_bancaria_ya_seteada(conn):
    """Una fila manual que YA absorbió una coincidencia (referencia_bancaria
    ya no es NULL) queda excluida de volver a ser candidata -- por lo
    tanto su referencia_bancaria original nunca puede ser sobreescrita por
    una fuente automática posterior; en cambio, esa fuente se inserta como
    movimiento nuevo."""
    uid = crear_usuario(conn, "ana")
    db.insertar_movimientos(conn, [mov("2026-09-06", "gasto", "comida", 30000, "almuerzo", "Manual")],
                             origen="app_manual", usuario_id=uid)
    fila_manual = db.obtener_movimientos(conn, usuario_id=uid)[0]
    # Simula que ya fue conciliada antes (referencia_bancaria ya seteada a mano).
    conn.execute("UPDATE movimientos SET referencia_bancaria = ? WHERE id = ?",
                 ("Descripcion bancaria original", fila_manual["id"]))
    conn.commit()

    stats = db.insertar_movimientos(
        conn,
        [mov("2026-09-06", "gasto", "transferencias", 30000, "Transferiste $30.000.00 de otra cuenta")],
        origen="correo_imap", usuario_id=uid,
    )

    assert stats["nuevos"] == 1
    assert stats["duplicados"] == 0

    filas = db.obtener_movimientos(conn, usuario_id=uid)
    fila_manual_actualizada = next(f for f in filas if f["id"] == fila_manual["id"])
    assert fila_manual_actualizada["referencia_bancaria"] == "Descripcion bancaria original"


def test_dos_fuentes_automaticas_que_matchean_entre_si_no_se_enriquecen(conn):
    """El enriquecimiento es específicamente 'automático absorbe a
    manual' -- entre dos fuentes automáticas (correo_imap y
    upload_excel), referencia_bancaria debe quedar NULL."""
    uid = crear_usuario(conn, "ana")
    db.insertar_movimientos(
        conn,
        [mov("2026-09-06", "gasto", "transferencias", 30000, "Transferiste $30.000.00 a *1234")],
        origen="correo_imap", usuario_id=uid,
    )

    stats = db.insertar_movimientos(
        conn,
        [mov("2026-09-06", "gasto", "transferencias", 30000, "Movimiento detectado en excel")],
        origen="upload_excel", usuario_id=uid,
    )

    assert stats["nuevos"] == 0
    assert stats["duplicados_bd"] == 1

    filas = db.obtener_movimientos(conn, usuario_id=uid)
    assert len(filas) == 1
    assert filas[0]["referencia_bancaria"] is None


# ============================================================================
# obtener_movimientos(): campos nuevos
# ============================================================================

def test_obtener_movimientos_incluye_id_origen_y_referencia_bancaria(conn):
    uid = crear_usuario(conn, "ana")
    db.insertar_movimientos(conn, [mov("2026-09-01", "gasto", "otros", 1000, "x", "y")],
                             origen="app_manual", usuario_id=uid)

    filas = db.obtener_movimientos(conn, usuario_id=uid)

    assert len(filas) == 1
    fila = filas[0]
    assert isinstance(fila["id"], int)
    assert fila["origen"] == "app_manual"
    assert fila["referencia_bancaria"] is None


def test_obtener_movimientos_sin_usuario_id_trae_de_todos(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    db.insertar_movimientos(conn, [mov("2026-09-01", "gasto", "otros", 1000, "de ana")],
                             origen="app_manual", usuario_id=uid1)
    db.insertar_movimientos(conn, [mov("2026-09-02", "gasto", "otros", 2000, "de beto")],
                             origen="app_manual", usuario_id=uid2)

    todas = db.obtener_movimientos(conn, usuario_id=None)

    descripciones = {f["descripcion"] for f in todas}
    assert descripciones == {"de ana", "de beto"}


# ============================================================================
# Migraciones: referencia_bancaria y cedula sobre tablas ya existentes
# ============================================================================

@pytest.fixture
def conn_sin_esquema(tmp_path, monkeypatch):
    """BD aislada en tmp_path, SIN crear el esquema todavía -- para poder
    crear a mano una versión "vieja" de las tablas antes de migrar."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "DB_PATH", data_dir / "finanzas.db")
    monkeypatch.setattr(db, "XLSX_PATH", data_dir / "finanzas_personales.xlsx")

    c = db.conectar()
    yield c
    c.close()


def test_migrar_columna_referencia_bancaria_agrega_columna_a_tabla_vieja(conn_sin_esquema):
    conn = conn_sin_esquema
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
    columnas_antes = [r["name"] for r in conn.execute("PRAGMA table_info(movimientos)")]
    assert "referencia_bancaria" not in columnas_antes

    db.crear_esquema(conn)  # no debe reventar sobre la tabla vieja

    columnas_despues = [r["name"] for r in conn.execute("PRAGMA table_info(movimientos)")]
    assert "referencia_bancaria" in columnas_despues

    # Idempotencia: correrlo de nuevo no debe romper nada.
    db.crear_esquema(conn)
    columnas_final = [r["name"] for r in conn.execute("PRAGMA table_info(movimientos)")]
    assert columnas_final.count("referencia_bancaria") == 1


def test_migrar_columna_cedula_correo_config_agrega_columna_a_tabla_vieja(conn_sin_esquema):
    conn = conn_sin_esquema
    conn.execute("""
        CREATE TABLE correo_config (
            usuario_id INTEGER PRIMARY KEY,
            email TEXT NOT NULL,
            app_password TEXT NOT NULL,
            imap_host TEXT NOT NULL DEFAULT 'imap.gmail.com',
            imap_port INTEGER NOT NULL DEFAULT 993,
            activo INTEGER NOT NULL DEFAULT 1,
            frecuencia_tipo TEXT NOT NULL DEFAULT 'intervalo',
            frecuencia_minutos INTEGER NOT NULL DEFAULT 30,
            frecuencia_hora TEXT,
            ultima_corrida TEXT,
            ultima_corrida_ok INTEGER,
            ultimo_error TEXT,
            actualizado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()
    columnas_antes = [r["name"] for r in conn.execute("PRAGMA table_info(correo_config)")]
    assert "cedula" not in columnas_antes

    db.crear_esquema(conn)  # no debe reventar sobre la tabla vieja

    columnas_despues = [r["name"] for r in conn.execute("PRAGMA table_info(correo_config)")]
    assert "cedula" in columnas_despues

    # Ya con la columna, guardar_correo_config debe funcionar normal.
    uid = db.crear_usuario(conn, "ana", "clave-123", "usuario", "Ana")
    db.guardar_correo_config(conn, uid, email="ana@example.com", app_password="x", cedula="123456")
    fila = db.obtener_correo_config(conn, uid)
    assert fila["cedula"] == "123456"
