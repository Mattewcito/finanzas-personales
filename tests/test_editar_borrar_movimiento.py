"""
Pruebas de editar/borrar un movimiento individual (2026-09-07, ver
requisitos/2026-09-07_editar-borrar-movimiento.md):

- db_finanzas.py: obtener_movimiento, editar_movimiento, borrar_movimiento,
  advertencia_riesgo_movimiento, y el campo nuevo tarjeta_id en
  obtener_movimientos().
- routes/dashboard.py: POST /api/movimiento/<id>/editar,
  POST /api/movimiento/<id>/borrar, y la regresión del bug de conciliación
  (origen="manual" -> origen="app_manual" en api_registrar_movimiento).

Dos secciones con aislamiento de BD distinto:
  1) Pruebas puras de db_finanzas (sin Flask), con una fixture `conn`
     propia en tmp_path -- mismo patrón que tests/test_conciliacion.py.
  2) Pruebas HTTP, reutilizando las fixtures app_ctx/client/login de
     tests/test_app_integration.py -- "import app" solo puede pasar en ese
     archivo en toda la corrida (ver su docstring), mismo patrón ya usado
     en tests/test_tarjetas_routes.py.
"""
import pytest

import db_finanzas as db

from test_app_integration import app_ctx, client, login  # noqa: F401 (fixtures reutilizadas)


# ============================================================================
# Sección 1: pruebas puras de db_finanzas (sin Flask)
# ============================================================================

@pytest.fixture
def conn(tmp_path, monkeypatch):
    """BD aislada en tmp_path, con el esquema ya creado -- mismo patrón que
    tests/test_conciliacion.py. Independiente de app_ctx/client (esta
    fixture NO importa app.py)."""
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


def insertar_uno(conn, usuario_id, origen="app_manual", **campos):
    """Inserta un único movimiento nuevo y devuelve su fila completa (con
    id) -- falla ruidosamente si por algún motivo terminó conciliándose en
    vez de insertarse como nuevo (no debería pasar con los datos de
    prueba usados acá, pero así no se enmascara un fallo real)."""
    defaults = dict(
        fecha="2026-09-01", tipo="gasto", categoria="otros", moneda="COP",
        monto=10000, descripcion="Movimiento de prueba", entidad="Test",
    )
    defaults.update(campos)
    ids_antes = {f["id"] for f in db.obtener_movimientos(conn, usuario_id=usuario_id)}
    stats = db.insertar_movimientos(conn, [defaults], origen=origen, usuario_id=usuario_id)
    assert stats["nuevos"] == 1, f"insertar_uno esperaba insertar un nuevo movimiento, stats={stats}"
    nuevas = [f for f in db.obtener_movimientos(conn, usuario_id=usuario_id) if f["id"] not in ids_antes]
    assert len(nuevas) == 1
    return nuevas[0]


# ----------------------------------------------------------------------
# obtener_movimiento()
# ----------------------------------------------------------------------

def test_obtener_movimiento_caso_feliz(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, descripcion="Almuerzo")

    encontrado = db.obtener_movimiento(conn, uid, fila["id"])

    assert encontrado is not None
    assert encontrado["descripcion"] == "Almuerzo"


def test_obtener_movimiento_ajeno_devuelve_none(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    fila = insertar_uno(conn, uid1)

    assert db.obtener_movimiento(conn, uid2, fila["id"]) is None


def test_obtener_movimiento_inexistente_devuelve_none(conn):
    uid = crear_usuario(conn, "ana")
    assert db.obtener_movimiento(conn, uid, 999999) is None


# ----------------------------------------------------------------------
# editar_movimiento(): existencia / aislamiento
# ----------------------------------------------------------------------

def test_editar_movimiento_inexistente_da_ok_false_sin_reventar(conn):
    uid = crear_usuario(conn, "ana")

    resultado = db.editar_movimiento(conn, uid, 999999, {"descripcion": "x"})

    assert resultado["ok"] is False
    assert resultado["reclasificado"] is False
    assert resultado["requiere_confirmacion"] is False


def test_editar_movimiento_ajeno_da_ok_false_y_no_lo_toca(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    fila = insertar_uno(conn, uid1, descripcion="Original")

    resultado = db.editar_movimiento(conn, uid2, fila["id"], {"descripcion": "Hackeado"})

    assert resultado["ok"] is False
    intacto = db.obtener_movimiento(conn, uid1, fila["id"])
    assert intacto["descripcion"] == "Original"


def test_editar_usuario_recien_creado_sin_movimientos_da_ok_false_sin_reventar(conn):
    """Caso disperso: un usuario sin ningún movimiento cargado todavía
    intentando editar cualquier id no debe reventar."""
    uid = crear_usuario(conn, "ana")
    resultado = db.editar_movimiento(conn, uid, 1, {"descripcion": "x"})
    assert resultado["ok"] is False


# ----------------------------------------------------------------------
# editar_movimiento(): campos descriptivos siempre libres
# ----------------------------------------------------------------------

def test_editar_campo_descriptivo_en_movimiento_manual_sin_conciliar_no_exige_confirmacion(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, descripcion="Almuerzo", categoria="comida")

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"categoria": "restaurantes", "entidad": "Rappi"})

    assert resultado["ok"] is True
    assert resultado["requiere_confirmacion"] is False
    actualizado = db.obtener_movimiento(conn, uid, fila["id"])
    assert actualizado["categoria"] == "restaurantes"
    assert actualizado["entidad"] == "Rappi"


