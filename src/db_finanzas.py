"""
db_finanzas.py
================
Módulo compartido de acceso a datos para el proyecto de finanzas personales.

FASE 0 del rediseño: mover la fuente de verdad de un Excel a una base de
datos SQLite real, local, sin dependencias externas (sqlite3 viene incluido
en Python — no hay que instalar nada).

Por ahora (transición), el Excel `data/finanzas_personales.xlsx` sigue
siendo lo que actualiza el bot de Gmail todos los días. Este módulo
SINCRONIZA desde ese Excel hacia `data/finanzas.db` cada vez que corre
`actualizar_dashboard.py`, así que la base de datos siempre queda al día
sin que nadie tenga que tocarla a mano. Cuando la lectura de correo pase a
ser una automatización local propia (próxima fase), la sincronización
dejará de ser "borrar y volver a cargar" y pasará a ser un merge con dedup
real por (fecha, monto).

Tablas:
  - movimientos: un registro por movimiento financiero, ya enriquecido con
    medio_pago y es_deuda (no hace falta recalcularlo en cada consulta).
  - historial_actualizaciones: espejo de la hoja del mismo nombre en el Excel.

Vista:
  - v_deuda_ledger: ledger cronológico de deuda de tarjeta de crédito con
    saldo corriente, calculado con una función de ventana SQL.
"""

import re
import json
import sqlite3
import datetime
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

import cifrado

SRC_DIR = Path(__file__).resolve().parent          # .../Finanzas personales/src
PROJECT_ROOT = SRC_DIR.parent                       # .../Finanzas personales
DATA_DIR = PROJECT_ROOT / "data"
XLSX_PATH = DATA_DIR / "finanzas_personales.xlsx"
DB_PATH = DATA_DIR / "finanzas.db"
SHEET_MOVIMIENTOS = "movimientos"
SHEET_HISTORIAL = "historial_actualizaciones"

CAMPOS_ESPERADOS = ("fecha", "tipo", "categoria", "moneda", "monto", "descripcion", "entidad")

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS movimientos (
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
    referencia_bancaria TEXT,
    creado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_movimientos_fecha ON movimientos(fecha);
CREATE INDEX IF NOT EXISTS idx_movimientos_fecha_monto ON movimientos(fecha, monto);
CREATE INDEX IF NOT EXISTS idx_movimientos_origen ON movimientos(origen);

CREATE TABLE IF NOT EXISTS historial_actualizaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_actualizacion TEXT NOT NULL,
    fecha_inicio_importada TEXT,
    fecha_fin_importada TEXT,
    movimientos_agregados INTEGER,
    origen TEXT DEFAULT 'gmail_bot_excel'
);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'usuario',   -- 'admin' | 'usuario'
    nombre_mostrado TEXT,
    creado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_usuarios_username ON usuarios(username);

-- Configuración de lectura de correo (Fase 1), UNA fila por usuario --
-- cada quien configura su propio correo dedicado desde "Mi perfil" en la
-- interfaz (routes/correo.py). app_password no se puede hashear (leer_correo.py
-- necesita el valor real para autenticarse por IMAP) -- desde la migración del
-- 2026-09-06 se guarda CIFRADO con cifrado.cifrar() (misma columna
-- app_password de abajo, pero con el valor cifrado) en vez de en texto plano;
-- la clave de cifrado vive en
-- data/cifrado.key, fuera de git, igual que finanzas.db. La interfaz nunca
-- vuelve a mostrar el valor una vez guardado.
CREATE TABLE IF NOT EXISTS correo_config (
    usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id),
    email TEXT NOT NULL,
    app_password TEXT NOT NULL,
    imap_host TEXT NOT NULL DEFAULT 'imap.gmail.com',
    imap_port INTEGER NOT NULL DEFAULT 993,
    cedula TEXT,          -- opcional: contraseña de los PDF de extracto adjuntos (Bancolombia los cifra con la cédula del titular)
    activo INTEGER NOT NULL DEFAULT 1,
    frecuencia_tipo TEXT NOT NULL DEFAULT 'intervalo',   -- 'intervalo' | 'diario'
    frecuencia_minutos INTEGER NOT NULL DEFAULT 30,       -- usado si frecuencia_tipo='intervalo'
    frecuencia_hora TEXT,                                 -- 'HH:MM', usado si frecuencia_tipo='diario'
    ultima_corrida TEXT,
    ultima_corrida_ok INTEGER,
    ultimo_error TEXT,
    ultima_corrida_detalle TEXT,  -- JSON con el detalle técnico de la última corrida (ver actualizar_estado_correo) -- solo visible para admin en la interfaz
    actualizado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Vistas del dashboard que un admin decidió ocultar para un usuario
-- puntual (routes/admin_vistas.py) -- ej. "Mathewcito no quiere que
-- Emanuel vea Correo automático". La AUSENCIA de una fila significa
-- "visible" (default): no hace falta una columna booleana, alcanza con
-- que exista o no la fila -- ocultar = INSERT, volver a mostrar =
-- DELETE. Se aplica siempre sobre la cuenta que inició sesión
-- (session["usuario_id"]), nunca sobre viendo_id() -- ver auth.py.
CREATE TABLE IF NOT EXISTS vistas_ocultas (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    vista TEXT NOT NULL,   -- 'correo_automatico' por ahora; futuro: 'insights', 'perfil_financiero'
    PRIMARY KEY (usuario_id, vista)
);

