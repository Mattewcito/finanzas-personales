"""
Pruebas de leer_correo.py enfocadas en el flujo multiusuario desatendido
configurado desde la BD (Fase 1 rediseñada, 2026-09-05): ya NO hay
archivos JSON por cuenta -- toda la configuración vive en la tabla
`correo_config` de data/finanzas.db (ver db_finanzas.py y
tests/test_db_correo_config.py). Cubre:

  - esta_pendiente(): lógica pura de fechas para 'intervalo' y 'diario'.
  - main(): recorrido de cuentas activas, respeto de esta_pendiente(),
    --usuario-id puntual (fuerza la corrida ignorando esta_pendiente()),
    aislamiento de fallos entre cuentas, y dedup.
  - procesar_cuenta(): deja subir la excepción sin atraparla.

No tocar: tests/test_parsers_correo.py ya cubre los parsers de regex y no
se toca acá.

IMPORTANTE -- aislamiento de filesystem (mismo patrón que dashboard_ctx en
tests/test_actualizar_dashboard.py):
  1. db.DATA_DIR / db.DB_PATH / db.XLSX_PATH -- BD aislada en tmp_path.
  2. leer_correo.LOG_PATH -- se calcula a partir de db.PROJECT_ROOT UNA
     sola vez al importar el módulo, así que hay que parchearlo
     directamente para nunca escribir en data/leer_correo.log real.

Este archivo NO hace "import app" -- convive sin problema con el resto de
la suite (esa importación está reservada a tests/test_app_integration.py).
"""
import datetime
import sys

import pytest

import db_finanzas as db
import leer_correo as lc


# ----------------------------- Fixtures y helpers -----------------------------