def test_editar_campo_descriptivo_en_movimiento_conciliado_no_exige_confirmacion(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, descripcion="Almuerzo", categoria="comida")
    conn.execute("UPDATE movimientos SET referencia_bancaria = ? WHERE id = ?", ("Transferiste...", fila["id"]))
    conn.commit()

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"categoria": "restaurantes"})

    assert resultado["ok"] is True
    assert resultado["requiere_confirmacion"] is False
    actualizado = db.obtener_movimiento(conn, uid, fila["id"])
    assert actualizado["categoria"] == "restaurantes"
    assert actualizado["referencia_bancaria"] == "Transferiste..."  # sigue conciliado, no se toca


def test_editar_campo_descriptivo_en_movimiento_de_origen_automatico_no_exige_confirmacion(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, origen="correo_imap", descripcion="Compra en tienda")

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"entidad": "Tienda X"})

    assert resultado["ok"] is True
    assert resultado["requiere_confirmacion"] is False


# ----------------------------------------------------------------------
# editar_movimiento(): campos de identidad (fecha/monto/tipo/moneda)
# ----------------------------------------------------------------------

def test_editar_campo_identidad_en_movimiento_manual_sin_conciliar_se_aplica_sin_advertencia(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, monto=10000)

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"monto": "20000"})

    assert resultado["ok"] is True
    assert resultado["requiere_confirmacion"] is False
    assert db.obtener_movimiento(conn, uid, fila["id"])["monto"] == 20000


def test_editar_campo_identidad_en_movimiento_conciliado_sin_confirmar_riesgo_es_rechazado(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, monto=10000, descripcion="Almuerzo")
    conn.execute("UPDATE movimientos SET referencia_bancaria = ? WHERE id = ?", ("ref", fila["id"]))
    conn.commit()

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"monto": "99999"})

    assert resultado["ok"] is False
    assert resultado["requiere_confirmacion"] is True
    intacto = db.obtener_movimiento(conn, uid, fila["id"])
    assert intacto["monto"] == 10000
    assert intacto["referencia_bancaria"] == "ref"


def test_editar_identidad_sin_confirmar_rechaza_todo_el_cambio_no_solo_el_campo_de_identidad(conn):
    """Nunca una edición parcial a medias por falta de confirmación -- ni
    siquiera los campos descriptivos que vinieran en el mismo pedido se
    aplican."""
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, monto=10000, categoria="comida", descripcion="Almuerzo")
    conn.execute("UPDATE movimientos SET referencia_bancaria = ? WHERE id = ?", ("ref", fila["id"]))
    conn.commit()

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"monto": "99999", "categoria": "restaurantes"})

    assert resultado["ok"] is False
    intacto = db.obtener_movimiento(conn, uid, fila["id"])
    assert intacto["categoria"] == "comida"  # tampoco se aplicó, aunque vino en el mismo pedido
    assert intacto["monto"] == 10000


def test_editar_campo_identidad_en_movimiento_conciliado_confirmado_limpia_referencia_bancaria(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, monto=10000)
    conn.execute("UPDATE movimientos SET referencia_bancaria = ? WHERE id = ?", ("ref", fila["id"]))
    conn.commit()

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"monto": "99999", "confirmar_riesgo": True})

    assert resultado["ok"] is True
    actualizado = db.obtener_movimiento(conn, uid, fila["id"])
    assert actualizado["monto"] == 99999
    assert actualizado["referencia_bancaria"] is None


def test_editar_campo_identidad_en_movimiento_de_origen_automatico_sin_confirmar_es_rechazado(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, origen="correo_imap", monto=10000)

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"monto": "50000"})

    assert resultado["ok"] is False
    assert resultado["requiere_confirmacion"] is True


def test_editar_campo_identidad_en_movimiento_de_origen_automatico_confirmado_se_aplica(conn):
    """A diferencia del caso conciliado, acá no hay referencia_bancaria
    que limpiar -- el movimiento en sí ES el registro de la fuente
    automática."""
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, origen="correo_imap", monto=10000)

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"monto": "50000", "confirmar_riesgo": True})

    assert resultado["ok"] is True
    actualizado = db.obtener_movimiento(conn, uid, fila["id"])
    assert actualizado["monto"] == 50000
    assert actualizado["referencia_bancaria"] is None  # no había nada que limpiar


