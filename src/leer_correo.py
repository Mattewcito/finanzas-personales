"""
leer_correo.py
================
FASE 1 del rediseño: automatización local de lectura de correo, sin
depender de ninguna tarea externa ni de Claude en tiempo de ejecución.

Se conecta a Gmail por IMAP (protocolo oficial, no navegador automatizado
— ver nota de diseño en el README) usando una contraseña de aplicación,
busca las notificaciones transaccionales de Bancolombia, las parsea con
expresiones regulares (nada de IA en este paso — determinístico y
gratis) y las inserta en data/finanzas.db con origen='correo_imap'.

Requiere data/credenciales_correo.json (ver credenciales_correo.example.json
para el formato) — ese archivo NUNCA se sube a git (vive en data/, que
está en .gitignore completo).

Uso:
    py leer_correo.py             -> solo reporta lo que encontró (no escribe)
    py leer_correo.py --aplicar   -> inserta los movimientos nuevos en la BD
    py leer_correo.py --dias 30   -> busca en los últimos N días (default 7)

Alcance actual (v1): SOLO Bancolombia (notificaciones en tiempo real).
Nu no manda alertas por movimiento, solo extractos mensuales por correo
con datos adjuntos — eso se sigue cubriendo con reconciliar_extractos.py
hasta que se sume un parser de esos adjuntos (fase futura).

⚠️ La categoría de cada compra se asigna con una lista de palabras clave
(sin IA) — es un mejor esfuerzo, no perfecta. Podés corregir categorías
después directamente en la base de datos; no afecta los totales de
ingreso/gasto/deuda, que dependen de tipo/medio_pago/monto, no de categoria.
"""

import re
import sys
import json
import imaplib
import email
import argparse
import datetime
from email.header import decode_header
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import db_finanzas as db

CONFIG_PATH = db.DATA_DIR / "credenciales_correo.json"
ESTADO_PATH = db.DATA_DIR / "leer_correo_estado.json"

REMITENTES_BANCOLOMBIA = (
    "alertasynotificaciones@an.notificacionesbancolombia.com",
    "alertasynotificaciones@bancolombia.com.co",
)

# Palabras clave en el nombre del comercio -> categoría. Mejor esfuerzo, sin IA.
# Se revisa en orden; la primera coincidencia gana. Todo lo que no matchea -> "otros".
CATEGORIAS_POR_PALABRA_CLAVE = [
    (("uber", "didi", "cabify", "beat "), "transporte"),
    (("rappi", "domicilios"), "restaurantes"),
    (("d1 ", "exito", "éxito", "carulla", "ara ", "jumbo", "olimpica", "olímpica", "merca"), "supermercado"),
    (("homecenter", "easy ", "falabella"), "hogar"),
    (("netflix", "spotify", "disney", "hbo", "amazon prime", "youtube premium",
      "anthropic", "claude", "openai", "chatgpt"), "suscripciones"),
    (("drogueria", "droguería", "farmacia", "eps ", "cruz verde"), "salud"),
    (("apple.com", "apple store"), "tecnologia"),
    (("temu", "shein", "mercadolibre", "mercado libre"), "compras"),
    (("cafe", "café", "pan ", "restaurante", "wok", "burger", "pizza", "sushi"), "restaurantes"),
]


def _categoria_por_comercio(comercio: str) -> str:
    c = comercio.lower()
    for palabras, categoria in CATEGORIAS_POR_PALABRA_CLAVE:
        if any(p in c for p in palabras):
            return categoria
    return "otros"


def _parsear_monto_latino(s: str) -> float:
    """'758.976,00' -> 758976.0 (formato colombiano: punto=miles, coma=decimal)."""
    return float(s.replace(".", "").replace(",", "."))


def _parsear_monto_plano(s: str) -> float:
    """'32500.00', '1750000' o '7,500.00' -> float. En esta familia de
    alertas el separador de miles (si aparece) siempre es coma y el
    decimal siempre es punto (nunca al revés) -- a diferencia de las
    alertas de "Compraste", que usan formato latino."""
    return float(s.replace(",", ""))


def _fecha_iso(dia: str, mes: str, anio: str) -> str:
    anio_i = int(anio)
    if anio_i < 100:
        anio_i += 2000
    return f"{anio_i:04d}-{int(mes):02d}-{int(dia):02d}"


