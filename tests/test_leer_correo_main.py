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


# ----------------------------- main(): usa calcular_dias_a_revisar dinámicamente -----------------------------

def test_main_sin_forzar_usa_calcular_dias_a_revisar_con_dias_minimo_de_cli(correo_ctx, monkeypatch):
    """Sin --usuario-id (recorrido normal de cuentas pendientes), main()
    debe calcular la ventana con calcular_dias_a_revisar(dias_minimo=--dias)
    -- no usar --dias directamente como ventana fija."""
    id_maria = crear_usuario("maria")
    crear_config(id_maria)

    llamadas_calc = []

    def _fake_calc(config, ahora, dias_minimo):
        llamadas_calc.append(dias_minimo)
        return 99

    monkeypatch.setattr(lc, "calcular_dias_a_revisar", _fake_calc)

    dias_usados = []

    def _buscar(dias, config):
        dias_usados.append(dias)
        return []

    monkeypatch.setattr(lc, "buscar_movimientos_correo", _buscar)

    correr_main(monkeypatch, ["--dias", "5", "--aplicar"])

    assert llamadas_calc == [5]
    assert dias_usados == [99]


def test_main_con_usuario_id_forzado_usa_el_valor_de_cli_directo_sin_calcular(correo_ctx, monkeypatch):
    """--usuario-id (forzado) debe usar --dias tal cual, SIN pasar por
    calcular_dias_a_revisar -- es una corrida manual explícita ("Sincronizar
    ahora"), no el recorrido automático."""
    id_maria = crear_usuario("maria")
    crear_config(id_maria)

    llamadas_calc = []
    monkeypatch.setattr(lc, "calcular_dias_a_revisar", lambda *a, **k: llamadas_calc.append(1) or 999)

    dias_usados = []
    monkeypatch.setattr(lc, "buscar_movimientos_correo", lambda dias, config: dias_usados.append(dias) or [])

    correr_main(monkeypatch, ["--usuario-id", str(id_maria), "--dias", "5", "--aplicar"])

    assert llamadas_calc == []
    assert dias_usados == [5]


# ----------------------------- calcular_dias_a_revisar() -----------------------------

def test_calcular_dias_a_revisar_sin_ultima_corrida_usa_dias_primera_corrida_si_es_mayor(correo_ctx):
    ahora = datetime.datetime(2026, 9, 5, 12, 0, 0)
    config = {"ultima_corrida": None}

    resultado = lc.calcular_dias_a_revisar(config, ahora, dias_minimo=7)

    assert resultado == lc.DIAS_PRIMERA_CORRIDA


def test_calcular_dias_a_revisar_sin_ultima_corrida_usa_dias_minimo_si_supera_primera_corrida(correo_ctx):
    ahora = datetime.datetime(2026, 9, 5, 12, 0, 0)
    config = {"ultima_corrida": None}

    resultado = lc.calcular_dias_a_revisar(config, ahora, dias_minimo=45)

    assert resultado == 45


def test_calcular_dias_a_revisar_hueco_chico_devuelve_el_minimo(correo_ctx):
    """Corrió hace 1 hora -- el hueco redondeado da menos que dias_minimo,
    así que debe devolver dias_minimo, no el hueco real."""
    ahora = datetime.datetime(2026, 9, 5, 12, 0, 0)
    ultima = (ahora - datetime.timedelta(hours=1)).isoformat()
    config = {"ultima_corrida": ultima}

    resultado = lc.calcular_dias_a_revisar(config, ahora, dias_minimo=2)

    assert resultado == 2


def test_calcular_dias_a_revisar_hueco_de_varios_dias_devuelve_el_hueco(correo_ctx):
    ahora = datetime.datetime(2026, 9, 15, 12, 0, 0)
    ultima = (ahora - datetime.timedelta(days=10)).isoformat()
    config = {"ultima_corrida": ultima}

    resultado = lc.calcular_dias_a_revisar(config, ahora, dias_minimo=2)

    assert resultado == 11  # hueco de 10 dias + 1 (cubre el dia completo de la ultima corrida)


