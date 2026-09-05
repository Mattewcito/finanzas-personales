"""
actualizar_dashboard.py
========================
Lee la PLANTILLA dashboard/dashboard_finanzas.html (versionada en git, sin
datos reales) y genera data/dashboard_finanzas.html (con tus datos reales
adentro, ignorado por git) — ese segundo archivo es el que abrís con doble
clic todos los días.

Pensado para correr desatendido todos los días vía una tarea programada
de Windows (Task Scheduler), después de que el bot que sincroniza el
Excel desde Gmail haya terminado (hasta que la lectura de correo se
reemplace por una automatización local propia).

  1. Sincroniza data/finanzas.db desde data/finanzas_personales.xlsx.
  2. Consulta los movimientos ya enriquecidos y el ledger de deuda DESDE
     la base de datos (esa lógica vive en db_finanzas.py, un solo lugar).
  3. Reemplaza los bloques embebidos en dashboard_finanzas.html (DATA,
     DEUDA_TARJETAS y GENERATED_AT) usando marcadores de comentario.
  4. Sólo sobrescribe el HTML si todo el proceso fue exitoso — si algo
     falla, el dashboard existente queda intacto y el error se registra
     en actualizar_dashboard.log

No requiere red ni backend: todo corre localmente con openpyxl + sqlite3
(ambos ya vienen con Python, sin instalar nada adicional).

⚠️ NOTA IMPORTANTE (no es asesoría tributaria):
La clasificación débito/crédito es automática, basada en patrones de
texto de las notificaciones bancarias (ej. "T.Cred", "T.Deb", "Avance").
Para movimientos donde el correo original no especifica el medio de
pago, se asume "débito" por defecto — es decir, se cuenta como gasto
real de caja. Esto es una herramienta de organización personal; antes
de usar estos números para declarar renta, verificalos con tu contador.
"""

import json
import re
import sys
import datetime
import traceback
from pathlib import Path

# La consola de Windows (Task Scheduler incluido) suele usar cp1252, que no
# puede imprimir flechas/tildes especiales. Forzamos UTF-8 en stdout/stderr
# (con reemplazo silencioso si algo raro se cuela) para que un simple print()
# nunca tumbe la tarea programada.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import db_finanzas as db  # mismo folder (src/) — sincronización, esquema y consultas

PROJECT_ROOT = db.PROJECT_ROOT
TEMPLATE_PATH = PROJECT_ROOT / "dashboard" / "dashboard_finanzas.html"  # versionada en git, SIN datos reales
HTML_PATH = PROJECT_ROOT / "data" / "dashboard_finanzas.html"           # generada, CON datos reales, gitignored
LOG_PATH = PROJECT_ROOT / "data" / "actualizar_dashboard.log"


def log(msg: str) -> None:
    """Escribe una línea con timestamp en el log y también la imprime (útil si se corre a mano)."""
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _bloque(marcador: str, contenido: str) -> str:
    return f"/* __{marcador}_START__ */\n{contenido}\n/* __{marcador}_END__ */"


def _reemplazar_bloque(html: str, marcador: str, nuevo_contenido: str) -> str:
    patron = re.compile(rf"/\* __{marcador}_START__ \*/.*?/\* __{marcador}_END__ \*/", re.DOTALL)
    if not patron.search(html):
        raise ValueError(f"No se encontraron los marcadores __{marcador}_START__/__{marcador}_END__ en el HTML.")
    nuevo_bloque = _bloque(marcador, nuevo_contenido)
    # Se usa una función como reemplazo (no un string) para que re.sub no interprete
    # secuencias tipo \1 dentro del JSON generado.
    return patron.sub(lambda _: nuevo_bloque, html, count=1)


def inyectar_en_html(html: str, movimientos: list[dict], ledger_deuda: list[dict]) -> str:
    """Reemplaza los bloques DATA, DEUDA_TARJETAS y GENERATED_AT dentro
    del HTML, usando los marcadores de comentario como anclas. Falla
    ruidosamente (excepción) si algún marcador no se encuentra, para no
    corromper el archivo silenciosamente."""

    data_json = json.dumps(movimientos, ensure_ascii=False, indent=0)
    html = _reemplazar_bloque(html, "DATA", f"const DATA = {data_json};")

    deuda_json = json.dumps(ledger_deuda, ensure_ascii=False, indent=0)
    html = _reemplazar_bloque(html, "DEUDA_TARJETAS", f"const DEUDA_TARJETAS = {deuda_json};")

    hoy = datetime.date.today().isoformat()
    html = _reemplazar_bloque(html, "GENERATED_AT", f'const GENERATED_AT = "{hoy}"; // fecha de generación del dashboard')

    return html


def main() -> int:
    try:
        if not db.XLSX_PATH.exists():
            raise FileNotFoundError(f"No se encontró {db.XLSX_PATH}")
        if not TEMPLATE_PATH.exists():
            raise FileNotFoundError(f"No se encontró la plantilla {TEMPLATE_PATH}")

        conn = db.conectar()
        try:
            db.crear_esquema(conn)  # no-op si ya existe; asegura que la BD esté lista aunque sea la primera corrida
            stats = db.sincronizar_desde_excel(conn)
            movimientos = db.obtener_movimientos(conn)
            ledger_deuda = db.obtener_ledger_deuda(conn)
        finally:
            conn.close()

        # Siempre parte de la PLANTILLA (sin datos), nunca del HTML generado
        # la vez anterior — así nunca queda un dato viejo pegado por error.
        html_plantilla = TEMPLATE_PATH.read_text(encoding="utf-8")
        html_nuevo = inyectar_en_html(html_plantilla, movimientos, ledger_deuda)
        HTML_PATH.write_text(html_nuevo, encoding="utf-8")

        saldo_final = ledger_deuda[-1]["saldo_acumulado"] if ledger_deuda else 0.0
        log(
            f"OK — {stats['movimientos']} movimientos ({stats['fecha_min']} a {stats['fecha_max']}), "
            f"{stats['en_deuda']} marcados como deuda de tarjeta, saldo deuda estimado ${saldo_final:,.0f} "
            f"→ sincronizado a {db.DB_PATH.name} y volcado a {HTML_PATH.name}"
        )
        return 0

    except Exception as e:
        log(f"ERROR — el dashboard NO se actualizó: {e}")
        log(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
