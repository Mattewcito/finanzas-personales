"""
actualizar_dashboard.py
========================
Hasta 2026-09-05 este script generaba un HTML por usuario con los datos
horneados adentro (`data/dashboard_<id>.html`), que era lo que Flask
servía tal cual. El dashboard ahora es DINÁMICO: `/vista/dashboard`
sirve un único archivo estático (`dashboard/dashboard_finanzas.html`) y
el navegador le pide sus propios datos a `/api/dashboard-data` al
cargar (ver `routes/dashboard.py::api_dashboard_data`) -- ya no hay
"regenerar" ni archivos por usuario en disco.

Lo único que le queda a este script es sincronizar `data/finanzas.db`
desde `data/finanzas_personales.xlsx`, mientras el Excel siga siendo un
canal de ingesta activo (el bot externo de Gmail que lo escribe todavía
no se reemplazó del todo por `leer_correo.py`, que ya inserta directo a
la BD). Si el Excel no existe, correr este script no hace nada -- no es
un error.

Sigue pensado para correr desatendido vía la tarea programada de
Windows ("ActualizarDashboardFinanzas"), pero una vez que el Excel se
retire del todo, ese script y esa tarea programada dejan de tener
trabajo que hacer y se pueden borrar.

⚠️ NOTA IMPORTANTE (no es asesoría tributaria):
La clasificación débito/crédito es automática, basada en patrones de
texto de las notificaciones bancarias (ej. "T.Cred", "T.Deb", "Avance").
Para movimientos donde el correo original no especifica el medio de
pago, se asume "débito" por defecto — es decir, se cuenta como gasto
real de caja. Esto es una herramienta de organización personal; antes
de usar estos números para declarar renta, verificalos con tu contador.
"""

import sys
import datetime
import traceback

# La consola de Windows (Task Scheduler incluido) suele usar cp1252, que no
# puede imprimir flechas/tildes especiales. Forzamos UTF-8 en stdout/stderr
# (con reemplazo silencioso si algo raro se cuela) para que un simple print()
# nunca tumbe la tarea programada.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import db_finanzas as db  # mismo folder (src/) — sincronización y esquema

PROJECT_ROOT = db.PROJECT_ROOT
LOG_PATH = PROJECT_ROOT / "data" / "actualizar_dashboard.log"


def log(msg: str) -> None:
    """Escribe una línea con timestamp en el log y también la imprime (útil si se corre a mano)."""
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    try:
        conn = db.conectar()
        try:
            db.crear_esquema(conn)  # no-op si ya existe; asegura que la BD esté lista aunque sea la primera corrida

            if db.XLSX_PATH.exists():
                stats = db.sincronizar_desde_excel(conn)
                log(f"OK — Excel sincronizado ({stats['movimientos']} filas, {stats['fecha_min']} a {stats['fecha_max']}).")
            else:
                log("OK — sin Excel activo, nada que sincronizar (el dashboard ya lee la BD directo).")
        finally:
            conn.close()
        return 0

    except Exception as e:
        log(f"ERROR — la sincronización con el Excel falló: {e}")
        log(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