def test_calcular_dias_a_revisar_hueco_enorme_se_topa_en_el_maximo(correo_ctx):
    """Automatización caída 200 días -- no debe escanear 200 días de
    correo, se topa en DIAS_MAXIMO_SI_HUBO_HUECO (60)."""
    ahora = datetime.datetime(2026, 9, 15, 12, 0, 0)
    ultima = (ahora - datetime.timedelta(days=200)).isoformat()
    config = {"ultima_corrida": ultima}

    resultado = lc.calcular_dias_a_revisar(config, ahora, dias_minimo=2)

    assert resultado == lc.DIAS_MAXIMO_SI_HUBO_HUECO


# ----------------------------- _adjuntos_pdf() -----------------------------

def _mensaje_multipart_con_adjuntos(adjuntos):
    """adjuntos: lista de tuplas (nombre_archivo, content_type, bytes)."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.application import MIMEApplication
    from email.mime.text import MIMEText

    msg = MIMEMultipart()
    msg.attach(MIMEText("cuerpo de prueba", "plain"))
    for nombre, content_type, datos in adjuntos:
        _maintype, subtype = content_type.split("/")
        parte = MIMEApplication(datos, _subtype=subtype)
        parte.add_header("Content-Disposition", "attachment", filename=nombre)
        msg.attach(parte)
    return msg


def test_adjuntos_pdf_mensaje_sin_adjuntos_da_lista_vacia():
    msg = _mensaje_multipart_con_adjuntos([])
    assert lc._adjuntos_pdf(msg) == []


def test_adjuntos_pdf_mensaje_no_multipart_da_lista_vacia():
    from email.mime.text import MIMEText
    msg = MIMEText("solo texto plano, sin adjuntos")
    assert lc._adjuntos_pdf(msg) == []


def test_adjuntos_pdf_con_un_adjunto_pdf_lo_extrae():
    msg = _mensaje_multipart_con_adjuntos([("extracto.pdf", "application/pdf", b"contenido falso de pdf")])
    adjuntos = lc._adjuntos_pdf(msg)
    assert adjuntos == [b"contenido falso de pdf"]


def test_adjuntos_pdf_ignora_adjuntos_que_no_son_pdf():
    msg = _mensaje_multipart_con_adjuntos([("foto.png", "image/png", b"contenido de imagen")])
    assert lc._adjuntos_pdf(msg) == []


def test_adjuntos_pdf_con_dos_adjuntos_pdf_extrae_los_dos():
    msg = _mensaje_multipart_con_adjuntos([
        ("extracto1.pdf", "application/pdf", b"pdf uno"),
        ("extracto2.pdf", "application/pdf", b"pdf dos"),
    ])
    adjuntos = lc._adjuntos_pdf(msg)
    assert set(adjuntos) == {b"pdf uno", b"pdf dos"}


def test_adjuntos_pdf_detecta_por_extension_aunque_content_type_no_sea_application_pdf():
    msg = _mensaje_multipart_con_adjuntos([("extracto.pdf", "application/octet-stream", b"contenido")])
    assert lc._adjuntos_pdf(msg) == [b"contenido"]


# ----------------------------- _parsear_pdf_adjunto() -----------------------------

def test_parsear_pdf_adjunto_devuelve_lista_vacia_si_pdf_text_lanza_excepcion(monkeypatch):
    """Contraseña incorrecta o PDF corrupto -- nunca debe propagar."""
    def _falla(buffer, password):
        raise Exception("contraseña incorrecta")

    monkeypatch.setattr(lc.rex, "pdf_text", _falla)

    assert lc._parsear_pdf_adjunto(b"bytes-cualquiera", cedula="123456") == []


def test_parsear_pdf_adjunto_devuelve_lista_vacia_si_no_matchea_ningun_formato_conocido(monkeypatch):
    monkeypatch.setattr(lc.rex, "pdf_text", lambda buffer, password: ["texto sin ningun patron reconocible"])

    assert lc._parsear_pdf_adjunto(b"bytes-cualquiera", cedula="123456") == []


def test_parsear_pdf_adjunto_dirige_a_savings_cuando_detecta_desde_hasta(monkeypatch):
    monkeypatch.setattr(lc.rex, "pdf_text", lambda buffer, password: ["DESDE: 2026/01/01 HASTA: 2026/01/31 resto del texto"])
    monkeypatch.setattr(lc.rex, "parse_savings_statement",
                         lambda buffer, password: ([{"fake": "mov"}], 0.0, "2026-01-01", "2026-01-31"))
    monkeypatch.setattr(lc.rex, "normalizar_savings", lambda m: {
        "fecha": "2026-01-15", "tipo": "gasto", "categoria": "otros", "moneda": "COP",
        "monto": 1000, "descripcion": "desde savings", "entidad": "Bancolombia",
    })

    resultado = lc._parsear_pdf_adjunto(b"bytes", cedula="123456")

    assert len(resultado) == 1
    assert resultado[0]["descripcion"] == "desde savings"


def test_parsear_pdf_adjunto_savings_agrega_fila_de_intereses_si_los_hay(monkeypatch):
    monkeypatch.setattr(lc.rex, "pdf_text", lambda buffer, password: ["DESDE: 2026/01/01 HASTA: 2026/01/31"])
    monkeypatch.setattr(lc.rex, "parse_savings_statement",
                         lambda buffer, password: ([], 5000.0, "2026-01-01", "2026-01-31"))

    resultado = lc._parsear_pdf_adjunto(b"bytes", cedula="123456")

    assert len(resultado) == 1
    assert resultado[0]["categoria"] == "intereses"
    assert resultado[0]["monto"] == 5000.0


def test_parsear_pdf_adjunto_devuelve_lista_vacia_si_parse_savings_lanza_excepcion(monkeypatch):
    """Detectó el formato (DESDE/HASTA) pero el parser real falla después
    -- no debe propagar, debe devolver []."""
    monkeypatch.setattr(lc.rex, "pdf_text", lambda buffer, password: ["DESDE: 2026/01/01 HASTA: 2026/01/31"])

    def _falla(buffer, password):
        raise Exception("boom")

    monkeypatch.setattr(lc.rex, "parse_savings_statement", _falla)

    assert lc._parsear_pdf_adjunto(b"bytes", cedula="123456") == []


def test_parsear_pdf_adjunto_dirige_a_tarjeta_cuando_detecta_detalles_del_movimiento(monkeypatch):
    monkeypatch.setattr(lc.rex, "pdf_text", lambda buffer, password: ["Detalles del movimiento de la tarjeta"])
    monkeypatch.setattr(lc.rex, "parse_card_statement",
                         lambda buffer, ultimos4, password: ([{"fake": "mov"}], {}, None, None))
    monkeypatch.setattr(lc.rex, "normalizar_card", lambda m, marca: {
        "fecha": "2026-01-15", "tipo": "gasto", "categoria": "otros", "moneda": "COP",
        "monto": 2000, "descripcion": "desde tarjeta", "entidad": "Bancolombia",
    })

    resultado = lc._parsear_pdf_adjunto(b"bytes", cedula="123456")

    assert len(resultado) == 1
    assert resultado[0]["descripcion"] == "desde tarjeta"


def test_parsear_pdf_adjunto_dirige_a_tarjeta_por_estado_de_cuenta_en(monkeypatch):
    monkeypatch.setattr(lc.rex, "pdf_text", lambda buffer, password: ["ESTADO DE CUENTA EN: PESOS con mas texto"])
    monkeypatch.setattr(lc.rex, "parse_card_statement",
                         lambda buffer, ultimos4, password: ([{"fake": "mov"}], {}, None, None))
    monkeypatch.setattr(lc.rex, "normalizar_card", lambda m, marca: {
        "fecha": "2026-01-15", "tipo": "gasto", "categoria": "otros", "moneda": "COP",
        "monto": 2000, "descripcion": "desde tarjeta 2", "entidad": "Bancolombia",
    })

    resultado = lc._parsear_pdf_adjunto(b"bytes", cedula="123456")

    assert len(resultado) == 1
    assert resultado[0]["descripcion"] == "desde tarjeta 2"


def test_parsear_pdf_adjunto_tarjeta_agrega_fila_de_intereses_si_los_hay(monkeypatch):
    monkeypatch.setattr(lc.rex, "pdf_text", lambda buffer, password: ["Detalles del movimiento con T.Cred *2011"])
    monkeypatch.setattr(lc.rex, "parse_card_statement",
                         lambda buffer, ultimos4, password: ([], {("2026-01-31", "COP"): 1500.0}, None, None))

    resultado = lc._parsear_pdf_adjunto(b"bytes", cedula="123456")

    assert len(resultado) == 1
    assert resultado[0]["categoria"] == "intereses"
    assert "2011" in resultado[0]["descripcion"]


def test_parsear_pdf_adjunto_devuelve_lista_vacia_si_parse_card_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(lc.rex, "pdf_text", lambda buffer, password: ["Detalles del movimiento"])

    def _falla(buffer, ultimos4, password):
        raise Exception("boom")

    monkeypatch.setattr(lc.rex, "parse_card_statement", _falla)

    assert lc._parsear_pdf_adjunto(b"bytes", cedula="123456") == []


def test_parsear_pdf_adjunto_extrae_ultimos4_reales_cuando_hay_patron_reconocible(monkeypatch):
    recibido = {}
    monkeypatch.setattr(lc.rex, "pdf_text", lambda buffer, password: ["Detalles del movimiento con tarjeta terminada en 2011 hoy"])

    def _fake_parse_card(buffer, ultimos4, password):
        recibido["ultimos4"] = ultimos4
        return ([], {}, None, None)

    monkeypatch.setattr(lc.rex, "parse_card_statement", _fake_parse_card)

    lc._parsear_pdf_adjunto(b"bytes", cedula="123456")

    assert recibido["ultimos4"] == "2011"


def test_parsear_pdf_adjunto_usa_signos_de_interrogacion_si_no_hay_patron_reconocible(monkeypatch):
    """Best-effort: si no encuentra el patrón de últimos 4 dígitos, usa
    '????' como fallback -- nunca rompe, el movimiento igual se procesa."""
    recibido = {}
    monkeypatch.setattr(lc.rex, "pdf_text", lambda buffer, password: ["Detalles del movimiento sin ningun numero de tarjeta"])

    def _fake_parse_card(buffer, ultimos4, password):
        recibido["ultimos4"] = ultimos4
        return ([], {}, None, None)

    monkeypatch.setattr(lc.rex, "parse_card_statement", _fake_parse_card)

    resultado = lc._parsear_pdf_adjunto(b"bytes", cedula="123456")

    assert recibido["ultimos4"] == "????"
    assert resultado == []


# ----------------------------- buscar_movimientos_correo(): PDFs adjuntos -----------------------------

def _mensaje_con_cuerpo_y_adjunto_pdf():
    """Bytes RFC822 de un correo con un cuerpo parseable como movimiento
    real (pago recibido) Y un adjunto PDF."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.application import MIMEApplication
    from email.mime.text import MIMEText

    msg = MIMEMultipart()
    msg.attach(MIMEText(
        "Recibiste un pago de Nomina de EMPRESA por $1000000.00 en tu cuenta de "
        "Ahorros el 01/09/2026 a las 09:00.",
        "plain",
    ))
    parte = MIMEApplication(b"contenido pdf falso", _subtype="pdf")
    parte.add_header("Content-Disposition", "attachment", filename="extracto.pdf")
    msg.attach(parte)
    return msg.as_bytes()