def test_reenviar_formulario_completo_con_identidad_igual_no_exige_confirmacion(conn):
    """El gate se dispara por VALOR final distinto, no por la mera
    presencia de la clave -- el modal de edición precarga y reenvía TODOS
    los campos del movimiento, así que reenviar fecha/monto/tipo/moneda
    IGUALES junto con una descripción distinta nunca debe exigir
    confirmar_riesgo, ni siquiera sobre un movimiento conciliado."""
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, fecha="2026-09-01", tipo="gasto", monto=10000, moneda="COP", descripcion="Almuerzo")
    conn.execute("UPDATE movimientos SET referencia_bancaria = ? WHERE id = ?", ("ref", fila["id"]))
    conn.commit()

    resultado = db.editar_movimiento(conn, uid, fila["id"], {
        "fecha": "2026-09-01", "tipo": "gasto", "monto": "10000", "moneda": "COP",
        "descripcion": "Almuerzo con amigos",
    })

    assert resultado["ok"] is True
    assert resultado["requiere_confirmacion"] is False
    actualizado = db.obtener_movimiento(conn, uid, fila["id"])
    assert actualizado["descripcion"] == "Almuerzo con amigos"
    assert actualizado["referencia_bancaria"] == "ref"  # sin cambio real de identidad, no se limpia


def test_editar_varios_campos_identidad_con_alguno_igual_y_otro_distinto_exige_confirmacion(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, fecha="2026-09-01", tipo="gasto", monto=10000, moneda="COP")
    conn.execute("UPDATE movimientos SET referencia_bancaria = ? WHERE id = ?", ("ref", fila["id"]))
    conn.commit()

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"fecha": "2026-09-01", "monto": "20000"})

    assert resultado["ok"] is False
    assert resultado["requiere_confirmacion"] is True


def test_confirmar_riesgo_true_en_movimiento_que_no_lo_necesitaba_no_causa_efectos_raros(conn):
    """Combinación olvidable: mandar confirmar_riesgo=True de más (sobre
    un cambio puramente descriptivo) no debe romper nada ni marcarlo como
    'requirió confirmación'."""
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, categoria="comida")

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"categoria": "restaurantes", "confirmar_riesgo": True})

    assert resultado["ok"] is True
    assert resultado["requiere_confirmacion"] is False


def test_editar_monto_con_diferencia_menor_a_un_peso_no_cuenta_como_cambio_de_identidad(conn):
    """round() decide si el monto 'cambió' -- una diferencia de centavos
    no debe disparar el gate de confirmar_riesgo sobre un movimiento
    conciliado."""
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, monto=10000)
    conn.execute("UPDATE movimientos SET referencia_bancaria = ? WHERE id = ?", ("ref", fila["id"]))
    conn.commit()

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"monto": "10000.40"})

    assert resultado["ok"] is True
    assert resultado["requiere_confirmacion"] is False


# ----------------------------------------------------------------------
# editar_movimiento(): validaciones básicas (se evalúan ANTES del gate)
# ----------------------------------------------------------------------

def test_editar_movimiento_con_fecha_vacia_da_error(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid)
    resultado = db.editar_movimiento(conn, uid, fila["id"], {"fecha": "   "})
    assert resultado["ok"] is False


def test_editar_movimiento_con_descripcion_vacia_da_error(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid)
    resultado = db.editar_movimiento(conn, uid, fila["id"], {"descripcion": ""})
    assert resultado["ok"] is False


def test_editar_movimiento_con_monto_no_numerico_da_error(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid)
    resultado = db.editar_movimiento(conn, uid, fila["id"], {"monto": "no-es-un-numero"})
    assert resultado["ok"] is False


def test_editar_movimiento_con_monto_cero_o_negativo_da_error(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid)
    for monto in ("0", "-500"):
        resultado = db.editar_movimiento(conn, uid, fila["id"], {"monto": monto})
        assert resultado["ok"] is False


def test_editar_movimiento_sin_cambios_no_rompe_y_no_altera_nada(conn):
    """Caso disperso: cambios={} (form vacío) debe comportarse como un
    no-op válido, no reventar."""
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, categoria="comida", descripcion="Almuerzo")

    resultado = db.editar_movimiento(conn, uid, fila["id"], {})

    assert resultado["ok"] is True
    assert resultado["reclasificado"] is False
    actualizado = db.obtener_movimiento(conn, uid, fila["id"])
    assert actualizado["descripcion"] == "Almuerzo"
    assert actualizado["categoria"] == "comida"


# ----------------------------------------------------------------------
# editar_movimiento(): reclasificación de medio_pago/es_deuda
# ----------------------------------------------------------------------