@pytest.fixture
def correo_ctx(tmp_path, monkeypatch):
    """Aísla toda la corrida de leer_correo.main() en tmp_path: BD y log.
    Nunca toca data/finanzas.db ni data/leer_correo.log reales."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "DB_PATH", data_dir / "finanzas.db")
    monkeypatch.setattr(db, "XLSX_PATH", data_dir / "finanzas_personales.xlsx")

    monkeypatch.setattr(lc, "LOG_PATH", data_dir / "leer_correo.log")

    return data_dir


def crear_usuario(username, rol="usuario", nombre_mostrado=None):
    """Crea el esquema (si hace falta) y un usuario en la BD ya parcheada
    por correo_ctx. Devuelve su id."""
    conn = db.conectar()
    db.crear_esquema(conn)
    uid = db.crear_usuario(conn, username, "clave-123", rol, nombre_mostrado or username)
    conn.close()
    return uid


def crear_config(usuario_id, email=None, **extra):
    """Guarda una fila en correo_config para usuario_id, con valores por
    defecto razonables, sobre la BD ya parcheada por correo_ctx."""
    email = email or f"usuario{usuario_id}@example.com"
    kwargs = {
        "email": email,
        "app_password": "clave-app-falsa",
    }
    kwargs.update(extra)
    conn = db.conectar()
    try:
        db.guardar_correo_config(conn, usuario_id, **kwargs)
    finally:
        conn.close()


def config_de(usuario_id):
    conn = db.conectar()
    try:
        return db.obtener_correo_config(conn, usuario_id)
    finally:
        conn.close()


MOVIMIENTOS_PRUEBA = [
    {
        "fecha": "2026-09-01",
        "tipo": "gasto",
        "categoria": "supermercado",
        "moneda": "COP",
        "monto": 50000.0,
        "descripcion": "Compra en EXITO con T.Deb *5360",
        "entidad": "Bancolombia",
    },
    {
        "fecha": "2026-09-02",
        "tipo": "ingreso",
        "categoria": "salario",
        "moneda": "COP",
        "monto": 2000000.0,
        "descripcion": "Pago recibido: Nomina",
        "entidad": "Bancolombia",
    },
]

MOVIMIENTOS_PRUEBA_OTRA_CUENTA = [
    {
        "fecha": "2026-09-03",
        "tipo": "gasto",
        "categoria": "transporte",
        "moneda": "COP",
        "monto": 15000.0,
        "descripcion": "Compra en UBER con T.Cred *4112",
        "entidad": "Bancolombia",
    },
]


def correr_main(monkeypatch, args):
    """Ejecuta lc.main() con el argv indicado, sin depender del argv real
    de pytest."""
    monkeypatch.setattr(sys, "argv", ["leer_correo.py"] + args)
    return lc.main()


# ----------------------------- esta_pendiente(): 'intervalo' -----------------------------

def test_esta_pendiente_intervalo_sin_ultima_corrida_es_true(correo_ctx):
    """Cuenta recién configurada, nunca corrió todavía -- debe correr ya."""
    config = {"frecuencia_tipo": "intervalo", "frecuencia_minutos": 30, "ultima_corrida": None}
    ahora = datetime.datetime(2026, 9, 5, 12, 0, 0)
    assert lc.esta_pendiente(config, ahora) is True


def test_esta_pendiente_intervalo_con_ultima_corrida_reciente_es_false(correo_ctx):
    """Corrió hace 10 minutos con intervalo de 30 -- todavía no le toca."""
    ahora = datetime.datetime(2026, 9, 5, 12, 0, 0)
    ultima = (ahora - datetime.timedelta(minutes=10)).isoformat()
    config = {"frecuencia_tipo": "intervalo", "frecuencia_minutos": 30, "ultima_corrida": ultima}
    assert lc.esta_pendiente(config, ahora) is False


def test_esta_pendiente_intervalo_con_ultima_corrida_vieja_es_true(correo_ctx):
    """Corrió hace 45 minutos con intervalo de 30 -- ya le toca de nuevo."""
    ahora = datetime.datetime(2026, 9, 5, 12, 0, 0)
    ultima = (ahora - datetime.timedelta(minutes=45)).isoformat()
    config = {"frecuencia_tipo": "intervalo", "frecuencia_minutos": 30, "ultima_corrida": ultima}
    assert lc.esta_pendiente(config, ahora) is True


# ----------------------------- esta_pendiente(): 'diario' -----------------------------

def test_esta_pendiente_diario_hora_todavia_no_llego_es_false(correo_ctx):
    ahora = datetime.datetime(2026, 9, 5, 7, 0, 0)
    config = {"frecuencia_tipo": "diario", "frecuencia_hora": "08:00", "ultima_corrida": None}
    assert lc.esta_pendiente(config, ahora) is False


def test_esta_pendiente_diario_hora_ya_paso_y_nunca_corrio_es_true(correo_ctx):
    ahora = datetime.datetime(2026, 9, 5, 9, 0, 0)
    config = {"frecuencia_tipo": "diario", "frecuencia_hora": "08:00", "ultima_corrida": None}
    assert lc.esta_pendiente(config, ahora) is True


def test_esta_pendiente_diario_hora_ya_paso_pero_ya_corrio_hoy_es_false(correo_ctx):
    """No debe disparar dos veces el mismo día, aunque ya haya pasado la
    hora objetivo."""
    ahora = datetime.datetime(2026, 9, 5, 9, 0, 0)
    ultima = datetime.datetime(2026, 9, 5, 8, 1, 0).isoformat()
    config = {"frecuencia_tipo": "diario", "frecuencia_hora": "08:00", "ultima_corrida": ultima}
    assert lc.esta_pendiente(config, ahora) is False


def test_esta_pendiente_diario_ultima_corrida_de_ayer_es_true(correo_ctx):
    """Al día siguiente, aunque ya haya corrido "alguna vez", debe volver
    a dispararse una vez que pase la hora objetivo."""
    ahora = datetime.datetime(2026, 9, 5, 9, 0, 0)
    ultima = datetime.datetime(2026, 9, 4, 8, 1, 0).isoformat()
    config = {"frecuencia_tipo": "diario", "frecuencia_hora": "08:00", "ultima_corrida": ultima}
    assert lc.esta_pendiente(config, ahora) is True


# ----------------------------- main(): multiusuario, sin cruces -----------------------------

def test_main_aplicar_con_dos_cuentas_activas_inserta_cada_una_en_su_propio_usuario(correo_ctx, monkeypatch):
    """El caso central del multiusuario: con DOS cuentas activas y
    pendientes en correo_config, main() --aplicar debe insertar los
    movimientos de cada una SOLO en su propio usuario_id -- nunca
    mezclados entre sí."""
    id_carlos = crear_usuario("carlos")
    id_maria = crear_usuario("maria")
    crear_config(id_carlos, email="carlos@example.com")
    crear_config(id_maria, email="maria@example.com")

    def _buscar_segun_config(dias, config):
        if config["usuario_id"] == id_carlos:
            return list(MOVIMIENTOS_PRUEBA_OTRA_CUENTA)
        return list(MOVIMIENTOS_PRUEBA)

    monkeypatch.setattr(lc, "buscar_movimientos_correo", _buscar_segun_config)

    resultado = correr_main(monkeypatch, ["--aplicar"])

    assert resultado == 0

    conn = db.conectar()
    try:
        movimientos_carlos = db.obtener_movimientos(conn, usuario_id=id_carlos)
        movimientos_maria = db.obtener_movimientos(conn, usuario_id=id_maria)
    finally:
        conn.close()

    assert len(movimientos_carlos) == 1
    assert movimientos_carlos[0]["descripcion"] == "Compra en UBER con T.Cred *4112"
    assert len(movimientos_maria) == 2
    descripciones_maria = {m["descripcion"] for m in movimientos_maria}
    assert "Compra en EXITO con T.Deb *5360" in descripciones_maria
    assert "Pago recibido: Nomina" in descripciones_maria

    log_texto = lc.LOG_PATH.read_text(encoding="utf-8")
    assert "OK" in log_texto


# ----------------------------- main(): respeta esta_pendiente() -----------------------------

def test_main_no_procesa_una_cuenta_a_la_que_todavia_no_le_toca(correo_ctx, monkeypatch):
    """Una cuenta activa, pero con ultima_corrida muy reciente frente a un
    intervalo largo: no debe ni siquiera llamarse buscar_movimientos_correo
    para ella, y sus movimientos no deben cambiar."""
    id_maria = crear_usuario("maria")
    crear_config(id_maria, frecuencia_tipo="intervalo", frecuencia_minutos=1440)
    # Simula que ya corrió hace un instante -- con un intervalo de 24hs,
    # no le toca de nuevo.
    conn = db.conectar()
    db.actualizar_estado_correo(conn, id_maria, ok=True)
    conn.close()

    llamadas = []

    def _buscar(dias, config):
        llamadas.append(config["usuario_id"])
        return list(MOVIMIENTOS_PRUEBA)

    monkeypatch.setattr(lc, "buscar_movimientos_correo", _buscar)

    resultado = correr_main(monkeypatch, ["--aplicar"])

    assert resultado == 0
    assert llamadas == []

    conn = db.conectar()
    try:
        movimientos = db.obtener_movimientos(conn, usuario_id=id_maria)
    finally:
        conn.close()
    assert movimientos == []


# ----------------------------- main(): aislamiento de fallos entre cuentas -----------------------------

def test_main_aplicar_con_una_cuenta_fallida_no_detiene_el_procesamiento_de_la_otra(correo_ctx, monkeypatch):
    """Con dos cuentas activas y pendientes, si una falla (excepción de
    buscar_movimientos_correo), la otra debe seguir procesándose e
    insertar sus movimientos igual. main() debe devolver 1, y la cuenta
    fallida debe quedar con ultima_corrida_ok=False y el mensaje de error
    guardado en correo_config."""
    id_maria = crear_usuario("maria")
    id_carlos = crear_usuario("carlos")
    crear_config(id_maria, email="maria@example.com")
    crear_config(id_carlos, email="carlos@example.com")

    def _buscar_segun_config(dias, config):
        if config["usuario_id"] == id_carlos:
            raise RuntimeError("fallo de conexión IMAP simulado")
        return list(MOVIMIENTOS_PRUEBA)

    monkeypatch.setattr(lc, "buscar_movimientos_correo", _buscar_segun_config)

    resultado = correr_main(monkeypatch, ["--aplicar"])

    assert resultado == 1

    conn = db.conectar()
    try:
        movimientos_maria = db.obtener_movimientos(conn, usuario_id=id_maria)
    finally:
        conn.close()
    assert len(movimientos_maria) == 2

    fila_carlos = config_de(id_carlos)
    assert fila_carlos["ultima_corrida_ok"] == 0
    assert "fallo de conexión IMAP simulado" in fila_carlos["ultimo_error"]

    log_texto = lc.LOG_PATH.read_text(encoding="utf-8")
    assert "ERROR" in log_texto
    assert "OK" in log_texto


def test_main_sin_aplicar_una_cuenta_fallida_no_llama_a_actualizar_estado_correo(correo_ctx, monkeypatch):
    """Sin --aplicar (modo reporte), aunque una cuenta falle, main() no
    debe escribir en correo_config -- ni siquiera el estado de error."""
    id_carlos = crear_usuario("carlos")
    crear_config(id_carlos, email="carlos@example.com")

    monkeypatch.setattr(
        lc, "buscar_movimientos_correo",
        lambda dias, config: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    resultado = correr_main(monkeypatch, [])

    assert resultado == 1
    fila = config_de(id_carlos)
    assert fila["ultima_corrida_ok"] is None
    assert fila["ultimo_error"] is None


# ----------------------------- main(): --usuario-id puntual -----------------------------

def test_main_con_usuario_id_fuerza_la_corrida_ignorando_esta_pendiente(correo_ctx, monkeypatch):
    """--usuario-id N debe correr esa cuenta YA MISMO, aunque su
    frecuencia diga que todavía no le toca."""
    id_maria = crear_usuario("maria")
    crear_config(id_maria, frecuencia_tipo="intervalo", frecuencia_minutos=1440)
    conn = db.conectar()
    db.actualizar_estado_correo(conn, id_maria, ok=True)  # "acaba de correr"
    conn.close()

    monkeypatch.setattr(lc, "buscar_movimientos_correo", lambda dias, config: list(MOVIMIENTOS_PRUEBA))

    resultado = correr_main(monkeypatch, ["--aplicar", "--usuario-id", str(id_maria)])

    assert resultado == 0
    conn = db.conectar()
    try:
        movimientos = db.obtener_movimientos(conn, usuario_id=id_maria)
    finally:
        conn.close()
    assert len(movimientos) == 2


def test_main_con_usuario_id_inexistente_devuelve_uno_y_loguea_error(correo_ctx, monkeypatch):
    crear_usuario("maria")  # existe como usuario, pero sin correo_config

    resultado = correr_main(monkeypatch, ["--aplicar", "--usuario-id", "999999"])

    assert resultado == 1
    log_texto = lc.LOG_PATH.read_text(encoding="utf-8")
    assert "ERROR" in log_texto


# ----------------------------- main(): sin ninguna cuenta activa -----------------------------

def test_main_sin_ninguna_cuenta_activa_devuelve_cero_y_loguea_ok(correo_ctx, monkeypatch):
    """A diferencia de --usuario-id apuntando a nadie, tener cero cuentas
    configuradas/activas todavía NO es un error -- es el estado normal de
    un sistema recién instalado."""
    resultado = correr_main(monkeypatch, ["--aplicar"])

    assert resultado == 0
    log_texto = lc.LOG_PATH.read_text(encoding="utf-8")
    assert "OK" in log_texto


# ----------------------------- Dedup -----------------------------

def test_main_aplicar_dos_veces_seguidas_con_los_mismos_movimientos_no_duplica(correo_ctx, monkeypatch):
    """Dos corridas de la misma cuenta con los mismos movimientos no deben
    duplicar -- se fuerza la segunda corrida con --usuario-id (si no,
    esta_pendiente() la bloquearía por el intervalo, que es justamente el
    comportamiento correcto en producción)."""
    id_maria = crear_usuario("maria")
    crear_config(id_maria, frecuencia_tipo="intervalo", frecuencia_minutos=30)
    monkeypatch.setattr(lc, "buscar_movimientos_correo", lambda dias, config: list(MOVIMIENTOS_PRUEBA))

    primer_resultado = correr_main(monkeypatch, ["--aplicar", "--usuario-id", str(id_maria)])
    segundo_resultado = correr_main(monkeypatch, ["--aplicar", "--usuario-id", str(id_maria)])

    assert primer_resultado == 0
    assert segundo_resultado == 0

    conn = db.conectar()
    try:
        movimientos = db.obtener_movimientos(conn, usuario_id=id_maria)
    finally:
        conn.close()

    assert len(movimientos) == 2


# ----------------------------- procesar_cuenta() -----------------------------

def test_procesar_cuenta_deja_subir_la_excepcion_sin_atraparla(correo_ctx, monkeypatch):
    """procesar_cuenta() no debe atrapar errores -- eso es responsabilidad
    de main() (para poder loguearlos y seguir con las demás cuentas). Acá
    se verifica que la excepción efectivamente suba y que NO se haya
    llamado a actualizar_estado_correo con ok=False por sí sola."""
    id_maria = crear_usuario("maria")
    crear_config(id_maria)
    config = config_de(id_maria)

    monkeypatch.setattr(
        lc, "buscar_movimientos_correo",
        lambda dias, config: (_ for _ in ()).throw(RuntimeError("fallo simulado")),
    )

    with pytest.raises(RuntimeError, match="fallo simulado"):
        lc.procesar_cuenta(config, dias=7, aplicar=True)

    fila = config_de(id_maria)
    assert fila["ultima_corrida_ok"] is None
    assert fila["ultimo_error"] is None


def test_procesar_cuenta_sin_aplicar_no_toca_la_bd(correo_ctx, monkeypatch):
    """Con aplicar=False, no debe insertarse nada ni actualizarse el
    estado de correo_config."""
    id_maria = crear_usuario("maria")
    crear_config(id_maria)
    config = config_de(id_maria)

    monkeypatch.setattr(lc, "buscar_movimientos_correo", lambda dias, config: list(MOVIMIENTOS_PRUEBA))

    mensaje = lc.procesar_cuenta(config, dias=7, aplicar=False)

    assert "solo reporte" in mensaje
    conn = db.conectar()
    try:
        assert db.obtener_movimientos(conn, usuario_id=id_maria) == []
    finally:
        conn.close()
    fila = config_de(id_maria)
    assert fila["ultima_corrida_ok"] is None
