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

import sqlite3
import datetime
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

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
"""

# username no tiene restricción UNIQUE a nivel de base de datos, para
# soportar configuraciones de cuentas fuera del caso estándar.

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
    return conn


def _migrar_columna_usuario_id(conn: sqlite3.Connection) -> None:
    """SQLite no tiene 'ADD COLUMN IF NOT EXISTS' -- se revisa a mano.
    Cada movimiento pasa a pertenecer a un usuario (multiusuario, 2026-09-05).
    Nula por defecto en filas viejas; se asigna al admin la primera vez que
    corre esta migración (ver asignar_movimientos_sin_dueno_a_admin)."""
    columnas = [r["name"] for r in conn.execute("PRAGMA table_info(movimientos)")]
    if "usuario_id" not in columnas:
        conn.execute("ALTER TABLE movimientos ADD COLUMN usuario_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movimientos_usuario ON movimientos(usuario_id)")
        conn.commit()


def crear_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA_SQL)
    _migrar_columna_usuario_id(conn)
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
    sql = """SELECT fecha, tipo, categoria, moneda, monto, descripcion, entidad, medio_pago, es_deuda
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


# ----------------------------- Inserción con dedup (usada por cualquier fuente de ingesta) -----------------------------

def insertar_movimientos(conn: sqlite3.Connection, movimientos: list[dict], origen: str, usuario_id: int) -> dict:
    """Inserta solo los movimientos cuyo (fecha, moneda, monto redondeado) no
    exista ya entre los movimientos DE ESE USUARIO -- cada usuario tiene sus
    propias finanzas separadas, así que el mismo día+monto en la cuenta de
    otro usuario no cuenta como duplicado. Cada movimiento debe traer al
    menos fecha/tipo/categoria/moneda/monto/descripcion/entidad; se
    enriquece acá (medio_pago/es_deuda) antes de insertar."""
    cur = conn.cursor()
    existentes = set()
    for row in cur.execute("SELECT fecha, moneda, ROUND(monto) AS m FROM movimientos WHERE usuario_id = ?", (usuario_id,)):
        existentes.add((row["fecha"], row["moneda"], row["m"]))

    nuevos, duplicados = [], 0
    for m in movimientos:
        clave = (m["fecha"], m["moneda"], round(m["monto"]))
        if clave in existentes:
            duplicados += 1
            continue
        existentes.add(clave)  # evita duplicar contra sí mismo si el lote trae el mismo movimiento dos veces
        nuevos.append(m)

    enriquecidos = [enriquecer_movimiento(m) for m in nuevos]
    for e in enriquecidos:
        e["origen"] = origen
        e["usuario_id"] = usuario_id
    cur.executemany(
        """INSERT INTO movimientos (fecha, tipo, categoria, moneda, monto, descripcion, entidad, medio_pago, es_deuda, origen, usuario_id)
           VALUES (:fecha, :tipo, :categoria, :moneda, :monto, :descripcion, :entidad, :medio_pago, :es_deuda, :origen, :usuario_id)""",
        enriquecidos,
    )
    conn.commit()
    return {"nuevos": len(nuevos), "duplicados": duplicados}