def test_reclasificacion_al_agregar_tcred_en_descripcion_se_reporta(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, tipo="gasto", descripcion="Compra en tienda", categoria="compras")
    assert fila["medio_pago"] == "debito"
    assert fila["es_deuda"] is False

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"descripcion": "Compra en tienda con T.Cred *1111"})

    assert resultado["ok"] is True
    assert resultado["reclasificado"] is True
    assert resultado["medio_pago_anterior"] == "debito"
    assert resultado["medio_pago_nuevo"] == "credito"
    assert resultado["es_deuda_anterior"] is False
    assert resultado["es_deuda_nuevo"] is True
    actualizado = db.obtener_movimiento(conn, uid, fila["id"])
    assert actualizado["medio_pago"] == "credito"
    assert actualizado["es_deuda"] is True


def test_reclasificacion_al_quitar_tcred_de_descripcion_tambien_se_reporta(conn):
    """Caso inverso: quitar 'T.Cred' de la descripción hace que un
    movimiento deje de contar como deuda -- también debe reportarse, no
    solo el sentido de 'empieza a ser deuda'."""
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, tipo="gasto", descripcion="Compra con T.Cred *1111", categoria="compras")
    assert fila["es_deuda"] is True

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"descripcion": "Compra en tienda"})

    assert resultado["ok"] is True
    assert resultado["reclasificado"] is True
    assert resultado["medio_pago_nuevo"] == "debito"
    assert resultado["es_deuda_nuevo"] is False


def test_sin_cambio_de_clasificacion_no_reporta_reclasificado(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, descripcion="Almuerzo")

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"categoria": "restaurantes"})

    assert resultado["reclasificado"] is False


# ----------------------------------------------------------------------
# editar_movimiento(): tarjeta_id nunca se re-infiere por texto
# ----------------------------------------------------------------------

def test_editar_descripcion_con_ultimos4_de_tarjeta_no_reasigna_tarjeta_id(conn):
    uid = crear_usuario(conn, "ana")
    db.crear_tarjeta(conn, uid, "Visa", 500000, ultimos4="2011")
    fila = insertar_uno(conn, uid, descripcion="Compra en tienda")  # sin tarjeta_id
    assert fila["tarjeta_id"] is None

    resultado = db.editar_movimiento(conn, uid, fila["id"], {
        "descripcion": "Compra con T.Cred *2011",  # matchearía por últimos4 si se re-infiriera al insertar
    })

    assert resultado["ok"] is True
    actualizado = db.obtener_movimiento(conn, uid, fila["id"])
    assert actualizado["tarjeta_id"] is None  # sigue sin asignar: nunca se adivina al editar


def test_editar_tarjeta_id_explicito_valido_la_asigna(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Visa", 500000)
    fila = insertar_uno(conn, uid)

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"tarjeta_id": tid})

    assert resultado["ok"] is True
    assert db.obtener_movimiento(conn, uid, fila["id"])["tarjeta_id"] == tid


def test_editar_tarjeta_id_vacio_desasigna_explicitamente(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Visa", 100000)
    fila = insertar_uno(conn, uid, tarjeta_id=tid)
    assert fila["tarjeta_id"] == tid

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"tarjeta_id": ""})

    assert resultado["ok"] is True
    assert db.obtener_movimiento(conn, uid, fila["id"])["tarjeta_id"] is None


def test_editar_tarjeta_id_no_parseable_da_error(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid)
    resultado = db.editar_movimiento(conn, uid, fila["id"], {"tarjeta_id": "no-es-un-id"})
    assert resultado["ok"] is False


def test_editar_tarjeta_id_de_otro_usuario_es_rechazado_y_no_la_asigna(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    tid_ajena = db.crear_tarjeta(conn, uid2, "Del otro", 100000)
    fila = insertar_uno(conn, uid1)

    resultado = db.editar_movimiento(conn, uid1, fila["id"], {"tarjeta_id": tid_ajena})

    assert resultado["ok"] is False
    assert db.obtener_movimiento(conn, uid1, fila["id"])["tarjeta_id"] is None


def test_editar_tarjeta_id_a_una_archivada_distinta_es_rechazado(conn):
    uid = crear_usuario(conn, "ana")
    tid_archivada = db.crear_tarjeta(conn, uid, "Vieja", 500000)
    db.archivar_tarjeta(conn, uid, tid_archivada)
    fila = insertar_uno(conn, uid)  # sin tarjeta asignada

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"tarjeta_id": tid_archivada})

    assert resultado["ok"] is False
    assert db.obtener_movimiento(conn, uid, fila["id"])["tarjeta_id"] is None


def test_editar_manteniendo_la_misma_tarjeta_ya_archivada_no_la_desasigna(conn):
    """No se fuerza a des-asignar una tarjeta archivada solo por reenviar
    el mismo tarjeta_id que ya tenía (mismo criterio que
    actualizar_tarjeta() con campos no tocados)."""
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Se va a archivar", 500000)
    fila = insertar_uno(conn, uid, tarjeta_id=tid)
    db.archivar_tarjeta(conn, uid, tid)

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"tarjeta_id": tid, "categoria": "otros"})

    assert resultado["ok"] is True
    assert db.obtener_movimiento(conn, uid, fila["id"])["tarjeta_id"] == tid