# ----------------------------- Parsers por tipo de alerta -----------------------------
# Cada uno recibe el texto YA normalizado (espacios/saltos de línea colapsados a uno solo)
# y devuelve un dict de movimiento, o None si el patrón no aplica.

def _p_compra_tarjeta(t: str) -> dict | None:
    # "Compraste COP758.976,00 en TEMU COM con tu T.Cred *2011, el 03/09/2026 a las 11:26."
    m = re.search(
        r"Compraste\s+(COP|USD|\$)\s?([\d.,]+)\s+en\s+(.+?)\s+con\s+tu\s+(T\.Cred|T\.Deb)\s+\*(\d+),?\s+el\s+"
        r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s+a las\s+\d{2}:\d{2}\.",
        t,
    )
    if not m:
        return None
    moneda_prefijo, monto_str, comercio, medio, tarjeta, dia, mes, anio = m.groups()
    moneda = "USD" if moneda_prefijo == "USD" else "COP"
    monto = _parsear_monto_latino(monto_str)
    comercio = comercio.strip()
    return {
        "fecha": _fecha_iso(dia, mes, anio),
        "tipo": "gasto",
        "categoria": _categoria_por_comercio(comercio),
        "moneda": moneda,
        "monto": monto,
        "descripcion": f"Compra en {comercio} con {medio} *{tarjeta}",
        "entidad": "Bancolombia",
    }


def _p_compra_tarjeta_asociada(t: str) -> dict | None:
    # "Compraste COP14.284,44 en UBER BV USD-USD COLO, el 29/08/2026 a las 14:54.
    #  Esta compra esta asociada a T.Cred *4112."
    m = re.search(
        r"Compraste\s+(COP|USD|\$)\s?([\d.,]+)\s+en\s+(.+?),\s+el\s+"
        r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s+a las\s+\d{2}:\d{2}\.\s+"
        r"Esta compra esta asociada a\s+(T\.Cred|T\.Deb)\s+\*(\d+)",
        t,
    )
    if not m:
        return None
    moneda_prefijo, monto_str, comercio, dia, mes, anio, medio, tarjeta = m.groups()
    moneda = "USD" if moneda_prefijo == "USD" else "COP"
    monto = _parsear_monto_latino(monto_str)
    comercio = comercio.strip()
    return {
        "fecha": _fecha_iso(dia, mes, anio),
        "tipo": "gasto",
        "categoria": _categoria_por_comercio(comercio),
        "moneda": moneda,
        "monto": monto,
        "descripcion": f"Compra en {comercio} con {medio} *{tarjeta}",
        "entidad": "Bancolombia",
    }


def _p_pago_qr(t: str) -> dict | None:
    # "... pagaste $19000.00 por codigo QR desde tu cuenta *5360 a la llave 0046104279
    #  el 22/08/2026 a las 09:30."
    m = re.search(
        r"pagaste\s+\$?([\d.,]+)\s+por codigo QR desde tu cuenta\s+\*(\d+)\s+a la llave\s+(\S+)\s+el\s+"
        r"(\d{1,2})/(\d{1,2})/(\d{2,4})",
        t,
    )
    if not m:
        return None
    monto_str, cuenta, llave, dia, mes, anio = m.groups()
    return {
        "fecha": _fecha_iso(dia, mes, anio),
        "tipo": "gasto",
        "categoria": "transferencias",
        "moneda": "COP",
        "monto": _parsear_monto_plano(monto_str),
        "descripcion": f"Pago QR desde cuenta *{cuenta} a llave {llave}",
        "entidad": "Bancolombia",
    }


def _p_transferencia_breb(t: str) -> dict | None:
    # "... transferiste $32500.00 a la llave 1037669068 desde tu cuenta *5360 a
    #  ESTEBAN GARCIA ZAPATA el 01/09/26 a las 19:53. Con Bre-b es de una..."
    m = re.search(
        r"transferiste\s+\$?([\d.,]+)\s+a la llave\s+(\S+)\s+desde tu cuenta\s+\*(\d+)\s+a\s+(.+?)\s+el\s+"
        r"(\d{1,2})/(\d{1,2})/(\d{2,4})",
        t,
    )
    if not m:
        return None
    monto_str, llave, cuenta, destinatario, dia, mes, anio = m.groups()
    return {
        "fecha": _fecha_iso(dia, mes, anio),
        "tipo": "gasto",
        "categoria": "transferencias",
        "moneda": "COP",
        "monto": _parsear_monto_plano(monto_str),
        "descripcion": f"Envio Bre-B a {destinatario.strip()}",
        "entidad": "Bancolombia",
    }