def _fake_imap_class(mensajes_bytes):
    """Clase IMAP4_SSL de mentira: la primera búsqueda (primer remitente)
    devuelve todos los mensajes; la segunda (segundo remitente) devuelve
    vacío, para no procesar el mismo mensaje dos veces."""
    estado = {"busquedas": 0}

    class _FakeIMAP:
        def __init__(self, host, port):
            pass

        def login(self, email, password):
            pass

        def select(self, mailbox, readonly=True):
            pass

        def search(self, charset, criterio):
            estado["busquedas"] += 1
            if estado["busquedas"] == 1:
                uids = b" ".join(str(i).encode() for i in range(len(mensajes_bytes)))
                return ("OK", [uids])
            return ("OK", [b""])

        def fetch(self, uid, spec):
            idx = int(uid)
            return ("OK", [(None, mensajes_bytes[idx])])

        def logout(self):
            pass

    return _FakeIMAP


def test_buscar_movimientos_correo_sin_cedula_no_llama_a_adjuntos_pdf(correo_ctx, monkeypatch):
    raw = _mensaje_con_cuerpo_y_adjunto_pdf()
    monkeypatch.setattr(lc.imaplib, "IMAP4_SSL", _fake_imap_class([raw]))
    llamado = []
    monkeypatch.setattr(lc, "_adjuntos_pdf", lambda msg: (llamado.append(True), [])[1])

    config = {"email": "x@example.com", "app_password": "y", "imap_host": "imap.gmail.com", "imap_port": 993}
    movimientos = lc.buscar_movimientos_correo(dias=3, config=config)

    assert llamado == []
    assert len(movimientos) == 1  # solo el del cuerpo