# ----------------------------------------------------------------------
# editar_movimiento(): moneda y deuda (riesgo aritmético del documento)
# ----------------------------------------------------------------------

def test_editar_moneda_de_movimiento_de_deuda_sin_conciliar_no_exige_confirmacion_y_actualiza_ledger(conn):
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Visa", 500000)
    fila = insertar_uno(conn, uid, tipo="gasto", moneda="COP", monto=50000,
                         descripcion="Compra con T.Cred *1111", tarjeta_id=tid)
    assert db.obtener_tarjetas_con_deuda(conn, uid)["activas"][0]["deuda_actual"] == 50000

    resultado = db.editar_movimiento(conn, uid, fila["id"], {"moneda": "USD"})

    assert resultado["ok"] is True
    # v_deuda/obtener_tarjetas_con_deuda filtran moneda='COP' a propósito
    assert db.obtener_tarjetas_con_deuda(conn, uid)["activas"][0]["deuda_actual"] == 0.0


def test_editar_moneda_de_movimiento_de_deuda_conciliado_requiere_confirmacion_y_luego_actualiza_ledger(conn):
    """Caso de alto riesgo aritmético del documento de requisitos: cambiar
    moneda COP<->USD en un movimiento de deuda YA conciliado exige
    confirmar_riesgo (es campo de identidad) y, una vez confirmado, saca
    la deuda del desglose por tarjeta."""
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Visa", 500000)
    fila = insertar_uno(conn, uid, tipo="gasto", moneda="COP", monto=50000,
                         descripcion="Compra con T.Cred *1111", tarjeta_id=tid)
    conn.execute("UPDATE movimientos SET referencia_bancaria = ? WHERE id = ?", ("ref", fila["id"]))
    conn.commit()

    rechazado = db.editar_movimiento(conn, uid, fila["id"], {"moneda": "USD"})
    assert rechazado["ok"] is False
    assert rechazado["requiere_confirmacion"] is True
    assert db.obtener_tarjetas_con_deuda(conn, uid)["activas"][0]["deuda_actual"] == 50000  # sin cambios

    confirmado = db.editar_movimiento(conn, uid, fila["id"], {"moneda": "USD", "confirmar_riesgo": True})
    assert confirmado["ok"] is True
    assert db.obtener_tarjetas_con_deuda(conn, uid)["activas"][0]["deuda_actual"] == 0.0


# ----------------------------------------------------------------------
# borrar_movimiento()
# ----------------------------------------------------------------------

def test_borrar_movimiento_caso_feliz(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid)

    assert db.borrar_movimiento(conn, uid, fila["id"]) is True
    assert db.obtener_movimiento(conn, uid, fila["id"]) is None


def test_borrar_movimiento_ajeno_devuelve_false_y_no_lo_borra(conn):
    uid1 = crear_usuario(conn, "ana")
    uid2 = crear_usuario(conn, "beto")
    fila = insertar_uno(conn, uid1)

    assert db.borrar_movimiento(conn, uid2, fila["id"]) is False
    assert db.obtener_movimiento(conn, uid1, fila["id"]) is not None


def test_borrar_movimiento_inexistente_devuelve_false(conn):
    uid = crear_usuario(conn, "ana")
    assert db.borrar_movimiento(conn, uid, 999999) is False


def test_borrar_movimiento_usuario_recien_creado_sin_movimientos_no_rompe(conn):
    """Caso disperso: borrar sobre una cuenta con 0 movimientos no debe
    reventar (mismo espíritu que los tests de dataset vacío del resto del
    proyecto)."""
    uid = crear_usuario(conn, "ana")
    assert db.borrar_movimiento(conn, uid, 1) is False


# ----------------------------------------------------------------------
# advertencia_riesgo_movimiento()
# ----------------------------------------------------------------------

def test_advertencia_riesgo_movimiento_manual_sin_conciliar_es_none(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, origen="app_manual")
    assert db.advertencia_riesgo_movimiento(fila) is None


def test_advertencia_riesgo_movimiento_conciliado_es_generica(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, origen="app_manual")
    fila["referencia_bancaria"] = "ref"

    advertencia = db.advertencia_riesgo_movimiento(fila)

    assert advertencia is not None
    assert "conciliado" in advertencia.lower()


def test_advertencia_riesgo_movimiento_origen_automatico_sin_conciliar_es_generica(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, origen="correo_imap")
    assert db.advertencia_riesgo_movimiento(fila) is not None


def test_advertencia_riesgo_movimiento_gmail_bot_excel_menciona_actualizar_dashboard(conn):
    uid = crear_usuario(conn, "ana")
    fila = insertar_uno(conn, uid, origen="gmail_bot_excel")

    advertencia = db.advertencia_riesgo_movimiento(fila)

    assert advertencia is not None
    assert "actualizar_dashboard" in advertencia