def _p_transferencia_generica(t: str) -> dict | None:
    # "... Transferiste $1750000 desde tu cuenta *5360 a la cuenta *60963448182
    #  el 31/08/2026 a las 10:55."
    m = re.search(
        r"[Tt]ransferiste\s+\$?([\d.,]+)\s+desde tu cuenta\s+\*(\d+)\s+a la cuenta\s+\*(\S+?)\s+el\s+"
        r"(\d{1,2})/(\d{1,2})/(\d{2,4})",
        t,
    )
    if not m:
        return None
    monto_str, cuenta_origen, cuenta_destino, dia, mes, anio = m.groups()
    return {
        "fecha": _fecha_iso(dia, mes, anio),
        "tipo": "gasto",
        "categoria": "transferencias",
        "moneda": "COP",
        "monto": _parsear_monto_plano(monto_str),
        "descripcion": f"Transferencia a cuenta *{cuenta_destino}",
        "entidad": "Bancolombia",
    }


def _p_pago_recibido(t: str) -> dict | None:
    # "... Recibiste un pago de Nomina de CHOUCAIR CARDEN por $2026374.00 en tu
    #  cuenta de Ahorros el 31/08/2026 a las 09:22."
    m = re.search(
        r"[Rr]ecibiste un pago de\s+(.+?)\s+por\s+\$?([\d.,]+)\s+en tu cuenta de\s+.+?\s+el\s+"
        r"(\d{1,2})/(\d{1,2})/(\d{2,4})",
        t,
    )
    if not m:
        return None
    origen, monto_str, dia, mes, anio = m.groups()
    es_nomina = "nomina" in origen.lower() or "nómina" in origen.lower()
    return {
        "fecha": _fecha_iso(dia, mes, anio),
        "tipo": "ingreso",
        "categoria": "salario" if es_nomina else "otros",
        "moneda": "COP",
        "monto": _parsear_monto_plano(monto_str),
        "descripcion": f"Pago recibido: {origen.strip()}",
        "entidad": "Bancolombia",
    }


def _p_avance(t: str) -> dict | None:
    # "... Hiciste un avance de $200000 en tu SUC VIRTUAL el 11:28 21/08/2026 desde
    #  tu T.Credito *2011 a la cuenta *5360."
    m = re.search(
        r"[Hh]iciste un avance de\s+\$?([\d.,]+)\s+en tu\s+.+?\s+el\s+\d{2}:\d{2}\s+"
        r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s+desde tu\s+(T\.Cr[eé]dito)\s+\*(\d+)\s+a la cuenta\s+\*(\d+)",
        t,
    )
    if not m:
        return None
    monto_str, dia, mes, anio, _medio, tarjeta, cuenta = m.groups()
    return {
        "fecha": _fecha_iso(dia, mes, anio),
        "tipo": "gasto",  # enriquecer_movimiento() lo reclasifica a ingreso+es_deuda por ser "avance"
        "categoria": "avance_credito",
        "moneda": "COP",
        "monto": _parsear_monto_plano(monto_str),
        "descripcion": f"Avance T.Credito *{tarjeta} a cuenta *{cuenta}",
        "entidad": "Bancolombia",
    }


# Se prueban en este orden (los más específicos primero, para no matchear de más).
PARSERS = (
    _p_avance,
    _p_compra_tarjeta,
    _p_compra_tarjeta_asociada,
    _p_pago_qr,
    _p_transferencia_breb,
    _p_transferencia_generica,
    _p_pago_recibido,
)


def parsear_alerta_bancolombia(cuerpo: str) -> dict | None:
    """Recibe el cuerpo plano del correo y devuelve un movimiento, o None si
    el correo no es un movimiento financiero (ej. "apagaste tu tarjeta")."""
    t = re.sub(r"\s+", " ", cuerpo).strip()
    for parser in PARSERS:
        resultado = parser(t)
        if resultado:
            return resultado
    return None


# ----------------------------- IMAP -----------------------------