-- Tarjetas de crédito propias del usuario (2026-09-07, ver
-- requisitos/2026-09-07_tarjetas-credito-cupo.md) -- entidad con cupo
-- propio, separada del ledger agregado de deuda que ya existía
-- (v_deuda_ledger). Sin cifrado a propósito: nombre/entidad/cupo_total/
-- ultimos4 son datos financieros equivalentes a "monto"/"saldo", no
-- credenciales -- ver la sección "Cifrado" del documento de requisitos.
-- cupo_total se valida > 0 en la capa de Python (crear_tarjeta/
-- actualizar_tarjeta), no solo en la UI. "activa" es el soft-delete
-- (archivar_tarjeta): una tarjeta archivada conserva su historial de
-- movimientos asociados, solo deja de ofrecerse en selectores/desgloses
-- de "activas".
CREATE TABLE IF NOT EXISTS tarjetas_credito (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    nombre TEXT NOT NULL,
    entidad TEXT,
    cupo_total REAL NOT NULL,
    ultimos4 TEXT,
    activa INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    actualizado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_tarjetas_credito_usuario ON tarjetas_credito(usuario_id);

-- Presupuesto por 3 baldes (50/30/20), metas de ahorro (2026-09-08, ver
-- requisitos/2026-09-08_presupuesto-ahorro-deudas.md). Sin cifrado a
-- propósito -- mismo criterio que tarjetas_credito: son montos y
-- porcentajes, no credenciales (ver sección "Cifrado" del documento).
--
-- "presupuesto" es UNA fila por usuario (como correo_config), no una
-- fila por balde: los 3 porcentajes de un mismo usuario se leen/escriben
-- siempre juntos, así que separarlos en filas solo complicaría sin
-- ganar nada. La AUSENCIA de fila significa "todavía sin configurar" --
-- se sigue devolviendo 50/30/20 igual (ver obtener_presupuesto(), campo
-- "configurado") para que el dashboard nunca reviente ni muestre NaN en
-- una cuenta nueva, cumpliendo el caso borde del documento de requisitos.
CREATE TABLE IF NOT EXISTS presupuesto (
    usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id),
    pct_necesidades REAL NOT NULL DEFAULT 50,
    pct_gustos REAL NOT NULL DEFAULT 30,
    pct_ahorro_deudas REAL NOT NULL DEFAULT 20,
    actualizado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Mapeo categoría -> balde, por usuario (cada quien puede reasignar sus
-- propias categorías sin tocar código ni afectar a otras cuentas). La
-- categoría es texto libre (igual que movimientos.categoria -- no hay
-- un catálogo cerrado, ver registrar.html/obtener_categorias()), así que
-- la clave es (usuario_id, categoria), no un id de categoría. Se
-- autopobla de forma perezosa e idempotente con un default razonable
-- (ver CATEGORIA_BALDE_DEFAULT) la primera vez que se pide el mapeo de
-- ese usuario (obtener_mapeo_categorias()) -- así "cada categoría
-- existente ya viene asignada a un balde por defecto" se cumple sin
-- que el usuario tenga que configurar nada.
CREATE TABLE IF NOT EXISTS presupuesto_categorias (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    categoria TEXT NOT NULL,
    balde TEXT NOT NULL,   -- 'necesidades' | 'gustos' | 'ahorro_deudas'
    actualizado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (usuario_id, categoria)
);

-- Metas de ahorro (mismo patrón que tarjetas_credito: crear, ver avance,
-- archivar). El "avance" (ahorrado) NUNCA se guarda como un número
-- aparte que haya que mantener sincronizado -- se calcula siempre al
-- vuelo sumando los movimientos de la tabla `movimientos` que traen
-- meta_ahorro_id=este id (ver _migrar_columna_meta_ahorro_id() más abajo
-- y obtener_metas_ahorro()): el aporte a una meta ES un movimiento más,
-- no un sistema paralelo de transferencias internas (ver documento de
-- requisitos). "activa" es el soft-delete (archivar_meta_ahorro): una
-- meta archivada conserva su historial de aportes, solo deja de
-- ofrecerse como destino de aportes nuevos.
CREATE TABLE IF NOT EXISTS metas_ahorro (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    nombre TEXT NOT NULL,
    monto_objetivo REAL NOT NULL,
    fecha_objetivo TEXT,     -- opcional, 'AAAA-MM-DD'
    activa INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    actualizado_en TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_metas_ahorro_usuario ON metas_ahorro(usuario_id);
"""

# Catálogo de vistas que un admin puede ocultar/mostrar por usuario
# (routes/admin_vistas.py). Agregar una nueva vista a futuro es tan
# simple como sumar una entrada acá y envolver esa sección del
# dashboard/menú con el mismo chequeo que ya usan las de abajo.
#
# "dashboard"/"perfil_financiero"/"insights"/"deuda"/"analisis"/
# "movimientos" son sobre DE QUÉ CUENTA se muestran datos -- se
# chequean con viendo_id() (ver auth.py::requiere_vista_visible
# (por_viendo=True) y routes/dashboard.py): ocultarle "Insights" a
# Emanuel los oculta tanto si Emanuel mira su propio dashboard como si
# un admin está "viendo" el perfil de Emanuel. Solo "dashboard" (la
# página completa) tiene su propio bloqueo de ruta con el decorador;
# las demás sub-secciones ("perfil_financiero", "insights", "deuda",
# "analisis", "movimientos") viven dentro de esa misma página y se
# esconden del lado del cliente vía el campo "vistas_ocultas" de
# /api/dashboard-data (ver dashboard/dashboard_finanzas.html::
# ocultarSubvistas()) -- no tienen ruta propia que bloquear.
# "correo_automatico" es distinto -- una función de
# autoservicio ligada a la identidad de sesión (para que un admin pueda
# seguir configurando el correo de Emanuel via viendo_id() aunque
# Emanuel tenga esa sección oculta para sí mismo) -- se chequea con
# session["usuario_id"] (por_viendo=False, el default).
VISTAS_DISPONIBLES = [
    {"id": "dashboard", "label": "Dashboard",
     "descripcion": "El ítem \"Dashboard\" del menú y la página completa."},
    {"id": "perfil_financiero", "label": "Tu perfil financiero",
     "descripcion": "La sección \"Tu perfil financiero\" dentro del Dashboard."},
    {"id": "insights", "label": "Insights automáticos",
     "descripcion": "La sección \"Insights automáticos\" dentro del Dashboard."},
    {"id": "deuda", "label": "Tarjetas y deudas",
     "descripcion": "La sección \"Tarjetas de crédito y deuda\" dentro del Dashboard."},
    {"id": "analisis", "label": "Análisis visual",
     "descripcion": "La sección \"Análisis visual\" (los 8 gráficos) dentro del Dashboard."},
    {"id": "movimientos", "label": "Movimientos",
     "descripcion": "La sección \"Últimos movimientos\" (las 5 vistas y la tabla completa paginada) dentro del Dashboard."},
    {"id": "correo_automatico", "label": "Correo automático",
     "descripcion": "El ítem \"Correo automático\" del menú y su página de configuración."},
]

# username no tiene restricción UNIQUE a nivel de base de datos, para
# soportar configuraciones de cuentas fuera del caso estándar.

# ----------------------------- Presupuesto por baldes (50/30/20) -----------------------------
# Catálogo de baldes -- id (usado en la BD/API) + etiqueta en lenguaje
# simple (para que el frontend no tenga que hardcodear el texto, mismo
# criterio que VISTAS_DISPONIBLES de arriba). Cambiar el ORDEN de esta
# lista no afecta nada guardado (la BD identifica cada balde por su id,
# nunca por posición).
BALDES_PRESUPUESTO = [
    {"id": "necesidades", "label": "Necesidades"},
    {"id": "gustos", "label": "Gustos"},
    {"id": "ahorro_deudas", "label": "Ahorro/deudas"},
]
IDS_BALDES = {b["id"] for b in BALDES_PRESUPUESTO}

# 50/30/20 del ingreso real, sugerido por el "Planeador financiero 2026"
# que ya usaba el usuario (ver requisitos/2026-09-08_presupuesto-ahorro-
# deudas.md) -- ya cargado por defecto, editable en cualquier momento
# (ver guardar_presupuesto()).
PRESUPUESTO_PCT_DEFAULT = {"necesidades": 50.0, "gustos": 30.0, "ahorro_deudas": 20.0}

# Asignación default razonable de las categorías REALES del proyecto (ver
# CAT_ICONS en dashboard/dashboard_finanzas.html, CATEGORIAS_POR_PALABRA_
# CLAVE en leer_correo.py y CATEGORIA_KEYWORDS en tools/reconciliar_
# extractos.py) a uno de los 3 baldes -- criterio usado, documentado acá
# porque el requerimiento pidió explicar las que no son obvias:
#   - Necesidades: lo recurrente/difícil de evitar en lo inmediato
#     (comida, supermercado, servicios, salud, hogar, internet, celular,
#     transporte, movilidad, educación).
#   - Gustos: lo discrecional (restaurantes, entretenimiento, ropa,
#     compras, suscripciones, tecnología).
#   - Ahorro/deudas: todo lo directamente ligado a deuda de tarjeta
#     (pago_tarjeta_credito, avance_credito, crédito -- comisiones/avances
#     de tarjeta sin comercio asociado, ver reconciliar_extractos.py
#     normalizar_card(), e intereses) más "ahorro" (categoría sugerida
#     para cuando un aporte a una meta se registra a mano).
#   - Ambiguas, resueltas con criterio conservador (default a
#     "necesidades" -- explicado en el reporte, el usuario las puede
#     reasignar libremente sin tocar código):
#       * transferencias: puede ser un gasto real (arriendo compartido,
#         mesada) o plata "de paso" -- sin forma de saberlo del texto del
#         banco, se asume necesidad antes que gusto.
#       * retiro (cajero): mismo motivo -- no hay forma de saber en qué
#         se gastó el efectivo retirado.
#       * mascotas: cuidado recurrente de un dependiente, se trata como
#         necesidad, no como gusto ocasional.
#       * otros / salario: "otros" es el catch-all de lo no reconocido
#         (mismo criterio conservador); "salario" es ingreso, nunca gasto,
#         así que en la práctica esta asignación no afecta ningún cálculo
#         de "real gastado" por balde.
#   - Se incluyen ambas variantes de acento/sin-acento que existen de
#     verdad en el código (ej. "tecnología"/"tecnologia",
#     "educación"/"educacion", "crédito"/"credito") porque son literales
#     de texto exactos guardados en movimientos.categoria -- un mapeo
#     solo con acento dejaría sin asignar a la mitad de las filas reales.
CATEGORIA_BALDE_DEFAULT = {
    # Necesidades
    "comida": "necesidades", "supermercado": "necesidades", "servicios": "necesidades",
    "salud": "necesidades", "educación": "necesidades", "educacion": "necesidades",
    "hogar": "necesidades", "internet": "necesidades", "celular": "necesidades",
    "transporte": "necesidades", "movilidad": "necesidades", "transferencias": "necesidades",
    "mascotas": "necesidades", "retiro": "necesidades", "otros": "necesidades", "salario": "necesidades",
    # Gustos
    "restaurantes": "gustos", "entretenimiento": "gustos", "ropa": "gustos", "compras": "gustos",
    "suscripciones": "gustos", "tecnología": "gustos", "tecnologia": "gustos",
    # Ahorro/deudas
    "pago_tarjeta_credito": "ahorro_deudas", "avance_credito": "ahorro_deudas",
    "crédito": "ahorro_deudas", "credito": "ahorro_deudas", "intereses": "ahorro_deudas",
    "ahorro": "ahorro_deudas",
}
# Fallback para una categoría 100% personalizada (texto libre que el
# usuario escribió a mano en el formulario de registro, ver registrar.html
# y obtener_categorias()) que no coincide con ninguna de las de arriba --
# mismo criterio conservador ("necesidades" antes que "gustos") que las
# categorías ambiguas de la lista.
CATEGORIA_BALDE_FALLBACK = "necesidades"

VISTA_DEUDA_SQL = """
CREATE VIEW IF NOT EXISTS v_deuda_ledger AS
SELECT
    id,
    usuario_id,
    fecha,
    medio_pago AS tipo_movimiento,
    monto,
    descripcion,
    entidad,
    SUM(CASE WHEN medio_pago = 'pago_tarjeta_credito' THEN -monto ELSE monto END)
        OVER (PARTITION BY usuario_id ORDER BY fecha, id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS saldo_acumulado
FROM movimientos
WHERE medio_pago IN ('credito', 'avance_credito', 'pago_tarjeta_credito')
  AND moneda = 'COP'
ORDER BY fecha, id;
"""


def conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # journal_mode = DELETE (no WAL) a propósito: `data/` está montado
    # como bind mount de Docker Desktop en Windows, y WAL necesita memoria
    # compartida (mmap) entre procesos que ese tipo de montaje no soporta
    # bien -- cada vez que el contenedor se recreaba, la conexión fallaba
    # con "disk I/O error" al no poder abrir/mapear el -shm (causó una
    # caída real de `dev` el 2026-09-10). DELETE usa el journal clásico,
    # sin mmap, 100% compatible con bind mounts. Es un no-op si el archivo
    # ya está en DELETE (el caso normal); si algo lo vuelve a poner en WAL
    # (ej. una herramienta externa como DB Browser), esta línea lo corrige
    # solo en la siguiente conexión.
    conn.execute("PRAGMA journal_mode = DELETE")
    return conn


@contextmanager
def conexion():
    """Context manager sobre conectar(): garantiza conn.close() incluso
    si algo lanza una excepción en el medio. Reemplaza el patrón repetido
    `conn = db.conectar(); try: ...; finally: conn.close()` que se
    duplicaba en cada ruta de app.py -- mismo comportamiento, menos
    código repetido. Uso: `with db.conexion() as conn: ...`."""
    conn = conectar()
    try:
        yield conn
    finally:
        conn.close()


def _agregar_columna_si_falta(conn: sqlite3.Connection, tabla: str, columna: str, tipo_sql: str) -> None:
    """ALTER TABLE ... ADD COLUMN, tolerante a la carrera entre procesos:
    gunicorn arranca esta app con varios workers (ver Dockerfile), cada
    uno importa app.py por separado y cada uno corre crear_esquema() al
    boot -- si dos lo hacen casi al mismo tiempo, el chequeo previo de
    PRAGMA table_info() puede pasar en los dos ANTES de que cualquiera
    haya hecho el ALTER, y el segundo revienta con "duplicate column
    name" (esto pasó de verdad al desplegar referencia_bancaria).
    SQLite no tiene 'ADD COLUMN IF NOT EXISTS', así que se ataja acá:
    chequeo previo (evita el ALTER en el caso común) + tolerar el error
    puntual de "ya existe" si igual se cuela la carrera."""
    columnas = [r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})")]
    if columna in columnas:
        return
    try:
        conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo_sql}")
        conn.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e):
            raise  # cualquier otro error sí debe reventar, no ocultarlo


def _migrar_columna_usuario_id(conn: sqlite3.Connection) -> None:
    """Cada movimiento pasa a pertenecer a un usuario (multiusuario,
    2026-09-05). Nula por defecto en filas viejas; se asigna al admin la
    primera vez que corre esta migración (ver
    asignar_movimientos_sin_dueno_a_admin)."""
    _agregar_columna_si_falta(conn, "movimientos", "usuario_id", "INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_movimientos_usuario ON movimientos(usuario_id)")
    conn.commit()


def _migrar_columna_referencia_bancaria(conn: sqlite3.Connection) -> None:
    """Guarda la descripción "oficial" (del banco, por correo/PDF) cuando
    esa misma transacción ya existía como registro manual -- ver
    insertar_movimientos(). Nula en todo lo insertado antes de esta
    migración (2026-09-06) y en cualquier movimiento que nunca se haya
    conciliado contra una fuente automática."""
    _agregar_columna_si_falta(conn, "movimientos", "referencia_bancaria", "TEXT")


def _migrar_columna_tarjeta_id(conn: sqlite3.Connection) -> None:
    """Asocia un movimiento con la tarjeta de crédito propia que lo generó
    (2026-09-07, ver requisitos/2026-09-07_tarjetas-credito-cupo.md) --
    nullable, y NUNCA se completa retroactivamente para movimientos ya
    cargados antes de esta migración ni para ningún histórico en general:
    solo se resuelve para movimientos NUEVOS, dentro de
    insertar_movimientos(), por coincidencia EXACTA (y no ambigua) de
    últimos4 dígitos contra una tarjeta activa de ese usuario. FK "normal"
    (sin ON DELETE CASCADE/SET NULL) a propósito: con
    `PRAGMA foreign_keys = ON` (ver conectar()), SQLite mismo rechaza con
    IntegrityError el borrado de una tarjeta que todavía tenga movimientos
    asociados -- ver borrar_tarjeta()."""
    _agregar_columna_si_falta(conn, "movimientos", "tarjeta_id", "INTEGER REFERENCES tarjetas_credito(id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_movimientos_tarjeta ON movimientos(tarjeta_id)")
    conn.commit()


def _migrar_columna_meta_ahorro_id(conn: sqlite3.Connection) -> None:
    """Asocia un movimiento con la meta de ahorro que ese aporte alimenta
    (2026-09-08, ver requisitos/2026-09-08_presupuesto-ahorro-deudas.md)
    -- el aporte a una meta ES un movimiento más (típicamente tipo='gasto',
    plata que sale de la cuenta corriente hacia el ahorro), nunca un
    sistema paralelo de transferencias internas. nullable, y NUNCA se
    completa retroactivamente -- mismo criterio exacto que
    _migrar_columna_tarjeta_id() (mismo tipo de columna, misma FK
    'normal' sin ON DELETE CASCADE/SET NULL: con `PRAGMA foreign_keys =
    ON`, SQLite rechaza con IntegrityError el borrado de una meta que
    todavía tenga aportes asociados -- ver borrar_meta_ahorro())."""
    _agregar_columna_si_falta(conn, "movimientos", "meta_ahorro_id", "INTEGER REFERENCES metas_ahorro(id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_movimientos_meta_ahorro ON movimientos(meta_ahorro_id)")
    conn.commit()


def _migrar_columna_cedula_correo_config(conn: sqlite3.Connection) -> None:
    """correo_config ya existía (2026-09-06) sin esta columna en cualquier
    BD real donde ya se hubiera guardado alguna configuración -- CREATE
    TABLE IF NOT EXISTS no la agrega sola a una tabla que ya existe."""
    _agregar_columna_si_falta(conn, "correo_config", "cedula", "TEXT")


def _migrar_cifrado_correo_config(conn: sqlite3.Connection) -> None:
    """Cifra en el lugar cualquier fila de correo_config que haya
    quedado en texto plano de ANTES de que existiera cifrado.py
    (2026-09-06) -- email/app_password/cedula pasan a estar cifrados
    tanto para filas nuevas (ver guardar_correo_config) como viejas.
    cifrado.esta_cifrado() hace que sea seguro correr esto una y otra
    vez sin volver a cifrar un valor ya cifrado (lo dejaría ilegible)."""
    filas = conn.execute("SELECT usuario_id, app_password, cedula, email FROM correo_config").fetchall()
    for fila in filas:
        cambios = {}
        for campo in ("app_password", "cedula", "email"):
            valor = fila[campo]
            if valor and not cifrado.esta_cifrado(valor):
                cambios[campo] = cifrado.cifrar(valor)
        if cambios:
            set_sql = ", ".join(f"{c} = ?" for c in cambios)
            conn.execute(f"UPDATE correo_config SET {set_sql} WHERE usuario_id = ?",
                         (*cambios.values(), fila["usuario_id"]))
    if filas:
        conn.commit()


def _migrar_columna_detalle_correo_config(conn: sqlite3.Connection) -> None:
    """correo_config ya existía sin esta columna en cualquier BD real donde
    ya se hubiera guardado alguna configuración -- CREATE TABLE IF NOT
    EXISTS no la agrega sola a una tabla que ya existe (mismo patrón que
    _migrar_columna_cedula_correo_config)."""
    _agregar_columna_si_falta(conn, "correo_config", "ultima_corrida_detalle", "TEXT")


def crear_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA_SQL)
    _migrar_columna_usuario_id(conn)
    _migrar_columna_referencia_bancaria(conn)
    _migrar_columna_tarjeta_id(conn)  # después de ESQUEMA_SQL: necesita que tarjetas_credito ya exista (FK)
    _migrar_columna_meta_ahorro_id(conn)  # después de ESQUEMA_SQL: necesita que metas_ahorro ya exista (FK)
    _migrar_columna_cedula_correo_config(conn)
    _migrar_columna_detalle_correo_config(conn)
    _migrar_cifrado_correo_config(conn)
    # DROP + recrear la vista: si ya existía de antes de agregar usuario_id
    # a su SELECT, "CREATE VIEW IF NOT EXISTS" no la actualiza sola.
    conn.execute("DROP VIEW IF EXISTS v_deuda_ledger")
    conn.executescript(VISTA_DEUDA_SQL)
    conn.commit()


# ----------------------------- Clasificación (misma lógica ya validada) -----------------------------

def clasificar_medio_pago(descripcion: str) -> str:
    """Infiere el medio de pago a partir de patrones de texto típicos de
    las notificaciones bancarias de Bancolombia/Nequi/Nu.

    Valores posibles:
      - 'avance_credito'       → adelanto de efectivo de una tarjeta de crédito hacia una cuenta
      - 'credito'              → compra cargada a tarjeta de crédito (deuda, no caja)
      - 'pago_tarjeta_credito' → pago que abona/salda una tarjeta de crédito (caja real)
      - 'debito'               → todo lo demás: débito, efectivo, transferencias, QR, nómina, etc.
    """
    d = (descripcion or "").lower()
    if "avance" in d and ("t.cred" in d or "tcred" in d or "tarjeta de cr" in d):
        return "avance_credito"
    if "t.cred" in d or "tcred" in d:
        return "credito"
    if "pago tarjeta" in d or "pago tdc" in d or "pago t.cred" in d or "pago a tarjeta" in d:
        return "pago_tarjeta_credito"
    return "debito"


def enriquecer_movimiento(row: dict) -> dict:
    """Agrega 'medio_pago' y 'es_deuda', y reclasifica los casos especiales
    acordados: avance de crédito pasa a 'ingreso' marcado como deuda; compra
    a crédito sigue siendo 'gasto' pero marcada como deuda (no caja real
    todavía); pago de tarjeta se recategoriza y es_deuda=False (sí es caja
    real, liquida deuda)."""
    row = dict(row)
    medio = clasificar_medio_pago(str(row.get("descripcion", "")))
    row["medio_pago"] = medio

    if medio == "avance_credito":
        row["tipo"] = "ingreso"
        row["categoria"] = "avance_credito"
        row["es_deuda"] = True
    elif medio == "credito":
        row["es_deuda"] = (row.get("tipo") == "gasto")
    elif medio == "pago_tarjeta_credito":
        row["categoria"] = "pago_tarjeta_credito"
        row["es_deuda"] = False
    else:
        row["es_deuda"] = False

    return row


# ----------------------------- Lectura del Excel -----------------------------

def leer_movimientos_excel() -> list[dict]:
    """Lee la hoja 'movimientos' del Excel (solo lectura, nunca escribe)."""
    import openpyxl

    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    if SHEET_MOVIMIENTOS not in wb.sheetnames:
        raise ValueError(f"La hoja '{SHEET_MOVIMIENTOS}' no existe en {XLSX_PATH.name}.")
    ws = wb[SHEET_MOVIMIENTOS]

    rows = []
    headers = None
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True)):
        if i == 0:
            headers = [str(h).strip() if h else h for h in row]
            continue
        if row[0] is None:
            continue
        d = dict(zip(headers, row))

        fecha = d.get("fecha")
        if isinstance(fecha, (datetime.datetime, datetime.date)):
            d["fecha"] = fecha.strftime("%Y-%m-%d")
        elif fecha is not None:
            d["fecha"] = str(fecha)

        monto = d.get("monto")
        d["monto"] = float(monto) if monto is not None else 0.0

        for campo in CAMPOS_ESPERADOS:
            d.setdefault(campo, "")

        rows.append(d)

    if not rows:
        raise ValueError("No se encontraron movimientos en la hoja — el Excel podría estar vacío o mal formado.")
    return rows


def leer_historial_excel() -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    if SHEET_HISTORIAL not in wb.sheetnames:
        return []
    ws = wb[SHEET_HISTORIAL]

    rows = []
    headers = None
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True)):
        if i == 0:
            headers = [str(h).strip() if h else h for h in row]
            continue
        if row[0] is None:
            continue
        d = dict(zip(headers, row))
        for k in ("fecha_actualizacion", "fecha_inicio_importada", "fecha_fin_importada"):
            v = d.get(k)
            if isinstance(v, (datetime.datetime, datetime.date)):
                d[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
        rows.append(d)
    return rows


# ----------------------------- Sincronización Excel -> SQLite -----------------------------

def sincronizar_desde_excel(conn: sqlite3.Connection) -> dict:
    """Reemplaza el contenido de origen='gmail_bot_excel' con lo que hay
    ahora mismo en el Excel. Mientras el Excel sea la única fuente de
    escritura (fase actual), esto es seguro y simple: el Excel manda.
    Cuando existan otras fuentes de ingesta, dejará de borrar-y-recargar y
    pasará a hacer un merge con dedup por (fecha, monto)."""
    # El Excel es de una sola persona (el dueño original de la app) -- todo
    # lo que sincroniza acá se le asigna a la cuenta 'admin'.
    admin = conn.execute("SELECT id FROM usuarios WHERE rol = 'admin' LIMIT 1").fetchone()
    admin_id = admin["id"] if admin else None

    movimientos = [enriquecer_movimiento(m) for m in leer_movimientos_excel()]
    for m in movimientos:
        m["usuario_id"] = admin_id
    historial = leer_historial_excel()

    cur = conn.cursor()
    cur.execute("DELETE FROM movimientos WHERE origen = 'gmail_bot_excel'")
    cur.executemany(
        """INSERT INTO movimientos (fecha, tipo, categoria, moneda, monto, descripcion, entidad, medio_pago, es_deuda, origen, usuario_id)
           VALUES (:fecha, :tipo, :categoria, :moneda, :monto, :descripcion, :entidad, :medio_pago, :es_deuda, 'gmail_bot_excel', :usuario_id)""",
        movimientos,
    )

    cur.execute("DELETE FROM historial_actualizaciones WHERE origen = 'gmail_bot_excel'")
    for h in historial:
        cur.execute(
            """INSERT INTO historial_actualizaciones
               (fecha_actualizacion, fecha_inicio_importada, fecha_fin_importada, movimientos_agregados, origen)
               VALUES (?, ?, ?, ?, 'gmail_bot_excel')""",
            (
                h.get("fecha_actualizacion"),
                h.get("fecha_inicio_importada"),
                h.get("fecha_fin_importada"),
                h.get("movimientos_agregados"),
            ),
        )
    conn.commit()

    return {
        "movimientos": len(movimientos),
        "historial": len(historial),
        "fecha_min": min((m["fecha"] for m in movimientos if m["fecha"]), default=None),
        "fecha_max": max((m["fecha"] for m in movimientos if m["fecha"]), default=None),
        "en_deuda": sum(1 for m in movimientos if m["es_deuda"]),
    }


# ----------------------------- Consultas para el dashboard -----------------------------

def obtener_movimientos(conn: sqlite3.Connection, usuario_id: int | None = None) -> list[dict]:
    """usuario_id=None trae TODO (uso interno/admin explícito) -- las
    rutas de la app siempre deben pasar un usuario_id real."""
    # origen/creado_en/referencia_bancaria: para poder distinguir en el
    # dashboard qué se cargó a mano y qué llegó solo (correo/PDF/Excel),
    # y cuándo -- ayuda a decidir/confiar en cada movimiento, no solo a
    # verlo (pedido explícito 2026-09-06).
    # tarjeta_id (2026-09-07, ver requisitos/2026-09-07_editar-borrar-movimiento.md):
    # el formulario de edición precarga sus datos desde ESTE array (el
    # documento asume explícitamente que ya viaja acá, "no hace falta un
    # endpoint de lectura nuevo") -- sin este campo el selector de
    # tarjeta del modal de edición no podría saber cuál venía asignada.
    # meta_ahorro_id (2026-09-08, ver
    # requisitos/2026-09-08_presupuesto-ahorro-deudas.md): mismo criterio
    # -- viaja acá para que el frontend pueda mostrar "este movimiento es
    # un aporte a <meta>" sin un endpoint de lectura aparte.
    sql = """SELECT id, fecha, tipo, categoria, moneda, monto, descripcion, entidad, medio_pago, es_deuda,
                    origen, referencia_bancaria, creado_en, tarjeta_id, meta_ahorro_id
             FROM movimientos"""
    params = ()
    if usuario_id is not None:
        sql += " WHERE usuario_id = ?"
        params = (usuario_id,)
    sql += " ORDER BY fecha, id"

    out = []
    for r in conn.execute(sql, params).fetchall():
        d = dict(r)
        d["es_deuda"] = bool(d["es_deuda"])
        out.append(d)
    return out


# ----------------------------- Usuarios / login -----------------------------

def crear_usuario(conn: sqlite3.Connection, username: str, password: str, rol: str, nombre_mostrado: str) -> int:
    """La contraseña se guarda SIEMPRE hasheada (nunca en texto plano),
    con el algoritmo por defecto de Werkzeug (scrypt)."""
    cur = conn.execute(
        "INSERT INTO usuarios (username, password_hash, rol, nombre_mostrado) VALUES (?, ?, ?, ?)",
        (username, generate_password_hash(password), rol, nombre_mostrado),
    )
    conn.commit()
    return cur.lastrowid


def actualizar_usuario(conn: sqlite3.Connection, usuario_id: int, username: str = None,
                        nombre_mostrado: str = None, password: str = None, rol: str = None) -> None:
    """Actualiza solo los campos que se pasen (None = no tocar ese campo).
    La contraseña, si se pasa, se hashea acá mismo -- nunca se guarda en
    texto plano, igual que en crear_usuario()."""
    campos, valores = [], []
    if username is not None:
        campos.append("username = ?"); valores.append(username)
    if nombre_mostrado is not None:
        campos.append("nombre_mostrado = ?"); valores.append(nombre_mostrado)
    if rol is not None:
        campos.append("rol = ?"); valores.append(rol)
    if password:
        campos.append("password_hash = ?"); valores.append(generate_password_hash(password))
    if not campos:
        return
    valores.append(usuario_id)
    conn.execute(f"UPDATE usuarios SET {', '.join(campos)} WHERE id = ?", valores)
    conn.commit()


def verificar_login(conn: sqlite3.Connection, username: str, password: str) -> dict | None:
    """Verifica las credenciales contra las cuentas registradas con ese
    nombre de usuario y devuelve la cuenta correspondiente si coinciden."""
    candidatos = conn.execute("SELECT * FROM usuarios WHERE username = ?", (username,)).fetchall()
    for c in candidatos:
        if check_password_hash(c["password_hash"], password):
            return dict(c)
    return None


def listar_usuarios(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT id, username, rol, nombre_mostrado FROM usuarios ORDER BY id")]


# ----------------------------- Configuración de lectura de correo -----------------------------
# email/app_password/cedula se guardan CIFRADOS en la columna (ver
# cifrado.py) -- esta es la ÚNICA capa que cifra/descifra; el resto del
# código (routes/correo.py, leer_correo.py) siempre trabaja con texto
# plano en memoria, como si el cifrado no existiera.

def _descifrar_fila_correo(fila: dict) -> dict:
    """Si algún campo no se puede descifrar (clave distinta, dato
    corrupto), queda en None en vez de tumbar toda la cuenta -- el login
    IMAP/PDF va a fallar igual con un error claro más adelante, pero no
    rompe el procesamiento de las DEMÁS cuentas en listar_correo_configs_activos()."""
    fila = dict(fila)
    for campo in ("email", "app_password", "cedula"):
        valor = fila.get(campo)
        if valor:
            try:
                fila[campo] = cifrado.descifrar(valor)
            except ValueError:
                fila[campo] = None
    return fila


def obtener_correo_config(conn: sqlite3.Connection, usuario_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM correo_config WHERE usuario_id = ?", (usuario_id,)).fetchone()
    return _descifrar_fila_correo(r) if r else None


def listar_correo_configs_activos(conn: sqlite3.Connection) -> list[dict]:
    """Todas las cuentas con la automatización encendida -- lo que
    leer_correo.py recorre en cada corrida de la tarea programada."""
    return [_descifrar_fila_correo(r) for r in conn.execute("SELECT * FROM correo_config WHERE activo = 1")]


def guardar_correo_config(
    conn: sqlite3.Connection,
    usuario_id: int,
    email: str,
    app_password: str | None = None,
    imap_host: str = "imap.gmail.com",
    imap_port: int = 993,
    cedula: str | None = None,
    frecuencia_tipo: str = "intervalo",
    frecuencia_minutos: int = 30,
    frecuencia_hora: str | None = None,
    activo: bool = True,
) -> None:
    """Crea o actualiza la configuración de correo de un usuario (una fila
    por usuario_id). `app_password=None` (o vacío) significa "no cambiar
    la que ya había guardada" -- así el formulario de edición no obliga a
    reescribirla cada vez que se toca cualquier otro campo (ej. la
    frecuencia). Es obligatoria la primera vez que se guarda esta cuenta.
    `cedula` es opcional (solo hace falta si se quiere que también se
    abran PDFs de extracto adjuntos, cifrados con ese número) y sigue el
    mismo criterio: vacío = no tocar la que ya había."""
    existente = obtener_correo_config(conn, usuario_id)  # ya viene descifrado (ver _descifrar_fila_correo)
    if not app_password:
        if not existente:
            raise ValueError("Falta la contraseña de aplicación (obligatoria la primera vez que se configura).")
        app_password = existente["app_password"]
    if not cedula and existente:
        cedula = existente["cedula"]

    conn.execute(
        """
        INSERT INTO correo_config
            (usuario_id, email, app_password, imap_host, imap_port, cedula, activo,
             frecuencia_tipo, frecuencia_minutos, frecuencia_hora, actualizado_en)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(usuario_id) DO UPDATE SET
            email = excluded.email,
            app_password = excluded.app_password,
            imap_host = excluded.imap_host,
            imap_port = excluded.imap_port,
            cedula = excluded.cedula,
            activo = excluded.activo,
            frecuencia_tipo = excluded.frecuencia_tipo,
            frecuencia_minutos = excluded.frecuencia_minutos,
            frecuencia_hora = excluded.frecuencia_hora,
            actualizado_en = excluded.actualizado_en
        """,
        (usuario_id, cifrado.cifrar(email), cifrado.cifrar(app_password), imap_host, imap_port,
         cifrado.cifrar(cedula), int(bool(activo)), frecuencia_tipo, frecuencia_minutos, frecuencia_hora),
    )
    conn.commit()


def actualizar_estado_correo(conn: sqlite3.Connection, usuario_id: int, ok: bool, error: str | None = None,
                              detalle: dict | None = None) -> None:
    """Deja constancia del resultado de la última corrida -- lo que se
    muestra en la interfaz ("última sincronización: hace 12 min, OK").

    `detalle` (2026-09-10, opcional): diccionario JSON-serializable con el
    detalle técnico de ESTA corrida puntual -- cuánto tardó, cuántos
    correos encontró, nuevos/duplicados, categorías, y una lista acotada
    de los movimientos concretos (ver leer_correo.py::procesar_cuenta,
    que lo arma). Acá solo se serializa y guarda tal cual, sin
    interpretarlo -- lo interpreta el frontend (routes/correo.py expone
    esta columna al template, que solo la muestra si `usuario_rol ==
    'admin'`: un usuario normal ve el resumen de siempre, no el detalle
    técnico). None (default) borra cualquier detalle anterior -- una
    corrida que no lo calculó (ej. un error temprano, antes de llegar a
    armarlo) no debe dejar viendo el detalle de la corrida ANTERIOR como
    si fuera de esta."""
    conn.execute(
        "UPDATE correo_config SET ultima_corrida = datetime('now', 'localtime'), "
        "ultima_corrida_ok = ?, ultimo_error = ?, ultima_corrida_detalle = ? WHERE usuario_id = ?",
        (int(bool(ok)), error, json.dumps(detalle, ensure_ascii=False) if detalle is not None else None, usuario_id),
    )
    conn.commit()


def eliminar_correo_config(conn: sqlite3.Connection, usuario_id: int) -> None:
    conn.execute("DELETE FROM correo_config WHERE usuario_id = ?", (usuario_id,))
    conn.commit()


# ----------------------------- Vistas ocultas por usuario (admin) -----------------------------

def vistas_ocultas_de(conn: sqlite3.Connection, usuario_id: int) -> set[str]:
    """Qué vistas tiene ocultas ESTE usuario puntual -- ausencia de fila
    significa "visible" (default), así que un usuario sin ninguna
    restricción devuelve un set vacío."""
    return {r["vista"] for r in conn.execute("SELECT vista FROM vistas_ocultas WHERE usuario_id = ?", (usuario_id,))}


def vistas_ocultas_todos(conn: sqlite3.Connection) -> dict[int, set[str]]:
    """Igual que vistas_ocultas_de() pero para TODOS los usuarios de una
    sola pasada -- lo usa la página de administración para pintar la
    grilla completa sin una consulta por usuario."""
    mapa: dict[int, set[str]] = {}
    for r in conn.execute("SELECT usuario_id, vista FROM vistas_ocultas"):
        mapa.setdefault(r["usuario_id"], set()).add(r["vista"])
    return mapa


def ocultar_vista(conn: sqlite3.Connection, usuario_id: int, vista: str) -> None:
    conn.execute("INSERT OR IGNORE INTO vistas_ocultas (usuario_id, vista) VALUES (?, ?)", (usuario_id, vista))
    conn.commit()


def mostrar_vista(conn: sqlite3.Connection, usuario_id: int, vista: str) -> None:
    conn.execute("DELETE FROM vistas_ocultas WHERE usuario_id = ? AND vista = ?", (usuario_id, vista))
    conn.commit()


def obtener_usuario(conn: sqlite3.Connection, usuario_id: int) -> dict | None:
    r = conn.execute("SELECT id, username, rol, nombre_mostrado FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    return dict(r) if r else None


def asignar_movimientos_sin_dueno_a_admin(conn: sqlite3.Connection) -> int:
    """Los movimientos que ya existían antes del sistema de usuarios
    (usuario_id NULL) son todos del dueño original de la app -- se le
    asignan a la cuenta 'admin' la primera vez que corre esto."""
    admin = conn.execute("SELECT id FROM usuarios WHERE rol = 'admin' LIMIT 1").fetchone()
    if not admin:
        return 0
    cur = conn.execute("UPDATE movimientos SET usuario_id = ? WHERE usuario_id IS NULL", (admin["id"],))
    conn.commit()
    return cur.rowcount


def obtener_categorias(conn: sqlite3.Connection, usuario_id: int | None = None) -> list[str]:
    """Categorías distintas ya usadas, para autocompletar el formulario de
    registro manual (evita que cada quien escriba la misma categoría con
    variantes distintas). Filtradas por usuario: cada quien autocompleta
    con SU propio historial."""
    sql = "SELECT DISTINCT categoria FROM movimientos WHERE categoria IS NOT NULL AND categoria != ''"
    params = ()
    if usuario_id is not None:
        sql += " AND usuario_id = ?"
        params = (usuario_id,)
    sql += " ORDER BY categoria"
    return [r["categoria"] for r in conn.execute(sql, params).fetchall()]


def obtener_entidades(conn: sqlite3.Connection, usuario_id: int | None = None) -> list[str]:
    sql = "SELECT DISTINCT entidad FROM movimientos WHERE entidad IS NOT NULL AND entidad != ''"
    params = ()
    if usuario_id is not None:
        sql += " AND usuario_id = ?"
        params = (usuario_id,)
    sql += " ORDER BY entidad"
    return [r["entidad"] for r in conn.execute(sql, params).fetchall()]


def obtener_ledger_deuda(conn: sqlite3.Connection, usuario_id: int | None = None) -> list[dict]:
    sql = "SELECT fecha, tipo_movimiento, monto, descripcion, entidad, saldo_acumulado FROM v_deuda_ledger"
    params = ()
    if usuario_id is not None:
        sql += " WHERE usuario_id = ?"
        params = (usuario_id,)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ----------------------------- Tarjetas de crédito (cupo, 2026-09-07) -----------------------------
# Ver requisitos/2026-09-07_tarjetas-credito-cupo.md para el diseño
# completo. Sin cifrado a propósito (nombre/entidad/cupo_total/ultimos4
# son datos financieros, no credenciales -- ver sección "Cifrado" del
# documento). Todo filtrado por usuario_id EXPLÍCITO, análogo a
# obtener_categorias()/obtener_entidades() -- las rutas (routes/tarjetas.py)
# siempre pasan viendo_id(), nunca session["usuario_id"] a secas: son
# datos/contenido de la cuenta que se esté viendo, mismo criterio que el
# resto del dashboard (ver auth.py::viendo_id()).

def crear_tarjeta(conn: sqlite3.Connection, usuario_id: int, nombre: str, cupo_total: float,
                   entidad: str | None = None, ultimos4: str | None = None) -> int:
    """cupo_total es obligatorio y > 0 (validado acá, no solo en la UI --
    ver requisitos, "Cupo total es obligatorio").

    Si viene ultimos4, dispara reasociar_movimientos_huerfanos() para esa
    tarjeta recién creada (2026-09-10): es el caso típico de "ya tenía
    gastos de esta tarjeta cargados, pero la tarjeta en sí la doy de alta
    recién ahora" -- sin esto, esos movimientos viejos quedarían
    huérfanos para siempre (ver el docstring de esa función)."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("Falta el nombre de la tarjeta.")
    if cupo_total is None or cupo_total <= 0:
        raise ValueError("El cupo total tiene que ser mayor a 0.")
    entidad = (entidad or "").strip() or None
    ultimos4 = (ultimos4 or "").strip() or None
    cur = conn.execute(
        "INSERT INTO tarjetas_credito (usuario_id, nombre, entidad, cupo_total, ultimos4) VALUES (?, ?, ?, ?, ?)",
        (usuario_id, nombre, entidad, cupo_total, ultimos4),
    )
    tarjeta_id = cur.lastrowid
    conn.commit()
    if ultimos4:
        reasociar_movimientos_huerfanos(conn, usuario_id, tarjeta_id=tarjeta_id)
    return tarjeta_id


def obtener_tarjetas(conn: sqlite3.Connection, usuario_id: int, solo_activas: bool = False) -> list[dict]:
    """Todas las tarjetas (o solo las activas) de usuario_id -- nunca de
    otro usuario, `usuario_id` siempre explícito en el WHERE."""
    sql = "SELECT * FROM tarjetas_credito WHERE usuario_id = ?"
    params = [usuario_id]
    if solo_activas:
        sql += " AND activa = 1"
    sql += " ORDER BY activa DESC, nombre"
    out = []
    for r in conn.execute(sql, params).fetchall():
        d = dict(r)
        d["activa"] = bool(d["activa"])
        out.append(d)
    return out


def obtener_tarjeta(conn: sqlite3.Connection, usuario_id: int, tarjeta_id: int) -> dict | None:
    """None si no existe O si existe pero es de otro usuario -- el
    aislamiento se hace acá mismo con el AND en el WHERE, nunca
    filtrando después en Python (nunca se le devuelve al llamador una
    fila de otra cuenta para que decida qué hacer con ella)."""
    r = conn.execute(
        "SELECT * FROM tarjetas_credito WHERE id = ? AND usuario_id = ?", (tarjeta_id, usuario_id)
    ).fetchone()
    if not r:
        return None
    d = dict(r)
    d["activa"] = bool(d["activa"])
    return d


def actualizar_tarjeta(conn: sqlite3.Connection, usuario_id: int, tarjeta_id: int, nombre: str | None = None,
                        entidad: str | None = None, cupo_total: float | None = None,
                        ultimos4: str | None = None) -> bool:
    """Actualiza solo los campos presentes (None = no tocar), mismo
    criterio que actualizar_usuario(). Un string vacío SÍ es una
    actualización explícita: "" en entidad/ultimos4 los limpia (quedan
    NULL, son opcionales); nombre es obligatorio y no puede quedar vacío
    -- lanza ValueError en ese caso, igual que cupo_total <= 0. Devuelve
    False si la tarjeta no existe o no es de usuario_id (aislamiento:
    nunca edita la de otro usuario aunque el id exista).

    Si ultimos4 se está SETEANDO a un valor no vacío (ya sea que antes
    estuviera vacío o cambiando por otro), dispara
    reasociar_movimientos_huerfanos() para esta tarjeta, mismo criterio y
    mismo motivo que crear_tarjeta() -- cubre el caso de "ya tenía la
    tarjeta creada pero sin el último-4 cargado, y recién ahora lo
    completo"."""
    if obtener_tarjeta(conn, usuario_id, tarjeta_id) is None:
        return False

    campos, valores = [], []
    if nombre is not None:
        nombre = nombre.strip()
        if not nombre:
            raise ValueError("El nombre no puede quedar vacío.")
        campos.append("nombre = ?"); valores.append(nombre)
    if entidad is not None:
        campos.append("entidad = ?"); valores.append(entidad.strip() or None)
    if cupo_total is not None:
        if cupo_total <= 0:
            raise ValueError("El cupo total tiene que ser mayor a 0.")
        campos.append("cupo_total = ?"); valores.append(cupo_total)
    ultimos4_nuevo = ultimos4.strip() or None if ultimos4 is not None else None
    if ultimos4 is not None:
        campos.append("ultimos4 = ?"); valores.append(ultimos4_nuevo)

    if campos:
        campos.append("actualizado_en = datetime('now', 'localtime')")
        valores.extend([tarjeta_id, usuario_id])
        conn.execute(f"UPDATE tarjetas_credito SET {', '.join(campos)} WHERE id = ? AND usuario_id = ?", valores)
        conn.commit()
    if ultimos4_nuevo:
        reasociar_movimientos_huerfanos(conn, usuario_id, tarjeta_id=tarjeta_id)
    return True


def archivar_tarjeta(conn: sqlite3.Connection, usuario_id: int, tarjeta_id: int) -> bool:
    """Soft delete: deja de listarse entre las 'activas' (selectores de
    Registrar movimiento, desglose del Dashboard, matching automático por
    últimos4) pero conserva intacto el historial de movimientos que ya
    tenía asociados. False si no existe o no es de usuario_id."""
    cur = conn.execute(
        "UPDATE tarjetas_credito SET activa = 0, actualizado_en = datetime('now', 'localtime') "
        "WHERE id = ? AND usuario_id = ?",
        (tarjeta_id, usuario_id),
    )
    conn.commit()
    return cur.rowcount > 0


def borrar_tarjeta(conn: sqlite3.Connection, usuario_id: int, tarjeta_id: int) -> tuple[bool, str | None]:
    """Borrado DEFINITIVO -- solo permitido si la tarjeta nunca tuvo
    ningún movimiento asociado. `tarjeta_id` en movimientos es una FK
    "normal" (sin ON DELETE CASCADE/SET NULL, ver
    _migrar_columna_tarjeta_id()): con `PRAGMA foreign_keys = ON` (ver
    conectar()), SQLite mismo rechaza el DELETE con IntegrityError si hay
    movimientos que la referencian -- alcanza con capturarlo acá, sin un
    chequeo manual previo (menos margen para una condición de carrera
    entre el chequeo y el borrado). Devuelve (ok, mensaje_de_error);
    mensaje_de_error es None si ok=True."""
    if obtener_tarjeta(conn, usuario_id, tarjeta_id) is None:
        return False, "Esa tarjeta no existe."
    try:
        conn.execute("DELETE FROM tarjetas_credito WHERE id = ? AND usuario_id = ?", (tarjeta_id, usuario_id))
        conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "Esa tarjeta tiene movimientos asociados -- archivala en vez de borrarla."


def _resolver_tarjeta_por_ultimos4(conn: sqlite3.Connection, usuario_id: int, ultimos4: str | None) -> int | None:
    """Auto-asociación al insertar un movimiento nuevo (ver
    insertar_movimientos()): solo asocia si hay EXACTAMENTE una tarjeta
    ACTIVA de usuario_id con esos últimos4 -- 0 coincidencias (no
    detectado / tarjeta no registrada) o 2+ (ambigüedad, ej. tarjeta
    reemplazada con el mismo último-4) nunca se adivinan, el movimiento
    queda sin tarjeta (NULL)."""
    if not ultimos4:
        return None
    filas = conn.execute(
        "SELECT id FROM tarjetas_credito WHERE usuario_id = ? AND activa = 1 AND ultimos4 = ?",
        (usuario_id, ultimos4),
    ).fetchall()
    return filas[0]["id"] if len(filas) == 1 else None


# Exige la palabra "tarjeta"/"T.Cred"/"card" a poco trecho del "*XXXX"
# -- un extracto de tarjeta también puede mencionar el último-4 de una
# CUENTA destino en la misma descripción (ej. "Avance T.Cred *4821 a
# cta *5360", ver tools/reconciliar_extractos.py::_formatear_movimiento):
# sin ese contexto, un "*XXXX" suelto es ambiguo y NO debe capturarse.
# "terminada/termina en XXXX" es el otro patrón frecuente cuando alguien
# lo escribe a mano en la descripción de un registro manual (ver
# templates/registrar.html, que no tiene un campo dedicado de
# últimos4).
_RE_ULTIMOS4_EN_TEXTO = re.compile(
    r"(?:tarjeta|t\.?\s*cred(?:ito)?|card)\D{0,20}?\*\s*(\d{4})\b"
    r"|termin(?:ada|a)\s+en\s+(\d{4})\b",
    re.IGNORECASE,
)


def _extraer_ultimos4_de_texto(texto: str | None) -> str | None:
    """Busca un patrón "...tarjeta *4821" / "T.Cred *4821" / "terminada
    en 4821" dentro de texto libre (típicamente la descripción de un
    movimiento) -- ver _RE_ULTIMOS4_EN_TEXTO para el porqué del
    contexto exigido. None si no encuentra nada: mismo criterio de "no
    adivinar" que _resolver_tarjeta_por_ultimos4."""
    if not texto:
        return None
    m = _RE_ULTIMOS4_EN_TEXTO.search(texto)
    if not m:
        return None
    return m.group(1) or m.group(2)


def reasociar_movimientos_huerfanos(conn: sqlite3.Connection, usuario_id: int, tarjeta_id: int | None = None) -> int:
    """Backfill retroactivo (2026-09-10, ver el pedido del usuario de
    "un trigger que asocie tanto movimientos viejos de tarjetas no
    agregadas como nuevos a tarjetas ya registradas"): recorre los
    movimientos de usuario_id que quedaron con tarjeta_id NULL y les
    intenta asociar una tarjeta ahora mismo, usando el mismo
    _extraer_ultimos4_de_texto()/_resolver_tarjeta_por_ultimos4() que
    corre al insertar (ver insertar_movimientos()) -- así que aplica la
    MISMA regla de "nunca adivinar" (0 o 2+ tarjetas activas
    coincidentes deja el movimiento sin tocar).

    Esto reemplaza deliberadamente la política previa documentada en
    insertar_movimientos() ("nada se reasigna retroactivamente, ni
    siquiera implícitamente") -- el usuario pidió explícitamente lo
    contrario para este caso: una tarjeta que se registra DESPUÉS de
    tener movimientos ya cargados (típicamente porque el usuario recién
    ahora la dio de alta en "Mis tarjetas") debe "adoptar" los
    movimientos viejos que la mencionan, en vez de quedar huérfanos para
    siempre. Se llama automáticamente desde crear_tarjeta() y desde
    actualizar_tarjeta() cuando cambia ultimos4 -- nunca hace falta
    invocarla a mano.

    `tarjeta_id`, si se pasa, acota el barrido a los huérfanos que
    matchean ESA tarjeta puntual (el caso común: se acaba de crear/
    editar una sola tarjeta) -- se sigue re-chequeando ambigüedad contra
    TODAS las tarjetas activas del usuario, no solo esa, para no asociar
    un movimiento que en realidad es ambiguo entre dos tarjetas con el
    mismo último-4. Sin `tarjeta_id` (None) barre todos los huérfanos del
    usuario contra cualquier tarjeta activa -- pensado para poder
    invocarse también como mantenimiento general a futuro.

    Devuelve cuántos movimientos quedaron asociados."""
    huerfanos = conn.execute(
        "SELECT id, descripcion FROM movimientos WHERE usuario_id = ? AND tarjeta_id IS NULL",
        (usuario_id,),
    ).fetchall()
    asociados = 0
    for fila in huerfanos:
        ultimos4 = _extraer_ultimos4_de_texto(fila["descripcion"])
        if not ultimos4:
            continue
        resuelto = _resolver_tarjeta_por_ultimos4(conn, usuario_id, ultimos4)
        if resuelto is None:
            continue
        if tarjeta_id is not None and resuelto != tarjeta_id:
            continue  # matchea OTRA tarjeta activa -- no es el barrido que se pidió, se deja para su propia corrida
        conn.execute("UPDATE movimientos SET tarjeta_id = ? WHERE id = ?", (resuelto, fila["id"]))
        asociados += 1
    if asociados:
        conn.commit()
    return asociados


def obtener_tarjetas_con_deuda(conn: sqlite3.Connection, usuario_id: int) -> dict:
    """Cupo/deuda/disponible POR TARJETA activa, con la MISMA lógica de
    signo que v_deuda_ledger (créditos/avances suman, pago_tarjeta_credito
    resta) y el mismo filtro moneda='COP' -- así "deuda por tarjeta"
    (todas) + "sin_asignar" siempre cuadra con el agregado global que ya
    muestra el KPI "Deuda actual estimada" (mismo total, agrupado
    distinto: acá por tarjeta_id, allá acumulado cronológicamente).

    Sin redondear acá a propósito -- igual que saldo_acumulado de
    v_deuda_ledger, que tampoco se redondea server-side (ver
    dashboard_finanzas.html::fmtNum, que aplica Math.round() recién al
    formatear en pantalla): redondear en dos capas con criterios
    distintos es justo lo que rompería que la suma cuadre centavo a
    centavo.

    Devuelve {"activas": [...], "sin_asignar": <float>}. "sin_asignar" NO
    se calcula filtrando literalmente `tarjeta_id IS NULL` -- se calcula
    como `deuda_total - suma(deuda de las tarjetas activas)`, es decir
    "todo lo que no está desglosado en 'activas'". Con el filtro literal,
    archivar una tarjeta que ya tenía movimientos asociados hacía
    desaparecer esa deuda del desglose por completo: dejaba de contar en
    "activas" (correcto) pero tampoco caía en "sin_asignar" porque su
    `tarjeta_id` seguía apuntando a la tarjeta archivada (no es NULL), así
    que "activas + sin_asignar" quedaba por debajo del agregado real de
    v_deuda_ledger -- rompiendo la invariante que pide el documento de
    requisitos. Con esta definición la invariante se cumple POR
    CONSTRUCCIÓN, sin caso especial: "sin_asignar" pasa a significar "no
    visible en el desglose de tarjetas activas" (incluye tanto los
    movimientos realmente sin tarjeta como los de cualquier tarjeta ya
    archivada), no literalmente "sin tarjeta_id"."""
    filas = conn.execute(
        """SELECT tarjeta_id,
                  SUM(CASE WHEN medio_pago = 'pago_tarjeta_credito' THEN -monto ELSE monto END) AS deuda
           FROM movimientos
           WHERE usuario_id = ?
             AND medio_pago IN ('credito', 'avance_credito', 'pago_tarjeta_credito')
             AND moneda = 'COP'
           GROUP BY tarjeta_id""",
        (usuario_id,),
    ).fetchall()
    deuda_por_tarjeta = {f["tarjeta_id"]: (f["deuda"] or 0.0) for f in filas}
    deuda_total = sum(deuda_por_tarjeta.values())

    activas = []
    deuda_activas_total = 0.0
    for t in obtener_tarjetas(conn, usuario_id, solo_activas=True):
        deuda_actual = deuda_por_tarjeta.get(t["id"], 0.0)
        deuda_activas_total += deuda_actual
        activas.append({
            **t,
            "deuda_actual": deuda_actual,
            "cupo_disponible": t["cupo_total"] - deuda_actual,  # puede dar negativo -- nunca se trunca a 0
            "porcentaje_uso": (deuda_actual / t["cupo_total"] * 100) if t["cupo_total"] else 0.0,
        })

    sin_asignar = deuda_total - deuda_activas_total

    return {"activas": activas, "sin_asignar": sin_asignar}


# ----------------------------- Presupuesto por baldes / metas de ahorro (2026-09-08) -----------------------------
# Ver requisitos/2026-09-08_presupuesto-ahorro-deudas.md para el diseño
# completo. Sin cifrado a propósito (montos/porcentajes, no credenciales
# -- misma justificación que tarjetas_credito). Todo filtrado por
# usuario_id EXPLÍCITO; las rutas (routes/presupuesto.py) siempre pasan
# viendo_id(), nunca session["usuario_id"] a secas -- presupuesto/
# categoria_balde/metas_ahorro son CONTENIDO de la cuenta que se esté
# viendo (igual que tarjetas/movimientos/perfil financiero), no
# autoservicio ligado a la identidad de quien inició sesión.

def obtener_presupuesto(conn: sqlite3.Connection, usuario_id: int) -> dict:
    """Los 3 porcentajes de usuario_id. Si todavía no configuró nada
    (ninguna fila guardada), devuelve el default 50/30/20
    (PRESUPUESTO_PCT_DEFAULT) con "configurado"=False -- así el
    dashboard puede mostrar "presupuestado" desde el primer momento
    (cumple "50/30/20 ya cargado por defecto") sin romperse ni mostrar
    NaN en una cuenta nueva, y a la vez el frontend sabe si mostrar la
    invitación a "todavía no configuraste esto, tocalo para ajustarlo".
    "suma_pct" viaja siempre calculado -- ver guardar_presupuesto() para
    por qué no se bloquea que sea distinto de 100 (se avisa, no se
    impide)."""
    r = conn.execute("SELECT * FROM presupuesto WHERE usuario_id = ?", (usuario_id,)).fetchone()
    if r:
        d = dict(r)
        d["configurado"] = True
    else:
        d = {
            "usuario_id": usuario_id,
            "pct_necesidades": PRESUPUESTO_PCT_DEFAULT["necesidades"],
            "pct_gustos": PRESUPUESTO_PCT_DEFAULT["gustos"],
            "pct_ahorro_deudas": PRESUPUESTO_PCT_DEFAULT["ahorro_deudas"],
            "actualizado_en": None,
            "configurado": False,
        }
    d["suma_pct"] = round(d["pct_necesidades"] + d["pct_gustos"] + d["pct_ahorro_deudas"], 2)
    return d


def guardar_presupuesto(conn: sqlite3.Connection, usuario_id: int, pct_necesidades, pct_gustos, pct_ahorro_deudas) -> dict:
    """Crea o actualiza (una fila por usuario_id, mismo patrón UPSERT que
    guardar_correo_config()) los 3 porcentajes de usuario_id. Cada uno
    tiene que ser un número >= 0 (un porcentaje negativo no tiene sentido
    financiero) -- eso SÍ se rechaza con ValueError. Que los 3 sumen
    exactamente 100 NO se exige acá: el documento de requisitos pide
    "avisar", no bloquear ("Algo a cuidar entre todos") -- el aviso
    (comparar el "suma_pct" del resultado contra 100) es responsabilidad
    de quien llama (la ruta / eventualmente el frontend), no de esta
    función. Devuelve el presupuesto ya guardado (mismo shape que
    obtener_presupuesto())."""
    valores = {"necesidades": pct_necesidades, "gustos": pct_gustos, "ahorro_deudas": pct_ahorro_deudas}
    for balde, v in valores.items():
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError(f"Falta el porcentaje de {balde}.")
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"El porcentaje de {balde} no es un número válido.")
        if v < 0:
            raise ValueError(f"El porcentaje de {balde} no puede ser negativo.")
        valores[balde] = v

    conn.execute(
        """
        INSERT INTO presupuesto (usuario_id, pct_necesidades, pct_gustos, pct_ahorro_deudas, actualizado_en)
        VALUES (?, ?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(usuario_id) DO UPDATE SET
            pct_necesidades = excluded.pct_necesidades,
            pct_gustos = excluded.pct_gustos,
            pct_ahorro_deudas = excluded.pct_ahorro_deudas,
            actualizado_en = excluded.actualizado_en
        """,
        (usuario_id, valores["necesidades"], valores["gustos"], valores["ahorro_deudas"]),
    )
    conn.commit()
    return obtener_presupuesto(conn, usuario_id)


def obtener_mapeo_categorias(conn: sqlite3.Connection, usuario_id: int) -> dict[str, str]:
    """{categoria: balde} de TODAS las categorías que usuario_id ya tiene
    en sus propios movimientos, más cualquiera que ya tuviera una
    asignación explícita guardada de antes (por si un movimiento se borró
    después de asignar su categoría a un balde -- la asignación no se
    pierde con él). Autopobla en la BD, de forma perezosa e idempotente
    (INSERT OR IGNORE: nunca pisa una asignación que el usuario ya haya
    elegido a mano), la fila que falte con el default razonable de
    CATEGORIA_BALDE_DEFAULT (o CATEGORIA_BALDE_FALLBACK si es una
    categoría 100% personalizada) -- así "cada categoría existente ya
    viene asignada a un balde por defecto" se cumple sin que el usuario
    tenga que configurar nada, y sin duplicar el default en dos lugares
    (acá y en el schema)."""
    usadas = obtener_categorias(conn, usuario_id)
    ya_asignadas = {
        r["categoria"] for r in conn.execute(
            "SELECT categoria FROM presupuesto_categorias WHERE usuario_id = ?", (usuario_id,)
        )
    }
    faltantes = [c for c in usadas if c not in ya_asignadas]
    if faltantes:
        conn.executemany(
            "INSERT OR IGNORE INTO presupuesto_categorias (usuario_id, categoria, balde) VALUES (?, ?, ?)",
            [(usuario_id, c, CATEGORIA_BALDE_DEFAULT.get(c, CATEGORIA_BALDE_FALLBACK)) for c in faltantes],
        )
        conn.commit()
    return {
        r["categoria"]: r["balde"]
        for r in conn.execute(
            "SELECT categoria, balde FROM presupuesto_categorias WHERE usuario_id = ? ORDER BY categoria",
            (usuario_id,),
        )
    }


def asignar_categoria_balde(conn: sqlite3.Connection, usuario_id: int, categoria: str, balde: str) -> None:
    """Reasigna (o asigna por primera vez) UNA categoría de usuario_id a
    un balde -- UPSERT, mismo patrón que guardar_correo_config(). `balde`
    tiene que ser uno de los 3 ids válidos (IDS_BALDES); cualquier otro
    valor se rechaza con ValueError -- nunca se guarda un balde
    inventado que después el frontend no sepa cómo mostrar."""
    categoria = (categoria or "").strip()
    if not categoria:
        raise ValueError("Falta la categoría.")
    if balde not in IDS_BALDES:
        ids_validos = ", ".join(b["id"] for b in BALDES_PRESUPUESTO)
        raise ValueError(f"Balde inválido -- tiene que ser uno de: {ids_validos}.")
    conn.execute(
        """
        INSERT INTO presupuesto_categorias (usuario_id, categoria, balde, actualizado_en)
        VALUES (?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(usuario_id, categoria) DO UPDATE SET
            balde = excluded.balde,
            actualizado_en = excluded.actualizado_en
        """,
        (usuario_id, categoria, balde),
    )
    conn.commit()


# ----------------------------- Metas de ahorro (2026-09-08) -----------------------------
# Mismo patrón que tarjetas_credito: crear_meta_ahorro/obtener_metas_ahorro/
# obtener_meta_ahorro/actualizar_meta_ahorro/archivar_meta_ahorro/
# borrar_meta_ahorro. El "avance" (ahorrado) nunca se guarda como un
# número aparte -- se calcula siempre sumando movimientos.monto de las
# filas que traen meta_ahorro_id=esta meta (ver _migrar_columna_meta_
# ahorro_id()): el aporte a una meta ES un movimiento más, no un sistema
# paralelo. Filtrado por moneda='COP' -- mismo criterio que
# obtener_tarjetas_con_deuda()/v_deuda_ledger (montos en otras monedas no
# se mezclan en el mismo acumulado).

def crear_meta_ahorro(conn: sqlite3.Connection, usuario_id: int, nombre: str, monto_objetivo: float,
                       fecha_objetivo: str | None = None) -> int:
    """monto_objetivo es obligatorio y > 0 (validado acá, no solo en la
    UI -- mismo criterio que crear_tarjeta() con cupo_total).
    fecha_objetivo es opcional; si viene, tiene que ser una fecha ISO
    válida (AAAA-MM-DD)."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("Falta el nombre de la meta.")
    if monto_objetivo is None or monto_objetivo <= 0:
        raise ValueError("El monto objetivo tiene que ser mayor a 0.")
    fecha_objetivo = (fecha_objetivo or "").strip() or None
    if fecha_objetivo:
        try:
            datetime.date.fromisoformat(fecha_objetivo)
        except ValueError:
            raise ValueError("La fecha objetivo no es una fecha válida (formato AAAA-MM-DD).")
    cur = conn.execute(
        "INSERT INTO metas_ahorro (usuario_id, nombre, monto_objetivo, fecha_objetivo) VALUES (?, ?, ?, ?)",
        (usuario_id, nombre, monto_objetivo, fecha_objetivo),
    )
    conn.commit()
    return cur.lastrowid


def _ahorrado_por_meta(conn: sqlite3.Connection, usuario_id: int) -> dict[int, float]:
    """{meta_ahorro_id: ahorrado} de TODAS las metas de usuario_id de una
    sola pasada -- lo usa obtener_metas_ahorro() para no hacer una
    consulta de agregación por meta (mismo patrón que
    obtener_tarjetas_con_deuda() con deuda_por_tarjeta)."""
    filas = conn.execute(
        """SELECT meta_ahorro_id, SUM(monto) AS ahorrado
           FROM movimientos
           WHERE usuario_id = ? AND meta_ahorro_id IS NOT NULL AND moneda = 'COP'
           GROUP BY meta_ahorro_id""",
        (usuario_id,),
    ).fetchall()
    return {f["meta_ahorro_id"]: (f["ahorrado"] or 0.0) for f in filas}


def _con_avance(meta: dict, ahorrado: float) -> dict:
    """Agrega ahorrado/restante/porcentaje a una fila de metas_ahorro ya
    convertida a dict. "restante" se trunca a 0 (a diferencia de
    cupo_disponible en obtener_tarjetas_con_deuda(), que a propósito NO
    se trunca): ahí un número negativo es una señal de alerta real
    (te pasaste del cupo); acá, superar la meta es bueno, no una deuda
    -- no tiene sentido mostrar "restante: -50.000". "porcentaje" SÍ
    puede superar 100 (no se trunca) para que se pueda mostrar "¡meta
    superada!" con el número real."""
    meta = dict(meta)
    meta["ahorrado"] = ahorrado
    meta["restante"] = max(meta["monto_objetivo"] - ahorrado, 0.0)
    meta["porcentaje"] = round((ahorrado / meta["monto_objetivo"] * 100), 2) if meta["monto_objetivo"] else 0.0
    return meta


def obtener_metas_ahorro(conn: sqlite3.Connection, usuario_id: int, solo_activas: bool = False) -> list[dict]:
    """Todas las metas (o solo las activas) de usuario_id, con su avance
    ya calculado -- nunca de otro usuario, `usuario_id` siempre explícito
    en el WHERE."""
    sql = "SELECT * FROM metas_ahorro WHERE usuario_id = ?"
    params = [usuario_id]
    if solo_activas:
        sql += " AND activa = 1"
    sql += " ORDER BY activa DESC, id"

    ahorrado_por_meta = _ahorrado_por_meta(conn, usuario_id)
    out = []
    for r in conn.execute(sql, params).fetchall():
        d = dict(r)
        d["activa"] = bool(d["activa"])
        out.append(_con_avance(d, ahorrado_por_meta.get(d["id"], 0.0)))
    return out


def obtener_meta_ahorro(conn: sqlite3.Connection, usuario_id: int, meta_id: int) -> dict | None:
    """None si no existe O si existe pero es de otro usuario -- mismo
    criterio de aislamiento que obtener_tarjeta()."""
    r = conn.execute(
        "SELECT * FROM metas_ahorro WHERE id = ? AND usuario_id = ?", (meta_id, usuario_id)
    ).fetchone()
    if not r:
        return None
    d = dict(r)
    d["activa"] = bool(d["activa"])
    ahorrado = conn.execute(
        "SELECT COALESCE(SUM(monto), 0) AS ahorrado FROM movimientos "
        "WHERE usuario_id = ? AND meta_ahorro_id = ? AND moneda = 'COP'",
        (usuario_id, meta_id),
    ).fetchone()["ahorrado"]
    return _con_avance(d, ahorrado)


def actualizar_meta_ahorro(conn: sqlite3.Connection, usuario_id: int, meta_id: int, nombre: str | None = None,
                            monto_objetivo: float | None = None, fecha_objetivo: str | None = None) -> bool:
    """Actualiza solo los campos presentes (None = no tocar), mismo
    criterio que actualizar_tarjeta(). Un string vacío en fecha_objetivo
    SÍ es una instrucción explícita de "quitar la fecha" (queda opcional
    de nuevo) -- para no tocarla, simplemente no se manda esa clave.
    Devuelve False si la meta no existe o no es de usuario_id."""
    if obtener_meta_ahorro(conn, usuario_id, meta_id) is None:
        return False

    campos, valores = [], []
    if nombre is not None:
        nombre = nombre.strip()
        if not nombre:
            raise ValueError("El nombre no puede quedar vacío.")
        campos.append("nombre = ?"); valores.append(nombre)
    if monto_objetivo is not None:
        if monto_objetivo <= 0:
            raise ValueError("El monto objetivo tiene que ser mayor a 0.")
        campos.append("monto_objetivo = ?"); valores.append(monto_objetivo)
    if fecha_objetivo is not None:
        fecha_objetivo = fecha_objetivo.strip() or None
        if fecha_objetivo:
            try:
                datetime.date.fromisoformat(fecha_objetivo)
            except ValueError:
                raise ValueError("La fecha objetivo no es una fecha válida (formato AAAA-MM-DD).")
        campos.append("fecha_objetivo = ?"); valores.append(fecha_objetivo)

    if campos:
        campos.append("actualizado_en = datetime('now', 'localtime')")
        valores.extend([meta_id, usuario_id])
        conn.execute(f"UPDATE metas_ahorro SET {', '.join(campos)} WHERE id = ? AND usuario_id = ?", valores)
        conn.commit()
    return True


def archivar_meta_ahorro(conn: sqlite3.Connection, usuario_id: int, meta_id: int) -> bool:
    """Soft delete: deja de listarse entre las 'activas' (selectores de
    "aportar a esta meta" en Registrar movimiento) pero conserva intacto
    el historial de aportes que ya tenía asociados. False si no existe o
    no es de usuario_id."""
    cur = conn.execute(
        "UPDATE metas_ahorro SET activa = 0, actualizado_en = datetime('now', 'localtime') "
        "WHERE id = ? AND usuario_id = ?",
        (meta_id, usuario_id),
    )
    conn.commit()
    return cur.rowcount > 0


def borrar_meta_ahorro(conn: sqlite3.Connection, usuario_id: int, meta_id: int) -> tuple[bool, str | None]:
    """Borrado DEFINITIVO -- solo permitido si la meta nunca tuvo ningún
    aporte (movimiento con meta_ahorro_id=esta meta) asociado. Mismo
    mecanismo que borrar_tarjeta(): meta_ahorro_id es una FK "normal", así
    que con `PRAGMA foreign_keys = ON` SQLite mismo rechaza el DELETE con
    IntegrityError si hay aportes que la referencian -- alcanza con
    capturarlo acá. Devuelve (ok, mensaje_de_error)."""
    if obtener_meta_ahorro(conn, usuario_id, meta_id) is None:
        return False, "Esa meta no existe."
    try:
        conn.execute("DELETE FROM metas_ahorro WHERE id = ? AND usuario_id = ?", (meta_id, usuario_id))
        conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "Esa meta tiene aportes (movimientos) asociados -- archivala en vez de borrarla."


# ----------------------------- Inserción con dedup (usada por cualquier fuente de ingesta) -----------------------------

def _palabras(*textos: str) -> set[str]:
    return set(re.findall(r"\w+", " ".join(t or "" for t in textos).lower()))


def _mejor_coincidencia(m: dict, candidatos: list[dict]) -> dict | None:
    """De entre los movimientos ya existentes que calzan en (moneda, monto,
    tipo), elige el más probable de ser LA MISMA transacción real que `m`:
    fecha exacta gana sobre ±1 día (el banco y el registro manual pueden
    quedar a caballo de la medianoche), y entre empates, el que más
    palabras comparte en descripción/entidad -- pero esto último es solo
    un DESEMPATE, nunca un requisito: un registro manual ("almuerzo") y
    uno de correo ("Transferiste $30.000 de tu cuenta...") legítimamente
    no comparten ninguna palabra siendo la misma transacción."""
    fecha_m = datetime.date.fromisoformat(m["fecha"])
    en_ventana = [
        c for c in candidatos
        if abs((datetime.date.fromisoformat(c["fecha"]) - fecha_m).days) <= 1
    ]
    if not en_ventana:
        return None
    palabras_m = _palabras(m.get("descripcion", ""), m.get("entidad", ""))

    def _orden(c: dict):
        fecha_exacta = 0 if c["fecha"] == m["fecha"] else 1
        solapadas = len(palabras_m & _palabras(c.get("descripcion", ""), c.get("entidad", "")))
        return (fecha_exacta, -solapadas, c["id"])

    return min(en_ventana, key=_orden)


def insertar_movimientos(conn: sqlite3.Connection, movimientos: list[dict], origen: str, usuario_id: int) -> dict:
    """Inserta los movimientos de `movimientos` que no correspondan a una
    transacción YA registrada para ese usuario -- cada usuario tiene sus
    propias finanzas separadas, así que lo de otro usuario nunca cuenta
    como duplicado. Cada movimiento debe traer al menos
    fecha/tipo/categoria/moneda/monto/descripcion/entidad; se enriquece
    acá (medio_pago/es_deuda) antes de insertar.

    CONCILIACIÓN (2026-09-06): el match ya no es "existe alguna fila con
    esa fecha+monto" (eso confundía dos transacciones reales distintas
    que coincidieran en fecha+monto -- ej. dos transferencias de $30.000
    el mismo día -- tratando la segunda como si fuera repetida). Ahora
    cada fila existente solo puede "absorber" UN incoming (multiset, no
    set): se consume al usarse, así que una segunda coincidencia real
    ese mismo día sí se inserta como nueva. Además, cuando lo que
    absorbe la coincidencia es un registro CARGADO A MANO (origen
    'app_manual') y lo que llega es de una fuente automática (correo,
    PDF, Excel), se guarda la descripción "oficial" del banco en
    referencia_bancaria SIN tocar la descripción/categoría que el
    usuario ya había escrito (ej. "almuerzo" se queda como está).

    El "consumo" tiene que sobrevivir entre llamadas distintas (cada
    corrida de leer_correo.py es una llamada separada) -- por eso una
    fila manual que YA absorbió una coincidencia (referencia_bancaria ya
    no es NULL) queda EXCLUIDA de volver a ser candidata en el futuro:
    si no, una segunda transacción real de $30.000 el mismo día,
    detectada en una corrida posterior, volvería a "encontrar" la misma
    fila de "almuerzo" y se perdería en vez de insertarse. Una fila
    automática ya existente sí puede seguir absorbiendo coincidencias
    indefinidamente entre corridas -- eso es re-detectar el mismo correo
    dos veces (ventanas que se solapan), que sí debe seguir marcándose
    como duplicado siempre.

    TARJETA_ID (2026-09-07): cada movimiento nuevo puede traer ya un
    'tarjeta_id' explícito (registro manual con tarjeta elegida en el
    formulario -- ver routes/dashboard.py::api_registrar_movimiento, que
    ya validó que pertenece a una tarjeta ACTIVA de ese usuario_id antes
    de llegar acá) -- ese valor nunca se pisa. Si no trae uno, y sí trae
    'ultimos4' (propagado por los parsers de leer_correo.py/
    tools/reconciliar_extractos.py), se intenta resolver automáticamente
    contra las tarjetas de usuario_id (ver _resolver_tarjeta_por_ultimos4);
    sin ultimos4, o con 0/2+ tarjetas activas coincidentes, queda NULL --
    nunca se adivina. Los movimientos que resultan duplicados (match
    contra uno ya existente) NUNCA reasignan tarjeta_id a la fila vieja
    -- ver la nota de "Migración de datos existentes" del documento de
    requisitos: nada se reasigna retroactivamente, ni siquiera implícitamente."""
    cur = conn.cursor()
    existentes = [
        dict(r) for r in cur.execute(
            "SELECT id, fecha, moneda, monto, tipo, descripcion, entidad, origen, referencia_bancaria "
            "FROM movimientos WHERE usuario_id = ? "
            "AND NOT (origen = 'app_manual' AND referencia_bancaria IS NOT NULL)",
            (usuario_id,),
        )
    ]
    if origen == "app_manual":
        # Dos movimientos MANUALES con la misma fecha±1/monto/tipo no son
        # necesariamente la misma transacción real -- a diferencia del caso
        # que este motor fue diseñado para resolver (una fuente automática
        # confirmando una fila manual ya cargada), acá no hay ninguna fuente
        # "más confiable" avisando que de verdad es la misma. Tratarlas como
        # duplicado descartaba en silencio una segunda compra real del mismo
        # monto el mismo día -- bug real reportado 2026-09-10 (usuario
        # registró 16.500000 y después 16.5: la segunda "desaparecía", el
        # saldo de la tarjeta quedaba corto). El formulario ya protege
        # contra doble-click (deshabilita el botón al enviar, ver
        # templates/registrar.html), así que no hace falta este mecanismo
        # para ese caso -- una fila manual existente solo puede seguir
        # absorbiendo coincidencias que lleguen de una fuente automática
        # (correo/PDF/Excel).
        existentes = [e for e in existentes if e["origen"] != "app_manual"]
    disponibles: dict[tuple, list[dict]] = defaultdict(list)
    for e in existentes:
        disponibles[(e["moneda"], round(e["monto"]), e["tipo"])].append(e)

    # Se distinguen dos tipos de duplicado -- son casos distintos y el
    # mensaje al usuario debe aclarar cuál es cuál:
    #   - duplicados_bd: esa transacción ya estaba guardada de antes.
    #   - duplicados_lote: dos filas DEL MISMO archivo/lote son iguales
    #     entre sí (no existían antes, pero no tiene sentido guardar la
    #     misma dos veces en la misma carga).
    vistos_en_lote = set()
    nuevos, duplicados_bd, duplicados_lote = [], 0, 0
    for m_crudo in movimientos:
        # Enriquecer ANTES de armar la clave de match: enriquecer_movimiento
        # puede reclasificar 'tipo' (ej. avance de tarjeta: 'gasto' ->
        # 'ingreso'), y las filas ya existentes en `disponibles` tienen el
        # tipo YA reclasificado -- si acá se comparara con el tipo crudo,
        # un avance nunca encontraría su propia fila ya guardada y se
        # insertaría de nuevo en cada corrida.
        m = enriquecer_movimiento(m_crudo)

        clave_lote = (m["fecha"], m["moneda"], round(m["monto"]), m["tipo"])
        if clave_lote in vistos_en_lote:
            duplicados_lote += 1
            continue

        candidatos = disponibles.get((m["moneda"], round(m["monto"]), m["tipo"]), [])
        match = _mejor_coincidencia(m, candidatos) if candidatos else None
        if match:
            candidatos.remove(match)  # consumida -- una segunda coincidencia real no la vuelve a encontrar
            duplicados_bd += 1
            if match["origen"] == "app_manual" and origen != "app_manual" and not match.get("referencia_bancaria"):
                referencia = (m.get("descripcion") or "").strip()
                if referencia:
                    cur.execute("UPDATE movimientos SET referencia_bancaria = ? WHERE id = ?", (referencia, match["id"]))
            continue

        vistos_en_lote.add(clave_lote)
        nuevos.append(m)

    for e in nuevos:
        e["origen"] = origen
        e["usuario_id"] = usuario_id
        if not e.get("tarjeta_id"):
            # 'ultimos4' explícito (correo/PDF/Excel, ver el docstring de
            # arriba) tiene prioridad; si no vino, se intenta extraer del
            # texto de la descripción (cubre el registro manual, que no
            # tiene un campo dedicado -- ver _extraer_ultimos4_de_texto).
            ultimos4 = e.get("ultimos4") or _extraer_ultimos4_de_texto(e.get("descripcion"))
            e["tarjeta_id"] = _resolver_tarjeta_por_ultimos4(conn, usuario_id, ultimos4)
        # meta_ahorro_id: a diferencia de tarjeta_id, no hay forma de
        # resolverlo automáticamente por texto (no hay un patrón bancario
        # equivalente a "últimos4") -- solo llega explícito cuando el
        # movimiento se registró a mano eligiendo una meta (ver
        # routes/dashboard.py::api_registrar_movimiento). setdefault en
        # vez de sobreescribir: si ya viene en el dict (ese caso), se
        # respeta tal cual.
        e.setdefault("meta_ahorro_id", None)
    cur.executemany(
        """INSERT INTO movimientos (fecha, tipo, categoria, moneda, monto, descripcion, entidad, medio_pago, es_deuda, origen, usuario_id, tarjeta_id, meta_ahorro_id)
           VALUES (:fecha, :tipo, :categoria, :moneda, :monto, :descripcion, :entidad, :medio_pago, :es_deuda, :origen, :usuario_id, :tarjeta_id, :meta_ahorro_id)""",
        nuevos,
    )
    conn.commit()
    return {
        "nuevos": len(nuevos),
        "duplicados": duplicados_bd + duplicados_lote,
        "duplicados_bd": duplicados_bd,
        "duplicados_lote": duplicados_lote,
    }


# ----------------------------- Editar/borrar un movimiento individual -----------------------------
# 2026-09-07, ver requisitos/2026-09-07_editar-borrar-movimiento.md.

CAMPOS_IDENTIDAD_MOVIMIENTO = ("fecha", "monto", "tipo", "moneda")


def obtener_movimiento(conn: sqlite3.Connection, usuario_id: int, movimiento_id: int) -> dict | None:
    """None si no existe O si existe pero es de otro usuario -- mismo
    criterio de aislamiento que obtener_tarjeta(): el AND va en el WHERE
    de la consulta, nunca se filtra después en Python (nunca se le
    devuelve al llamador una fila ajena para que decida qué hacer)."""
    r = conn.execute(
        "SELECT * FROM movimientos WHERE id = ? AND usuario_id = ?", (movimiento_id, usuario_id)
    ).fetchone()
    if not r:
        return None
    d = dict(r)
    d["es_deuda"] = bool(d["es_deuda"])
    return d


def editar_movimiento(conn: sqlite3.Connection, usuario_id: int, movimiento_id: int, cambios: dict) -> dict:
    """Edición PARCIAL de un movimiento propio de usuario_id -- mismo
    criterio que actualizar_tarjeta()/actualizar_usuario(): solo se
    tocan los campos presentes en `cambios`.

    Devuelve un dict (no el tuple[bool, str | None] del primer borrador
    del requerimiento): además de "ok"/"error" hace falta poder avisar
    la reclasificación de medio_pago/es_deuda (viejo vs. nuevo) para que
    la ruta se la pase al frontend -- forzar esa info en un string de
    error hubiera sido más fràgil que un dict explícito. Claves siempre
    presentes: "ok" (bool), "error" (str | None), "reclasificado"
    (bool). Si "reclasificado" es True, además: "medio_pago_anterior",
    "medio_pago_nuevo", "es_deuda_anterior", "es_deuda_nuevo".

    Reglas (ver documento de requisitos para el detalle completo):
      - 404 se modela acá como ok=False -- es la ruta quien decide el
        status code exacto, esta función no conoce HTTP.
      - Campos "de identidad" (fecha/monto/tipo/moneda) en un movimiento
        YA CONCILIADO (referencia_bancaria IS NOT NULL) o de ORIGEN
        AUTOMÁTICO (origen != 'app_manual') exigen
        cambios["confirmar_riesgo"] is True; si falta, se rechaza TODO
        el cambio (nunca una edición parcial a medias por falta de
        confirmación -- ni siquiera los campos descriptivos que vinieran
        en el mismo `cambios` se aplican).

        El gate se dispara por VALOR final distinto al que el movimiento
        ya tenía, no por la mera presencia de la clave en `cambios`
        (deliberado, a diferencia de actualizar_tarjeta()): el modal de
        edición del frontend precarga TODOS los campos del movimiento
        (ver requisitos, "ya están en el cliente") y lo más probable es
        que reenvíe el formulario completo aunque el usuario solo haya
        tocado un campo descriptivo -- si el gate mirara solo "¿vino la
        clave fecha/monto/tipo/moneda en el body?" en vez de "¿cambió de
        verdad?", CUALQUIER edición de descripción en un movimiento
        conciliado exigiría confirmar_riesgo, violando directamente el
        criterio de aceptación "los campos descriptivos nunca requieren
        esta advertencia".
      - Confirmar un cambio de identidad sobre un movimiento con
        referencia_bancaria no nula la limpia (NULL) en la misma
        transacción -- ya no se puede seguir garantizando que ese dato
        es lo que el banco confirmó. Si el movimiento es de origen
        automático pero nunca tuvo referencia_bancaria, no hay nada que
        limpiar (el movimiento en sí ES el registro de la fuente
        automática).
      - tarjeta_id SOLO se toca si viene explícito en `cambios` -- nunca
        se re-infiere por texto/descripción (a diferencia de la
        resolución automática por últimos4 al insertar, ver
        _resolver_tarjeta_por_ultimos4()). Debe pertenecer a una tarjeta
        ACTIVA de usuario_id, salvo que sea exactamente la misma que ya
        tenía (aunque esa tarjeta esté archivada -- no se fuerza a
        des-asignar solo por no tocarla). Un valor "vacío"
        (None/0/"") en cambios["tarjeta_id"] es una des-asignación
        explícita, siempre permitida.
      - Se recalcula medio_pago/es_deuda con enriquecer_movimiento()
        sobre el resultado final (lo que no cambió + lo editado) -- es
        la MISMA función que ya corre al insertar, así que un campo
        editado (típicamente descripción) puede reclasificar el
        movimiento exactamente igual que si se hubiera cargado así desde
        el principio."""
    existente = obtener_movimiento(conn, usuario_id, movimiento_id)
    if existente is None:
        return {"ok": False, "error": "Ese movimiento no existe.", "reclasificado": False, "requiere_confirmacion": False}

    fecha = cambios.get("fecha", existente["fecha"])
    tipo = cambios.get("tipo", existente["tipo"])
    monto = cambios.get("monto", existente["monto"])
    moneda = cambios.get("moneda", existente["moneda"])
    descripcion = cambios.get("descripcion", existente["descripcion"])
    categoria = cambios.get("categoria", existente["categoria"])
    entidad = cambios.get("entidad", existente["entidad"])

    if not str(fecha or "").strip():
        return {"ok": False, "error": "Falta fecha.", "reclasificado": False, "requiere_confirmacion": False}
    if not str(descripcion or "").strip():
        return {"ok": False, "error": "Falta descripción.", "reclasificado": False, "requiere_confirmacion": False}
    try:
        monto = float(monto)
    except (TypeError, ValueError):
        return {"ok": False, "error": "El monto no es un número válido.", "reclasificado": False, "requiere_confirmacion": False}
    if monto <= 0:
        return {"ok": False, "error": "El monto tiene que ser mayor a 0.", "reclasificado": False, "requiere_confirmacion": False}

    fecha = str(fecha).strip()
    tipo = str(tipo).strip()
    moneda = str(moneda).strip()
    descripcion = str(descripcion).strip()

    identidad_cambio = (
        fecha != existente["fecha"]
        or tipo != existente["tipo"]
        or round(monto) != round(existente["monto"])
        or moneda != existente["moneda"]
    )
    ya_conciliado = existente["referencia_bancaria"] is not None
    es_automatico = existente["origen"] != "app_manual"
    requiere_confirmacion = identidad_cambio and (ya_conciliado or es_automatico)
    if requiere_confirmacion and cambios.get("confirmar_riesgo") is not True:
        return {
            "ok": False,
            "error": "Editar fecha/monto/tipo/moneda de este movimiento requiere confirmar_riesgo=true.",
            "reclasificado": False,
            "requiere_confirmacion": True,
        }

    tarjeta_id = existente["tarjeta_id"]
    if "tarjeta_id" in cambios:
        tid_raw = cambios["tarjeta_id"]
        if not tid_raw:
            tarjeta_id = None
        else:
            try:
                nuevo_tid = int(tid_raw)
            except (TypeError, ValueError):
                return {"ok": False, "error": "tarjeta_id inválido.", "reclasificado": False, "requiere_confirmacion": False}
            if nuevo_tid == existente["tarjeta_id"]:
                tarjeta_id = nuevo_tid  # sin cambio real, aunque esa tarjeta esté archivada
            else:
                tarjeta = obtener_tarjeta(conn, usuario_id, nuevo_tid)
                if not tarjeta or not tarjeta["activa"]:
                    return {"ok": False, "error": "Esa tarjeta no existe o no está activa.", "reclasificado": False, "requiere_confirmacion": False}
                tarjeta_id = nuevo_tid

    fila_final = enriquecer_movimiento({
        "fecha": fecha, "tipo": tipo, "categoria": categoria, "moneda": moneda,
        "monto": monto, "descripcion": descripcion, "entidad": entidad,
    })

    medio_pago_anterior = existente["medio_pago"]
    es_deuda_anterior = existente["es_deuda"]
    reclasificado = (
        fila_final["medio_pago"] != medio_pago_anterior
        or fila_final["es_deuda"] != es_deuda_anterior
    )

    limpiar_referencia = requiere_confirmacion and ya_conciliado

    campos_sql = [
        "fecha = ?", "tipo = ?", "categoria = ?", "moneda = ?", "monto = ?",
        "descripcion = ?", "entidad = ?", "medio_pago = ?", "es_deuda = ?", "tarjeta_id = ?",
    ]
    valores = [
        fila_final["fecha"], fila_final["tipo"], fila_final["categoria"], fila_final["moneda"],
        fila_final["monto"], fila_final["descripcion"], fila_final["entidad"],
        fila_final["medio_pago"], int(fila_final["es_deuda"]), tarjeta_id,
    ]
    if limpiar_referencia:
        campos_sql.append("referencia_bancaria = NULL")
    valores.extend([movimiento_id, usuario_id])

    conn.execute(f"UPDATE movimientos SET {', '.join(campos_sql)} WHERE id = ? AND usuario_id = ?", valores)
    conn.commit()

    resultado = {"ok": True, "error": None, "reclasificado": reclasificado, "requiere_confirmacion": requiere_confirmacion}
    if reclasificado:
        resultado["medio_pago_anterior"] = medio_pago_anterior
        resultado["medio_pago_nuevo"] = fila_final["medio_pago"]
        resultado["es_deuda_anterior"] = es_deuda_anterior
        resultado["es_deuda_nuevo"] = fila_final["es_deuda"]
    return resultado


def advertencia_riesgo_movimiento(movimiento: dict) -> str | None:
    """Texto de advertencia (o None si no aplica) sobre el riesgo real de
    editar/borrar `movimiento` -- centralizado acá (no en el frontend)
    para que la ruta se lo devuelva a quien consuma la API en vez de que
    cada cliente reinvente su propia versión del copy. Ver
    requisitos/2026-09-07_editar-borrar-movimiento.md, "Casos borde" y
    "Riesgo financiero/UX a vigilar" -- el copy nombra la consecuencia en
    plata real, no un "¿Estás seguro?" genérico.

    - None: movimiento manual (origen='app_manual') sin conciliar
      (referencia_bancaria IS NULL) -- no hay ningún riesgo real que
      avisar todavía.
    - Texto ESPECÍFICO Y MÁS FUERTE para origen='gmail_bot_excel':
      nombra el mecanismo real (actualizar_dashboard.py, corrida en cada
      deploy, borra y reinserta TODOS los movimientos de ese origen
      leyendo el Excel de nuevo) -- se puede perder solo, sin ninguna
      acción adicional del usuario, no solo "podría duplicarse".
    - Texto GENÉRICO para cualquier otro caso conciliado o de origen
      automático: la próxima vez que se detecte la misma transacción
      (correo/PDF/Excel), puede volver a insertarse -- mismo gasto
      contado dos veces en los totales."""
    origen = movimiento.get("origen")
    conciliado = movimiento.get("referencia_bancaria") is not None
    if origen == "gmail_bot_excel":
        return (
            "Este movimiento viene del Excel sincronizado por el bot de Gmail. "
            "En cada deploy, actualizar_dashboard.py borra y vuelve a cargar TODOS "
            "los movimientos de este origen leyendo el Excel de nuevo -- si el dato "
            "sigue igual ahí, tu edición o borrado se puede perder solo en la próxima "
            "sincronización, sin que vuelvas a tocar nada."
        )
    if conciliado or origen != "app_manual":
        return (
            "Este movimiento ya fue conciliado con un correo/PDF/Excel del banco, o "
            "viene directo de una fuente automática. Si esa misma transacción se "
            "vuelve a detectar más adelante (una corrida repetida de la lectura de "
            "correo, o resubir el mismo extracto), puede insertarse de nuevo y vas a "
            "ver el mismo gasto contado dos veces en tus totales."
        )
    return None


def borrar_movimiento(conn: sqlite3.Connection, usuario_id: int, movimiento_id: int) -> bool:
    """Hard delete DEFINITIVO -- no hay papelera ni deshacer en esta
    versión. Devuelve True si borró una fila, False si no existía o era
    de otro usuario (aislamiento en el propio WHERE, nunca filtrado
    después en Python). No hay ninguna FK entrante hacia movimientos.id
    (a diferencia de tarjetas_credito.id, ver borrar_tarjeta()), así que
    es un DELETE simple sin IntegrityError que capturar."""
    cur = conn.execute("DELETE FROM movimientos WHERE id = ? AND usuario_id = ?", (movimiento_id, usuario_id))
    conn.commit()
    return cur.rowcount > 0