# ----------------------------------------------------------------------
# obtener_movimientos(): tarjeta_id
# ----------------------------------------------------------------------

def test_obtener_movimientos_incluye_tarjeta_id_asignado_y_none_si_no_hay(conn):
    """fecha/monto distintos entre las dos inserciones a propósito -- con
    los mismos valores, el motor de conciliación (mismo día+monto+tipo)
    trataría la segunda como duplicado de la primera en vez de insertarla
    como una fila nueva."""
    uid = crear_usuario(conn, "ana")
    tid = db.crear_tarjeta(conn, uid, "Visa", 500000)
    con_tarjeta = insertar_uno(conn, uid, descripcion="Con tarjeta", monto=10000, tarjeta_id=tid)
    sin_tarjeta = insertar_uno(conn, uid, descripcion="Sin tarjeta", monto=20000)

    assert con_tarjeta["tarjeta_id"] == tid
    assert sin_tarjeta["tarjeta_id"] is None


def test_obtener_movimientos_usuario_sin_movimientos_devuelve_lista_vacia(conn):
    uid = crear_usuario(conn, "ana")
    assert db.obtener_movimientos(conn, usuario_id=uid) == []


# ============================================================================
# Sección 2: pruebas HTTP (routes/dashboard.py), reutilizando
# app_ctx/client/login de test_app_integration.py
# ============================================================================

def _registrar(client, **overrides):
    """POST /api/registrar-movimiento con datos válidos por default."""
    datos = {
        "fecha": "2026-09-01", "tipo": "gasto", "monto": "20000",
        "descripcion": "Compra en tienda", "categoria": "compras",
        "moneda": "COP", "entidad": "Tienda",
    }
    datos.update(overrides)
    return client.post("/api/registrar-movimiento", data=datos)


def _unico_movimiento_id(usuario_id):
    conn = db.conectar()
    filas = db.obtener_movimientos(conn, usuario_id=usuario_id)
    conn.close()
    assert len(filas) == 1, f"se esperaba exactamente un movimiento, hay {len(filas)}"
    return filas[0]["id"]


def _marcar_conciliado(movimiento_id, referencia="ref-bancaria"):
    conn = db.conectar()
    conn.execute("UPDATE movimientos SET referencia_bancaria = ? WHERE id = ?", (referencia, movimiento_id))
    conn.commit()
    conn.close()


# ----------------------------------------------------------------------
# Regresión del bug de conciliación (origen="manual" -> "app_manual")
# ----------------------------------------------------------------------

def test_regresion_movimiento_manual_via_http_se_concilia_con_automatico_posterior(client, app_ctx):
    """Bug de producción corregido 2026-09-07 (ver requisitos): antes,
    api_registrar_movimiento pasaba origen='manual' a insertar_movimientos(),
    pero TODA la lógica de conciliación compara contra el literal exacto
    'app_manual' -- así que un movimiento cargado a mano por un usuario
    real nunca disparaba la rama de conciliación cuando el banco
    confirmaba esa misma transacción por correo/PDF/Excel. Este test
    falla si el literal vuelve a desalinearse en el futuro."""
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")

    resp = client.post("/api/registrar-movimiento", data={
        "fecha": "2026-09-06", "tipo": "gasto", "monto": "30000",
        "descripcion": "almuerzo", "categoria": "comida",
        "moneda": "COP", "entidad": "Manual",
    })
    assert resp.get_json()["nuevos"] == 1

    conn = db.conectar()
    stats = db.insertar_movimientos(
        conn,
        [{"fecha": "2026-09-06", "tipo": "gasto", "categoria": "transferencias", "moneda": "COP",
          "monto": 30000, "descripcion": "Transferiste $30.000.00 de tu cuenta *5360",
          "entidad": "Bancolombia"}],
        origen="correo_imap", usuario_id=admin_id,
    )
    assert stats["nuevos"] == 0
    assert stats["duplicados_bd"] == 1

    filas = db.obtener_movimientos(conn, usuario_id=admin_id)
    conn.close()
    assert len(filas) == 1
    fila = filas[0]
    assert fila["origen"] == "app_manual"
    assert fila["descripcion"] == "almuerzo"  # descripción original preservada
    assert fila["referencia_bancaria"] == "Transferiste $30.000.00 de tu cuenta *5360"


# ----------------------------------------------------------------------
# POST /api/movimiento/<id>/editar
# ----------------------------------------------------------------------

