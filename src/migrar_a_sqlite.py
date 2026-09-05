"""
migrar_a_sqlite.py
====================
Migración/reset: crea data/finanzas.db (si no existe) y la sincroniza con
todo lo que hay en data/finanzas_personales.xlsx, ya enriquecido con
medio_pago/es_deuda.

Uso puntual — el día a día lo maneja actualizar_dashboard.py, que también
sincroniza antes de regenerar el dashboard. Este script sirve para
verificar la sincronización a mano, o para reconstruir finanzas.db desde
cero si alguna vez hace falta.

    py migrar_a_sqlite.py

No borra ni modifica el Excel — es de solo lectura sobre él.
"""

import sys
import db_finanzas as db


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    existia = db.DB_PATH.exists()
    conn = db.conectar()
    try:
        db.crear_esquema(conn)
        stats = db.sincronizar_desde_excel(conn)
    finally:
        conn.close()

    print(f"{'Actualizada' if existia else 'Creada'}: {db.DB_PATH}")
    print(f"  Movimientos migrados: {stats['movimientos']} (rango {stats['fecha_min']} a {stats['fecha_max']})")
    print(f"  Marcados como deuda de tarjeta (compras/avances a crédito): {stats['en_deuda']}")
    print(f"  Filas de historial_actualizaciones: {stats['historial']}")

    movimientos_excel = db.leer_movimientos_excel()
    if len(movimientos_excel) != stats["movimientos"]:
        print(f"  ⚠ ADVERTENCIA: el Excel tiene {len(movimientos_excel)} filas pero se migraron {stats['movimientos']}.")
        return 1

    print("  OK — la base de datos coincide exactamente con el Excel actual.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