def test_buscar_movimientos_correo_con_cedula_vacia_no_llama_a_adjuntos_pdf(correo_ctx, monkeypatch):
    raw = _mensaje_con_cuerpo_y_adjunto_pdf()
    monkeypatch.setattr(lc.imaplib, "IMAP4_SSL", _fake_imap_class([raw]))
    llamado = []
    monkeypatch.setattr(lc, "_adjuntos_pdf", lambda msg: (llamado.append(True), [])[1])

    config = {"email": "x@example.com", "app_password": "y", "cedula": ""}
    lc.buscar_movimientos_correo(dias=3, config=config)

    assert llamado == []


def test_buscar_movimientos_correo_con_cedula_llama_a_parsear_pdf_adjunto_y_agrega_resultados(correo_ctx, monkeypatch):
    raw = _mensaje_con_cuerpo_y_adjunto_pdf()
    monkeypatch.setattr(lc.imaplib, "IMAP4_SSL", _fake_imap_class([raw]))
    monkeypatch.setattr(lc, "_parsear_pdf_adjunto", lambda datos, cedula: [{
        "fecha": "2026-01-01", "tipo": "ingreso", "categoria": "intereses", "moneda": "COP",
        "monto": 1, "descripcion": "del pdf", "entidad": "Bancolombia",
    }])

    config = {"email": "x@example.com", "app_password": "y", "cedula": "123456"}
    movimientos = lc.buscar_movimientos_correo(dias=3, config=config)

    assert len(movimientos) == 2  # cuerpo + pdf
    descripciones = {m["descripcion"] for m in movimientos}
    assert "del pdf" in descripciones


def test_buscar_movimientos_correo_un_adjunto_que_lanza_excepcion_no_tumba_la_corrida(correo_ctx, monkeypatch):
    raw = _mensaje_con_cuerpo_y_adjunto_pdf()
    monkeypatch.setattr(lc.imaplib, "IMAP4_SSL", _fake_imap_class([raw]))

    def _falla(datos, cedula):
        raise RuntimeError("adjunto corrupto")

    monkeypatch.setattr(lc, "_parsear_pdf_adjunto", _falla)

    config = {"email": "x@example.com", "app_password": "y", "cedula": "123456"}
    movimientos = lc.buscar_movimientos_correo(dias=3, config=config)

    assert len(movimientos) == 1  # solo el del cuerpo -- el pdf falló pero no tumbó nada


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