def test_editar_movimiento_redirige_a_login_sin_sesion(client):
    resp = client.post("/api/movimiento/1/editar", data={"categoria": "otros"})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_editar_movimiento_inexistente_da_404(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/movimiento/999999/editar", data={"categoria": "otros"})
    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False


def test_editar_movimiento_de_otro_usuario_da_404_y_no_lo_toca(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.insertar_movimientos(
        conn,
        [{"fecha": "2026-09-01", "tipo": "gasto", "categoria": "otros", "moneda": "COP",
          "monto": 5000, "descripcion": "Del usuario", "entidad": "Test"}],
        origen="app_manual", usuario_id=user_id,
    )
    mov_id = db.obtener_movimientos(conn, usuario_id=user_id)[0]["id"]
    conn.close()

    login(client, "admin_test", "clave-admin-123")  # admin viendo SU propio perfil, no el del usuario
    resp = client.post(f"/api/movimiento/{mov_id}/editar", data={"categoria": "otros2"})

    assert resp.status_code == 404
    conn = db.conectar()
    assert db.obtener_movimiento(conn, user_id, mov_id)["categoria"] == "otros"
    conn.close()


def test_editar_campo_descriptivo_via_http_sin_advertencia(client, app_ctx):
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")
    _registrar(client)
    mov_id = _unico_movimiento_id(admin_id)

    resp = client.post(f"/api/movimiento/{mov_id}/editar", data={"categoria": "otros"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["requiere_confirmacion"] is False


def test_editar_campo_descriptivo_en_movimiento_conciliado_via_http_no_exige_confirmacion(client, app_ctx):
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")
    _registrar(client, descripcion="almuerzo", categoria="comida")
    mov_id = _unico_movimiento_id(admin_id)
    _marcar_conciliado(mov_id)

    resp = client.post(f"/api/movimiento/{mov_id}/editar", data={"categoria": "restaurantes"})

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_editar_campo_identidad_en_movimiento_conciliado_sin_confirmar_da_400_con_advertencia(client, app_ctx):
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")
    _registrar(client, monto="20000")
    mov_id = _unico_movimiento_id(admin_id)
    _marcar_conciliado(mov_id)

    resp = client.post(f"/api/movimiento/{mov_id}/editar", data={"monto": "99999"})

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert body["requiere_confirmacion"] is True
    assert body["advertencia"] is not None


def test_editar_campo_identidad_en_movimiento_conciliado_con_confirmar_riesgo_true_aplica_y_limpia_referencia(client, app_ctx):
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")
    _registrar(client, monto="20000")
    mov_id = _unico_movimiento_id(admin_id)
    _marcar_conciliado(mov_id)

    resp = client.post(f"/api/movimiento/{mov_id}/editar", data={"monto": "99999", "confirmar_riesgo": "true"})

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    conn = db.conectar()
    fila = db.obtener_movimiento(conn, admin_id, mov_id)
    conn.close()
    assert fila["monto"] == 99999
    assert fila["referencia_bancaria"] is None


def test_editar_movimiento_de_origen_gmail_bot_excel_incluye_advertencia_especifica(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    db.insertar_movimientos(
        conn,
        [{"fecha": "2026-09-01", "tipo": "gasto", "categoria": "otros", "moneda": "COP",
          "monto": 15000, "descripcion": "Del excel legado", "entidad": "Bot"}],
        origen="gmail_bot_excel", usuario_id=admin_id,
    )
    mov_id = db.obtener_movimientos(conn, usuario_id=admin_id)[0]["id"]
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/movimiento/{mov_id}/editar", data={"categoria": "restaurantes"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert "actualizar_dashboard" in body["advertencia"]


def test_editar_descripcion_via_http_reporta_reclasificacion(client, app_ctx):
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")
    _registrar(client, descripcion="Compra en tienda")
    mov_id = _unico_movimiento_id(admin_id)

    resp = client.post(f"/api/movimiento/{mov_id}/editar", data={
        "descripcion": "Compra en tienda con T.Cred *1111",
    })

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["reclasificado"] is True
    assert body["medio_pago_nuevo"] == "credito"


def test_editar_movimiento_asignando_tarjeta_activa_via_http(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    tid = db.crear_tarjeta(conn, admin_id, "Visa", 500000)
    conn.close()
    login(client, "admin_test", "clave-admin-123")
    _registrar(client)
    mov_id = _unico_movimiento_id(admin_id)

    resp = client.post(f"/api/movimiento/{mov_id}/editar", data={"tarjeta_id": str(tid)})

    assert resp.status_code == 200
    conn = db.conectar()
    assert db.obtener_movimiento(conn, admin_id, mov_id)["tarjeta_id"] == tid
    conn.close()


def test_editar_movimiento_opera_sobre_viendo_id_no_sobre_la_sesion_del_admin(client, app_ctx):
    """Un admin viendo el perfil de otro usuario edita los movimientos de
    ESA cuenta, no los propios."""
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.insertar_movimientos(
        conn,
        [{"fecha": "2026-09-01", "tipo": "gasto", "categoria": "otros", "moneda": "COP",
          "monto": 5000, "descripcion": "Del usuario", "entidad": "Test"}],
        origen="app_manual", usuario_id=user_id,
    )
    mov_id = db.obtener_movimientos(conn, usuario_id=user_id)[0]["id"]
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})

    resp = client.post(f"/api/movimiento/{mov_id}/editar", data={"categoria": "otros2"})

    assert resp.status_code == 200
    conn = db.conectar()
    assert db.obtener_movimiento(conn, user_id, mov_id)["categoria"] == "otros2"
    conn.close()


# ----------------------------------------------------------------------
# POST /api/movimiento/<id>/borrar
# ----------------------------------------------------------------------

def test_borrar_movimiento_redirige_a_login_sin_sesion(client):
    resp = client.post("/api/movimiento/1/borrar", data={"confirmar": "true"})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_borrar_movimiento_inexistente_da_404(client):
    login(client, "admin_test", "clave-admin-123")
    resp = client.post("/api/movimiento/999999/borrar", data={"confirmar": "true"})
    assert resp.status_code == 404


def test_borrar_movimiento_de_otro_usuario_da_404_y_no_lo_borra(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.insertar_movimientos(
        conn,
        [{"fecha": "2026-09-01", "tipo": "gasto", "categoria": "otros", "moneda": "COP",
          "monto": 5000, "descripcion": "Del usuario", "entidad": "Test"}],
        origen="app_manual", usuario_id=user_id,
    )
    mov_id = db.obtener_movimientos(conn, usuario_id=user_id)[0]["id"]
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/movimiento/{mov_id}/borrar", data={"confirmar": "true"})

    assert resp.status_code == 404
    conn = db.conectar()
    assert db.obtener_movimiento(conn, user_id, mov_id) is not None
    conn.close()


def test_borrar_movimiento_sin_confirmar_da_400_y_no_borra(client, app_ctx):
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")
    _registrar(client)
    mov_id = _unico_movimiento_id(admin_id)

    resp = client.post(f"/api/movimiento/{mov_id}/borrar")

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    conn = db.conectar()
    assert db.obtener_movimiento(conn, admin_id, mov_id) is not None
    conn.close()


def test_borrar_movimiento_con_confirmar_valor_invalido_no_cuenta_como_confirmado(client, app_ctx):
    """"no" no es una confirmación explícita -- solo "true"/"1"/"on"/"yes"
    cuentan (ver _es_true)."""
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")
    _registrar(client)
    mov_id = _unico_movimiento_id(admin_id)

    resp = client.post(f"/api/movimiento/{mov_id}/borrar", data={"confirmar": "no"})

    assert resp.status_code == 400
    conn = db.conectar()
    assert db.obtener_movimiento(conn, admin_id, mov_id) is not None
    conn.close()


def test_borrar_movimiento_con_confirmar_true_lo_elimina_definitivamente(client, app_ctx):
    _, admin_id, _ = app_ctx
    login(client, "admin_test", "clave-admin-123")
    _registrar(client)
    mov_id = _unico_movimiento_id(admin_id)

    resp = client.post(f"/api/movimiento/{mov_id}/borrar", data={"confirmar": "true"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    conn = db.conectar()
    assert db.obtener_movimiento(conn, admin_id, mov_id) is None
    conn.close()


def test_borrar_movimiento_de_origen_gmail_bot_excel_incluye_advertencia_especifica_en_la_respuesta(client, app_ctx):
    _, admin_id, _ = app_ctx
    conn = db.conectar()
    db.insertar_movimientos(
        conn,
        [{"fecha": "2026-09-01", "tipo": "gasto", "categoria": "otros", "moneda": "COP",
          "monto": 15000, "descripcion": "Del excel legado", "entidad": "Bot"}],
        origen="gmail_bot_excel", usuario_id=admin_id,
    )
    mov_id = db.obtener_movimientos(conn, usuario_id=admin_id)[0]["id"]
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    resp = client.post(f"/api/movimiento/{mov_id}/borrar", data={"confirmar": "true"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert "actualizar_dashboard" in body["advertencia"]


def test_borrar_movimiento_opera_sobre_viendo_id_no_sobre_la_sesion_del_admin(client, app_ctx):
    _, admin_id, user_id = app_ctx
    conn = db.conectar()
    db.insertar_movimientos(
        conn,
        [{"fecha": "2026-09-01", "tipo": "gasto", "categoria": "otros", "moneda": "COP",
          "monto": 5000, "descripcion": "Del usuario", "entidad": "Test"}],
        origen="app_manual", usuario_id=user_id,
    )
    mov_id = db.obtener_movimientos(conn, usuario_id=user_id)[0]["id"]
    conn.close()

    login(client, "admin_test", "clave-admin-123")
    client.post("/cambiar-vista", data={"usuario_id": user_id})

    resp = client.post(f"/api/movimiento/{mov_id}/borrar", data={"confirmar": "true"})

    assert resp.status_code == 200
    conn = db.conectar()
    assert db.obtener_movimiento(conn, user_id, mov_id) is None
    conn.close()
