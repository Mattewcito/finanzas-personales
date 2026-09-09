"""
Pruebas de presupuesto por 3 baldes (50/30/20), mapeo categoría->balde y
metas de ahorro (2026-09-08, ver
requisitos/2026-09-08_presupuesto-ahorro-deudas.md) en la capa de datos
(db_finanzas.py): obtener_presupuesto/guardar_presupuesto,
obtener_mapeo_categorias/asignar_categoria_balde (autopoblado perezoso e
idempotente), CRUD de metas_ahorro con avance calculado siempre al vuelo
sobre movimientos.meta_ahorro_id, y la migración
_migrar_columna_meta_ahorro_id().

IMPORTANTE -- aislamiento de filesystem: BD aislada en tmp_path (mismo
patrón que tests/test_tarjetas.py). Nunca toca data/finanzas.db real.
Este archivo NO hace "import app" (reservado a
tests/test_app_integration.py) -- las pruebas de las rutas HTTP de
routes/presupuesto.py viven en tests/test_presupuesto_routes.py,
reutilizando las fixtures app_ctx/client/login ya existentes.
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
    patrón que tests/test_tarjetas.py)."""
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
    """Movimiento crudo listo para insertar_movimientos() -- mismo patrón
    que tests/test_tarjetas.py::mov, `extra` permite pasar
    meta_ahorro_id/moneda sin ensuciar la firma."""
    d = {
        "fecha": fecha, "tipo": tipo, "categoria": categoria, "moneda": moneda,
        "monto": monto, "descripcion": descripcion, "entidad": entidad,
    }
    d.update(extra)
    return d


def mov_aporte(fecha, monto, meta_id, descripcion="Aporte a meta", **extra):
    return mov(fecha, "gasto", "ahorro", monto, descripcion, meta_ahorro_id=meta_id, **extra)


# ============================================================================
# obtener_presupuesto(): default 50/30/20 con "configurado"=False cuando
# todavía no hay fila guardada, nunca None/NaN
# ============================================================================

def test_obtener_presupuesto_sin_configurar_devuelve_default_50_30_20(conn):
    uid = crear_usuario(conn, "ana")

    p = db.obtener_presupuesto(conn, uid)

    assert p["configurado"] is False
    assert p["pct_necesidades"] == 50.0
    assert p["pct_gustos"] == 30.0
    assert p["pct_ahorro_deudas"] == 20.0
    assert p["suma_pct"] == 100.0
    assert p["usuario_id"] == uid
    assert p["actualizado_en"] is None


def test_obtener_presupuesto_configurado_devuelve_valores_guardados(conn):
    uid = crear_usuario(conn, "ana")
    db.guardar_presupuesto(conn, uid, 40, 30, 30)

    p = db.obtener_presupuesto(conn, uid)

    assert p["configurado"] is True
    assert p["pct_necesidades"] == 40.0
    assert p["pct_gustos"] == 30.0
    assert p["pct_ahorro_deudas"] == 30.0
    assert p["suma_pct"] == 100.0