def cargar_credenciales() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"No existe {CONFIG_PATH}. Copia credenciales_correo.example.json a ese nombre "
            "y completa tu correo y contraseña de aplicación de Gmail "
            "(myaccount.google.com/apppasswords)."
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _texto_plano_del_mensaje(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for parte in msg.walk():
            if parte.get_content_type() == "text/plain" and "attachment" not in str(parte.get("Content-Disposition", "")):
                charset = parte.get_content_charset() or "utf-8"
                return parte.get_payload(decode=True).decode(charset, errors="replace")
        return ""
    charset = msg.get_content_charset() or "utf-8"
    return msg.get_payload(decode=True).decode(charset, errors="replace")


def buscar_movimientos_correo(dias: int) -> list[dict]:
    config = cargar_credenciales()
    host = config.get("imap_host", "imap.gmail.com")
    port = config.get("imap_port", 993)

    conn = imaplib.IMAP4_SSL(host, port)
    try:
        conn.login(config["email"], config["app_password"])
        conn.select("INBOX", readonly=True)

        desde = (datetime.date.today() - datetime.timedelta(days=dias)).strftime("%d-%b-%Y")
        movimientos = []
        for remitente in REMITENTES_BANCOLOMBIA:
            typ, data = conn.search(None, f'(FROM "{remitente}" SINCE {desde})')
            if typ != "OK":
                continue
            uids = data[0].split()
            for uid in uids:
                typ, msg_data = conn.fetch(uid, "(RFC822)")
                if typ != "OK" or not msg_data or msg_data[0] is None:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                cuerpo = _texto_plano_del_mensaje(msg)
                mov = parsear_alerta_bancolombia(cuerpo)
                if mov:
                    movimientos.append(mov)
        return movimientos
    finally:
        conn.logout()


# ----------------------------- Inserción con dedup -----------------------------

def insertar_sin_duplicar(conn, movimientos: list[dict]) -> dict:
    """Inserta solo los movimientos cuyo (fecha, monto redondeado) no exista
    ya en la base de datos, sin importar el origen — evita duplicar lo que
    ya haya entrado por el Excel/bot de Gmail viejo durante la transición."""
    cur = conn.cursor()
    existentes = set()
    for row in cur.execute("SELECT fecha, moneda, ROUND(monto) AS m FROM movimientos"):
        existentes.add((row["fecha"], row["moneda"], row["m"]))

    nuevos, duplicados = [], 0
    for m in movimientos:
        clave = (m["fecha"], m["moneda"], round(m["monto"]))
        if clave in existentes:
            duplicados += 1
            continue
        existentes.add(clave)  # evita duplicar contra sí mismo si el correo llega repetido en el mismo lote
        nuevos.append(m)

    enriquecidos = [db.enriquecer_movimiento(m) for m in nuevos]
    cur.executemany(
        """INSERT INTO movimientos (fecha, tipo, categoria, moneda, monto, descripcion, entidad, medio_pago, es_deuda, origen)
           VALUES (:fecha, :tipo, :categoria, :moneda, :monto, :descripcion, :entidad, :medio_pago, :es_deuda, 'correo_imap')""",
        enriquecidos,
    )
    conn.commit()
    return {"nuevos": len(nuevos), "duplicados": duplicados}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=7, help="Cuántos días hacia atrás buscar (default 7)")
    ap.add_argument("--aplicar", action="store_true", help="Insertar en la base de datos (si no, solo reporta)")
    args = ap.parse_args()

    print(f"Buscando notificaciones de Bancolombia de los últimos {args.dias} días...")
    movimientos = buscar_movimientos_correo(args.dias)
    print(f"Correos financieros parseados: {len(movimientos)}")
    for m in movimientos:
        print(f"  {m['fecha']}  {m['tipo']:6s}  {m['moneda']} {m['monto']:>12,.0f}  {m['descripcion']}")

    if not args.aplicar:
        print("\n(solo reporte -- corré con --aplicar para insertar en la base de datos)")
        return 0

    conn = db.conectar()
    try:
        db.crear_esquema(conn)
        stats = insertar_sin_duplicar(conn, movimientos)
    finally:
        conn.close()

    print(f"\nOK — {stats['nuevos']} movimientos nuevos insertados, {stats['duplicados']} ya existían (omitidos).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