def test_obtener_presupuesto_aisla_entre_usuarios(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    db.guardar_presupuesto(conn, uid1, 10, 10, 10)

    p2 = db.obtener_presupuesto(conn, uid2)

    assert p2["configurado"] is False
    assert p2["pct_necesidades"] == 50.0


# ============================================================================
# guardar_presupuesto(): NO bloquea suma != 100 (se avisa, no se impide),
# SÍ rechaza negativos/no numéricos/faltantes con ValueError
# ============================================================================

def test_guardar_presupuesto_caso_feliz_suma_100(conn):
    uid = crear_usuario(conn, "ana")

    resultado = db.guardar_presupuesto(conn, uid, 50, 30, 20)

    assert resultado["configurado"] is True
    assert resultado["suma_pct"] == 100.0


def test_guardar_presupuesto_no_bloquea_suma_distinta_de_100(conn):
    """45+45+45=135 -- el documento de requisitos pide "avisar", no
    bloquear (ver "Algo a cuidar entre todos"). suma_pct refleja el
    valor real guardado, no se corrige a 100 en silencio."""
    uid = crear_usuario(conn, "ana")

    resultado = db.guardar_presupuesto(conn, uid, 45, 45, 45)

    assert resultado["pct_necesidades"] == 45.0
    assert resultado["pct_gustos"] == 45.0
    assert resultado["pct_ahorro_deudas"] == 45.0
    assert resultado["suma_pct"] == 135.0
    # Y quedó REALMENTE guardado así, no solo en la respuesta de la llamada.
    p = db.obtener_presupuesto(conn, uid)
    assert p["suma_pct"] == 135.0
    assert p["configurado"] is True


@pytest.mark.parametrize("kwargs", [
    {"pct_necesidades": -1, "pct_gustos": 30, "pct_ahorro_deudas": 20},
    {"pct_necesidades": 50, "pct_gustos": -5, "pct_ahorro_deudas": 20},
    {"pct_necesidades": 50, "pct_gustos": 30, "pct_ahorro_deudas": -20},
])
def test_guardar_presupuesto_rechaza_porcentaje_negativo_en_cualquier_balde(conn, kwargs):
    uid = crear_usuario(conn, "ana")
    with pytest.raises(ValueError):
        db.guardar_presupuesto(conn, uid, **kwargs)


def test_guardar_presupuesto_rechaza_no_numerico(conn):
    uid = crear_usuario(conn, "ana")
    with pytest.raises(ValueError):
        db.guardar_presupuesto(conn, uid, "no-es-un-numero", 30, 20)


@pytest.mark.parametrize("valor_invalido", [None, "", "   "])
def test_guardar_presupuesto_rechaza_valor_faltante(conn, valor_invalido):
    uid = crear_usuario(conn, "ana")
    with pytest.raises(ValueError):
        db.guardar_presupuesto(conn, uid, valor_invalido, 30, 20)


def test_guardar_presupuesto_acepta_cero_en_un_balde(conn):
    """0 es un porcentaje válido (>= 0, no > 0) -- un balde puede
    legítimamente no recibir nada del ingreso."""
    uid = crear_usuario(conn, "ana")

    resultado = db.guardar_presupuesto(conn, uid, 0, 50, 50)

    assert resultado["pct_necesidades"] == 0.0
    assert resultado["suma_pct"] == 100.0


def test_guardar_presupuesto_upsert_reemplaza_sin_duplicar_fila(conn):
    uid = crear_usuario(conn, "ana")
    db.guardar_presupuesto(conn, uid, 50, 30, 20)

    db.guardar_presupuesto(conn, uid, 60, 20, 20)

    filas = conn.execute(
        "SELECT COUNT(*) AS c FROM presupuesto WHERE usuario_id = ?", (uid,)
    ).fetchone()["c"]
    assert filas == 1
    p = db.obtener_presupuesto(conn, uid)
    assert p["pct_necesidades"] == 60.0


def test_guardar_presupuesto_aisla_entre_usuarios(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")

    db.guardar_presupuesto(conn, uid1, 70, 20, 10)

    p2 = db.obtener_presupuesto(conn, uid2)
    assert p2["configurado"] is False
    assert p2["pct_necesidades"] == 50.0


# ============================================================================
# obtener_mapeo_categorias(): autopoblado perezoso e idempotente
# (INSERT OR IGNORE) -- nunca pisa una reasignación manual ya hecha
# ============================================================================

def test_obtener_mapeo_categorias_usuario_sin_movimientos_devuelve_dict_vacio(conn):
    uid = crear_usuario(conn, "ana")
    assert db.obtener_mapeo_categorias(conn, uid) == {}


def test_obtener_mapeo_categorias_autopobla_con_defaults_razonables(conn):
    uid = crear_usuario(conn, "ana")
    db.insertar_movimientos(
        conn,
        [
            mov("2026-09-01", "gasto", "comida", 20000, "Compra en supermercado"),
            mov("2026-09-02", "gasto", "restaurantes", 30000, "Cena afuera"),
            mov("2026-09-03", "gasto", "mi_categoria_rara_de_test", 5000, "Gasto raro"),
        ],
        origen="app_manual", usuario_id=uid,
    )

    mapeo = db.obtener_mapeo_categorias(conn, uid)

    assert mapeo["comida"] == "necesidades"
    assert mapeo["restaurantes"] == "gustos"
    # Categoría 100% personalizada -> fallback conservador (necesidades).
    assert mapeo["mi_categoria_rara_de_test"] == db.CATEGORIA_BALDE_FALLBACK


def test_obtener_mapeo_categorias_no_pisa_una_reasignacion_manual_ya_hecha(conn):
    """Caso explícitamente señalado como propenso a bugs: autopoblar NO
    debe volver a pisar una categoría que el usuario ya reasignó a mano
    a un balde distinto del default."""
    uid = crear_usuario(conn, "ana")
    db.insertar_movimientos(
        conn, [mov("2026-09-01", "gasto", "comida", 20000, "Compra en supermercado")],
        origen="app_manual", usuario_id=uid,
    )

    mapeo_inicial = db.obtener_mapeo_categorias(conn, uid)  # autopobla: comida -> necesidades
    assert mapeo_inicial["comida"] == "necesidades"

    db.asignar_categoria_balde(conn, uid, "comida", "gustos")  # reasignación manual explícita

    mapeo_final = db.obtener_mapeo_categorias(conn, uid)  # NO debe volver a poner "necesidades"
    assert mapeo_final["comida"] == "gustos"


def test_obtener_mapeo_categorias_es_idempotente_sin_reasignacion(conn):
    uid = crear_usuario(conn, "ana")
    db.insertar_movimientos(
        conn, [mov("2026-09-01", "gasto", "comida", 20000, "Compra en supermercado")],
        origen="app_manual", usuario_id=uid,
    )

    mapeo1 = db.obtener_mapeo_categorias(conn, uid)
    mapeo2 = db.obtener_mapeo_categorias(conn, uid)

    assert mapeo1 == mapeo2


def test_obtener_mapeo_categorias_conserva_la_asignacion_aunque_se_borre_el_movimiento(conn):
    """La asignación categoría->balde vive en su propia tabla
    (presupuesto_categorias) -- si el único movimiento de esa categoría
    se borra después, la asignación no desaparece con él."""
    uid = crear_usuario(conn, "ana")
    db.insertar_movimientos(
        conn, [mov("2026-09-01", "gasto", "unica_del_test", 5000, "Gasto único")],
        origen="app_manual", usuario_id=uid,
    )
    db.obtener_mapeo_categorias(conn, uid)  # autopobla
    db.asignar_categoria_balde(conn, uid, "unica_del_test", "gustos")

    movimiento_id = db.obtener_movimientos(conn, usuario_id=uid)[0]["id"]
    db.borrar_movimiento(conn, uid, movimiento_id)
    assert db.obtener_movimientos(conn, usuario_id=uid) == []

    mapeo = db.obtener_mapeo_categorias(conn, uid)
    assert mapeo["unica_del_test"] == "gustos"


def test_obtener_mapeo_categorias_aisla_entre_usuarios(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    db.insertar_movimientos(
        conn, [mov("2026-09-01", "gasto", "comida", 20000, "Compra de Ana")],
        origen="app_manual", usuario_id=uid1,
    )
    db.insertar_movimientos(
        conn, [mov("2026-09-01", "gasto", "comida", 15000, "Compra de Beto")],
        origen="app_manual", usuario_id=uid2,
    )

    db.obtener_mapeo_categorias(conn, uid1)
    db.asignar_categoria_balde(conn, uid1, "comida", "gustos")

    mapeo_beto = db.obtener_mapeo_categorias(conn, uid2)
    assert mapeo_beto["comida"] == "necesidades"  # sin afectar por la reasignación de Ana


# ============================================================================
# asignar_categoria_balde(): UPSERT, valida balde contra IDS_BALDES
# ============================================================================

def test_asignar_categoria_balde_caso_feliz(conn):
    uid = crear_usuario(conn, "ana")
    db.asignar_categoria_balde(conn, uid, "comida", "necesidades")

    mapeo = db.obtener_mapeo_categorias(conn, uid)
    assert mapeo["comida"] == "necesidades"


def test_asignar_categoria_balde_reasigna_categoria_ya_asignada(conn):
    uid = crear_usuario(conn, "ana")
    db.asignar_categoria_balde(conn, uid, "comida", "necesidades")
    db.asignar_categoria_balde(conn, uid, "comida", "ahorro_deudas")

    mapeo = db.obtener_mapeo_categorias(conn, uid)
    assert mapeo["comida"] == "ahorro_deudas"
    filas = conn.execute(
        "SELECT COUNT(*) AS c FROM presupuesto_categorias WHERE usuario_id = ? AND categoria = ?",
        (uid, "comida"),
    ).fetchone()["c"]
    assert filas == 1  # no duplicó la fila


def test_asignar_categoria_balde_invalido_rechaza(conn):
    uid = crear_usuario(conn, "ana")
    with pytest.raises(ValueError):
        db.asignar_categoria_balde(conn, uid, "comida", "balde_inventado")


def test_asignar_categoria_vacia_rechaza(conn):
    uid = crear_usuario(conn, "ana")
    with pytest.raises(ValueError):
        db.asignar_categoria_balde(conn, uid, "   ", "gustos")


# ============================================================================
# crear_meta_ahorro(): monto_objetivo obligatorio y > 0, fecha_objetivo
# opcional pero válida si viene
# ============================================================================

def test_crear_meta_ahorro_caso_feliz_con_fecha_objetivo(conn):
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Vacaciones", 1_000_000, fecha_objetivo="2026-12-31")

    meta = db.obtener_meta_ahorro(conn, uid, mid)

    assert meta["nombre"] == "Vacaciones"
    assert meta["monto_objetivo"] == 1_000_000
    assert meta["fecha_objetivo"] == "2026-12-31"
    assert meta["activa"] is True


def test_crear_meta_ahorro_sin_fecha_objetivo_queda_none(conn):
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Fondo de emergencia", 500_000)

    meta = db.obtener_meta_ahorro(conn, uid, mid)
    assert meta["fecha_objetivo"] is None


def test_crear_meta_ahorro_sin_nombre_rechaza(conn):
    uid = crear_usuario(conn, "ana")
    with pytest.raises(ValueError):
        db.crear_meta_ahorro(conn, uid, "   ", 100_000)


@pytest.mark.parametrize("monto_invalido", [0, -1, -500_000, None])
def test_crear_meta_ahorro_monto_objetivo_no_positivo_rechaza(conn, monto_invalido):
    uid = crear_usuario(conn, "ana")
    with pytest.raises(ValueError):
        db.crear_meta_ahorro(conn, uid, "Meta", monto_invalido)


def test_crear_meta_ahorro_fecha_objetivo_invalida_rechaza(conn):
    uid = crear_usuario(conn, "ana")
    with pytest.raises(ValueError):
        db.crear_meta_ahorro(conn, uid, "Meta", 100_000, fecha_objetivo="31-12-2026")


# ============================================================================
# Avance de una meta: SIEMPRE sumando movimientos.meta_ahorro_id al vuelo,
# nunca un campo separado que haya que mantener sincronizado
# ============================================================================

def test_avance_meta_solo_suma_movimientos_con_meta_ahorro_id_correspondiente(conn):
    """Caso señalado explícitamente como propenso a bugs: una meta con
    aportes propios, un gasto normal sin meta_ahorro_id, y un aporte a
    OTRA meta -- el avance solo debe contar el primero."""
    uid = crear_usuario(conn, "ana")
    meta_id = db.crear_meta_ahorro(conn, uid, "Vacaciones", 1_000_000)
    otra_meta_id = db.crear_meta_ahorro(conn, uid, "Auto", 5_000_000)

    db.insertar_movimientos(
        conn,
        [
            mov_aporte("2026-09-01", 100_000, meta_id, descripcion="Aporte a vacaciones"),
            mov("2026-09-02", "gasto", "comida", 50_000, "Gasto normal sin meta"),
            mov_aporte("2026-09-03", 200_000, otra_meta_id, descripcion="Aporte al auto"),
        ],
        origen="app_manual", usuario_id=uid,
    )

    meta = db.obtener_meta_ahorro(conn, uid, meta_id)
    assert meta["ahorrado"] == 100_000
    assert meta["restante"] == 900_000
    assert meta["porcentaje"] == 10.0

    # obtener_metas_ahorro() (todas de una pasada) debe cuadrar igual.
    metas = {m["id"]: m for m in db.obtener_metas_ahorro(conn, uid)}
    assert metas[meta_id]["ahorrado"] == 100_000
    assert metas[otra_meta_id]["ahorrado"] == 200_000


def test_avance_meta_sin_aportes_es_cero_no_none_ni_nan(conn):
    uid = crear_usuario(conn, "ana")
    meta_id = db.crear_meta_ahorro(conn, uid, "Meta nueva", 500_000)

    meta = db.obtener_meta_ahorro(conn, uid, meta_id)

    assert meta["ahorrado"] == 0.0
    assert meta["restante"] == 500_000
    assert meta["porcentaje"] == 0.0


def test_con_avance_monto_objetivo_cero_no_revienta_por_division_por_cero():
    """Guard defensivo directo sobre _con_avance(): crear_meta_ahorro() ya
    impide monto_objetivo<=0 en el flujo normal, pero el cálculo de
    porcentaje no debe depender de eso -- no debe reventar ni devolver
    NaN si alguna vez llega una fila con monto_objetivo=0 (ej. dato
    corrupto o migración vieja)."""
    resultado = db._con_avance({"monto_objetivo": 0}, ahorrado=0.0)
    assert resultado["porcentaje"] == 0.0
    assert resultado["restante"] == 0.0


def test_avance_meta_supera_objetivo_porcentaje_no_se_trunca_pero_restante_si(conn):
    uid = crear_usuario(conn, "ana")
    meta_id = db.crear_meta_ahorro(conn, uid, "Meta chica", 100_000)
    db.insertar_movimientos(
        conn, [mov_aporte("2026-09-01", 150_000, meta_id, descripcion="Superé la meta")],
        origen="app_manual", usuario_id=uid,
    )

    meta = db.obtener_meta_ahorro(conn, uid, meta_id)

    assert meta["ahorrado"] == 150_000
    assert meta["restante"] == 0.0  # nunca negativo
    assert meta["porcentaje"] == 150.0  # sí puede superar 100


def test_avance_meta_ignora_movimientos_en_moneda_distinta_de_cop(conn):
    uid = crear_usuario(conn, "ana")
    meta_id = db.crear_meta_ahorro(conn, uid, "Meta en USD", 1000)
    db.insertar_movimientos(
        conn, [mov_aporte("2026-09-01", 500, meta_id, descripcion="Aporte en USD", moneda="USD")],
        origen="app_manual", usuario_id=uid,
    )

    meta = db.obtener_meta_ahorro(conn, uid, meta_id)
    assert meta["ahorrado"] == 0.0


def test_avance_meta_suma_varios_aportes(conn):
    uid = crear_usuario(conn, "ana")
    meta_id = db.crear_meta_ahorro(conn, uid, "Vacaciones", 1_000_000)
    db.insertar_movimientos(
        conn,
        [
            mov_aporte("2026-09-01", 100_000, meta_id, descripcion="Primer aporte"),
            mov_aporte("2026-09-15", 150_000, meta_id, descripcion="Segundo aporte"),
        ],
        origen="app_manual", usuario_id=uid,
    )

    meta = db.obtener_meta_ahorro(conn, uid, meta_id)
    assert meta["ahorrado"] == 250_000


# ============================================================================
# obtener_metas_ahorro() / obtener_meta_ahorro(): aislamiento y solo_activas
# ============================================================================

def test_obtener_metas_ahorro_usuario_sin_metas_devuelve_lista_vacia(conn):
    uid = crear_usuario(conn, "ana")
    assert db.obtener_metas_ahorro(conn, uid) == []


def test_obtener_metas_ahorro_solo_activas_excluye_archivadas(conn):
    uid = crear_usuario(conn, "ana")
    activa_id = db.crear_meta_ahorro(conn, uid, "Activa", 100_000)
    archivada_id = db.crear_meta_ahorro(conn, uid, "Archivada", 100_000)
    db.archivar_meta_ahorro(conn, uid, archivada_id)

    todas = db.obtener_metas_ahorro(conn, uid, solo_activas=False)
    solo_activas = db.obtener_metas_ahorro(conn, uid, solo_activas=True)

    assert {m["id"] for m in todas} == {activa_id, archivada_id}
    assert {m["id"] for m in solo_activas} == {activa_id}


def test_obtener_metas_ahorro_aisla_entre_usuarios(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    db.crear_meta_ahorro(conn, uid1, "Meta de Ana", 100_000)
    db.crear_meta_ahorro(conn, uid2, "Meta de Beto", 200_000)

    metas_ana = db.obtener_metas_ahorro(conn, uid1)
    assert [m["nombre"] for m in metas_ana] == ["Meta de Ana"]


def test_obtener_meta_ahorro_de_otro_usuario_devuelve_none(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    mid = db.crear_meta_ahorro(conn, uid1, "Meta de Ana", 100_000)

    assert db.obtener_meta_ahorro(conn, uid2, mid) is None


def test_obtener_meta_ahorro_inexistente_devuelve_none(conn):
    uid = crear_usuario(conn, "ana")
    assert db.obtener_meta_ahorro(conn, uid, 999999) is None


# ============================================================================
# actualizar_meta_ahorro(): edición parcial (incluidas combinaciones de
# 2+ campos a la vez), validaciones y aislamiento
# ============================================================================

def test_actualizar_meta_ahorro_edicion_parcial_solo_toca_campos_presentes(conn):
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Original", 100_000, fecha_objetivo="2026-12-31")

    ok = db.actualizar_meta_ahorro(conn, uid, mid, monto_objetivo=200_000)  # solo el monto

    assert ok is True
    meta = db.obtener_meta_ahorro(conn, uid, mid)
    assert meta["monto_objetivo"] == 200_000
    assert meta["nombre"] == "Original"
    assert meta["fecha_objetivo"] == "2026-12-31"


def test_actualizar_meta_ahorro_editando_nombre_y_fecha_a_la_vez_no_ignora_ninguno(conn):
    """Combinación de 2+ parámetros: el bug real de este proyecto fue un
    filtro que se ignoraba en silencio al combinarse con otro -- acá se
    confirma que editar nombre Y fecha_objetivo JUNTOS aplica ambos, sin
    que uno pise o anule al otro, y sin tocar el monto_objetivo."""
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Original", 100_000, fecha_objetivo="2026-06-30")

    ok = db.actualizar_meta_ahorro(conn, uid, mid, nombre="Renombrada", fecha_objetivo="2026-12-31")

    assert ok is True
    meta = db.obtener_meta_ahorro(conn, uid, mid)
    assert meta["nombre"] == "Renombrada"
    assert meta["fecha_objetivo"] == "2026-12-31"
    assert meta["monto_objetivo"] == 100_000  # no tocado


def test_actualizar_meta_ahorro_string_vacio_en_fecha_limpia_el_campo(conn):
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Original", 100_000, fecha_objetivo="2026-12-31")

    db.actualizar_meta_ahorro(conn, uid, mid, fecha_objetivo="")

    meta = db.obtener_meta_ahorro(conn, uid, mid)
    assert meta["fecha_objetivo"] is None


def test_actualizar_meta_ahorro_nombre_vacio_rechaza(conn):
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Original", 100_000)
    with pytest.raises(ValueError):
        db.actualizar_meta_ahorro(conn, uid, mid, nombre="   ")


@pytest.mark.parametrize("monto_invalido", [0, -1])
def test_actualizar_meta_ahorro_monto_no_positivo_rechaza(conn, monto_invalido):
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Original", 100_000)
    with pytest.raises(ValueError):
        db.actualizar_meta_ahorro(conn, uid, mid, monto_objetivo=monto_invalido)


def test_actualizar_meta_ahorro_fecha_invalida_rechaza(conn):
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Original", 100_000)
    with pytest.raises(ValueError):
        db.actualizar_meta_ahorro(conn, uid, mid, fecha_objetivo="fecha-mala")


def test_actualizar_meta_ahorro_de_otro_usuario_devuelve_false_sin_tocar_nada(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    mid = db.crear_meta_ahorro(conn, uid1, "Meta de Ana", 100_000)

    ok = db.actualizar_meta_ahorro(conn, uid2, mid, nombre="Hackeada", monto_objetivo=999999999)

    assert ok is False
    meta = db.obtener_meta_ahorro(conn, uid1, mid)
    assert meta["nombre"] == "Meta de Ana"
    assert meta["monto_objetivo"] == 100_000


def test_actualizar_meta_ahorro_inexistente_devuelve_false(conn):
    uid = crear_usuario(conn, "ana")
    assert db.actualizar_meta_ahorro(conn, uid, 999999, nombre="x") is False


# ============================================================================
# archivar_meta_ahorro(): soft delete, conserva historial -- y a
# diferencia de borrar_meta_ahorro(), SÍ funciona con aportes asociados
# ============================================================================

def test_archivar_meta_ahorro_caso_feliz(conn):
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Vieja", 100_000)

    assert db.archivar_meta_ahorro(conn, uid, mid) is True
    assert db.obtener_meta_ahorro(conn, uid, mid)["activa"] is False


def test_archivar_meta_ahorro_con_aportes_asociados_funciona_igual(conn):
    """Mismo criterio del documento: archivar (soft delete) sí debe
    funcionar con aportes asociados -- a diferencia de borrar()."""
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Con aportes", 100_000)
    db.insertar_movimientos(
        conn, [mov_aporte("2026-09-01", 50_000, mid)], origen="app_manual", usuario_id=uid,
    )

    assert db.archivar_meta_ahorro(conn, uid, mid) is True

    meta = db.obtener_meta_ahorro(conn, uid, mid)
    assert meta["activa"] is False
    assert meta["ahorrado"] == 50_000  # el avance se sigue calculando igual


def test_archivar_meta_ahorro_no_borra_los_aportes_ya_registrados(conn):
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Vieja", 100_000)
    db.insertar_movimientos(
        conn, [mov_aporte("2026-09-01", 50_000, mid)], origen="app_manual", usuario_id=uid,
    )

    db.archivar_meta_ahorro(conn, uid, mid)

    assert len(db.obtener_movimientos(conn, usuario_id=uid)) == 1


def test_archivar_meta_ahorro_de_otro_usuario_devuelve_false(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    mid = db.crear_meta_ahorro(conn, uid1, "Meta de Ana", 100_000)

    assert db.archivar_meta_ahorro(conn, uid2, mid) is False
    assert db.obtener_meta_ahorro(conn, uid1, mid)["activa"] is True


def test_archivar_meta_ahorro_inexistente_devuelve_false(conn):
    uid = crear_usuario(conn, "ana")
    assert db.archivar_meta_ahorro(conn, uid, 999999) is False


# ============================================================================
# borrar_meta_ahorro(): borrado definitivo SOLO si nunca tuvo aportes
# (mismo criterio exacto que borrar_tarjeta())
# ============================================================================

def test_borrar_meta_ahorro_sin_aportes_la_elimina(conn):
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Sin usar", 100_000)

    ok, error = db.borrar_meta_ahorro(conn, uid, mid)

    assert ok is True
    assert error is None
    assert db.obtener_meta_ahorro(conn, uid, mid) is None


def test_borrar_meta_ahorro_con_aportes_asociados_falla_y_sugiere_archivar(conn):
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Con historial", 100_000)
    db.insertar_movimientos(
        conn, [mov_aporte("2026-09-01", 50_000, mid)], origen="app_manual", usuario_id=uid,
    )

    ok, error = db.borrar_meta_ahorro(conn, uid, mid)

    assert ok is False
    assert "archiv" in error.lower()
    assert db.obtener_meta_ahorro(conn, uid, mid) is not None  # sigue existiendo, no quedó a medio borrar


def test_borrar_meta_ahorro_de_otro_usuario_no_la_borra(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    mid = db.crear_meta_ahorro(conn, uid1, "Meta de Ana", 100_000)

    ok, error = db.borrar_meta_ahorro(conn, uid2, mid)

    assert ok is False
    assert db.obtener_meta_ahorro(conn, uid1, mid) is not None


def test_borrar_meta_ahorro_inexistente_devuelve_false(conn):
    uid = crear_usuario(conn, "ana")
    ok, error = db.borrar_meta_ahorro(conn, uid, 999999)
    assert ok is False
    assert error is not None


# ============================================================================
# insertar_movimientos() con meta_ahorro_id: respeta la misma distinción
# duplicados_bd/duplicados_lote que cualquier otra inserción -- un aporte
# duplicado no debe contarse dos veces en el avance
# ============================================================================

def test_insertar_movimientos_aporte_a_meta_duplicado_no_se_cuenta_dos_veces_en_el_avance(conn):
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Vacaciones", 1_000_000)
    aporte = mov_aporte("2026-09-01", 100_000, mid, descripcion="Aporte a vacaciones")

    db.insertar_movimientos(conn, [aporte], origen="app_manual", usuario_id=uid)
    stats = db.insertar_movimientos(conn, [dict(aporte)], origen="correo_imap", usuario_id=uid)

    assert stats["nuevos"] == 0
    assert stats["duplicados_bd"] == 1
    assert stats["duplicados_lote"] == 0

    meta = db.obtener_meta_ahorro(conn, uid, mid)
    assert meta["ahorrado"] == 100_000  # no se contó dos veces


def test_insertar_movimientos_dos_aportes_identicos_en_el_mismo_lote_se_cuentan_una_sola_vez(conn):
    """Dentro del MISMO lote, dos filas con igual fecha+moneda+monto+tipo
    se consideran duplicados_lote sin importar que la descripción
    difiera -- mismo criterio preexistente ya probado en
    tests/test_conciliacion.py::test_duplicados_lote_dentro_del_mismo_batch_sigue_funcionando,
    acá confirmado además para el avance de una meta: no debe contar el
    aporte dos veces."""
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Vacaciones", 1_000_000)

    stats = db.insertar_movimientos(
        conn,
        [
            mov_aporte("2026-09-01", 100_000, mid, descripcion="Aporte de la mañana"),
            mov_aporte("2026-09-01", 100_000, mid, descripcion="Aporte de la tarde"),
        ],
        origen="app_manual", usuario_id=uid,
    )

    assert stats["nuevos"] == 1
    assert stats["duplicados_lote"] == 1
    assert stats["duplicados_bd"] == 0
    meta = db.obtener_meta_ahorro(conn, uid, mid)
    assert meta["ahorrado"] == 100_000  # no se contó dos veces


def test_avance_meta_tras_reconciliar_por_correo_una_segunda_transaccion_real_no_se_pierde_ni_se_duplica(conn):
    """Reproduce el flujo completo de conciliación multiset (mismo patrón
    que tests/test_conciliacion.py::
    test_reconciliacion_manual_correo_segunda_transaccion_y_re_escaneo)
    aplicado a un aporte de meta: 1) aporte cargado a mano, 2) esa MISMA
    transacción real llega por correo y concilia (0 nuevos), 3) una
    SEGUNDA transacción real, distinta, mismo día y monto, en una
    llamada separada -- sí se inserta como nueva. El avance final debe
    reflejar los DOS aportes reales, ninguno perdido ni contado doble."""
    uid = crear_usuario(conn, "ana")
    mid = db.crear_meta_ahorro(conn, uid, "Vacaciones", 1_000_000)

    db.insertar_movimientos(
        conn, [mov_aporte("2026-09-06", 100_000, mid, descripcion="Aporte manual")],
        origen="app_manual", usuario_id=uid,
    )
    stats1 = db.insertar_movimientos(
        conn, [mov_aporte("2026-09-06", 100_000, mid,
                           descripcion="Transferiste $100.000.00 de tu cuenta *5360 a *1234")],
        origen="correo_imap", usuario_id=uid,
    )
    assert stats1["nuevos"] == 0
    assert stats1["duplicados_bd"] == 1

    stats2 = db.insertar_movimientos(
        conn, [mov_aporte("2026-09-06", 100_000, mid,
                           descripcion="Transferiste $100.000.00 de tu cuenta *5360 a *9999")],
        origen="correo_imap", usuario_id=uid,
    )
    assert stats2["nuevos"] == 1

    meta = db.obtener_meta_ahorro(conn, uid, mid)
    assert meta["ahorrado"] == 200_000


# ============================================================================
# _migrar_columna_meta_ahorro_id(): idempotente sobre una BD vieja, y las
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


def test_migrar_columna_meta_ahorro_id_agrega_tabla_y_columna_a_bd_vieja(conn_sin_esquema):
    conn = conn_sin_esquema
    _crear_tabla_movimientos_vieja(conn)
    columnas_antes = [r["name"] for r in conn.execute("PRAGMA table_info(movimientos)")]
    assert "meta_ahorro_id" not in columnas_antes

    db.crear_esquema(conn)  # crea metas_ahorro Y agrega la columna, en ese orden

    columnas_despues = [r["name"] for r in conn.execute("PRAGMA table_info(movimientos)")]
    assert "meta_ahorro_id" in columnas_despues
    tablas = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert "metas_ahorro" in tablas

    # Idempotencia: correrlo de nuevo no debe romper nada ni duplicar la columna.
    db.crear_esquema(conn)
    columnas_final = [r["name"] for r in conn.execute("PRAGMA table_info(movimientos)")]
    assert columnas_final.count("meta_ahorro_id") == 1


def test_movimientos_historicos_preexistentes_quedan_con_meta_ahorro_id_null_tras_migrar(conn_sin_esquema):
    """Movimientos ya cargados ANTES de esta feature nunca se reasignan
    retroactivamente a ninguna meta -- mismo criterio exacto que
    _migrar_columna_tarjeta_id()."""
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
        "es_deuda, usuario_id) VALUES ('2026-01-01', 'gasto', 'ahorro', 'COP', 50000, "
        "'Aporte viejo a un ahorro', 'Bancolombia', 'debito', 0, 1)"
    )
    conn.commit()

    db.crear_esquema(conn)  # corre la migración de meta_ahorro_id sobre la fila ya existente

    fila = conn.execute("SELECT meta_ahorro_id FROM movimientos WHERE id = 1").fetchone()
    assert fila["meta_ahorro_id"] is None

    # Crear HOY una meta no reasigna el histórico -- no existe ninguna función que lo haga.
    db.crear_meta_ahorro(conn, usuario_id=1, nombre="Meta nueva", monto_objetivo=100_000)
    fila = conn.execute("SELECT meta_ahorro_id FROM movimientos WHERE id = 1").fetchone()
    assert fila["meta_ahorro_id"] is None
