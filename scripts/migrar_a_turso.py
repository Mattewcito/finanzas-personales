#!/usr/bin/env python3
"""
migrar_a_turso.py
=================
Copia todos los datos de finanzas.db local a la base remota de Turso.
Corre una sola vez después de crear la cuenta y configurar el .env.

Uso:
    cd "C:\\Finanzas personales"
    set TURSO_DATABASE_URL=libsql://tu-base.turso.io
    set TURSO_AUTH_TOKEN=tu-token
    python scripts/migrar_a_turso.py

El script es idempotente: usa INSERT OR IGNORE, así que si lo corrés de
nuevo no duplica datos (asume que los IDs no cambiaron).
"""

import os
import sys
import sqlite3
from pathlib import Path

# ---- paths ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
SRC  = ROOT / "src"
DB   = ROOT / "data" / "finanzas.db"

sys.path.insert(0, str(SRC))   # para importar db_finanzas y crear_esquema


def main() -> None:
    turso_url   = os.environ.get("TURSO_DATABASE_URL", "").strip()
    turso_token = os.environ.get("TURSO_AUTH_TOKEN",   "").strip()

    if not turso_url or not turso_token:
        print("ERROR: configurá TURSO_DATABASE_URL y TURSO_AUTH_TOKEN antes de correr el script.")
        print("       Copiá .env.example como .env y rellená los valores.")
        sys.exit(1)

    if not DB.exists():
        print(f"ERROR: no encontré la base local en {DB}")
        sys.exit(1)

    try:
        import libsql_experimental as libsql
    except ImportError:
        print("ERROR: falta libsql-experimental. Corré:  pip install libsql-experimental")
        sys.exit(1)

    # --- conexión origen (SQLite local) ---
    print(f"Leyendo  {DB} ...")
    local = sqlite3.connect(DB)
    local.row_factory = sqlite3.Row

    # --- conexión destino (Turso remoto) ---
    print(f"Conectando a {turso_url} ...")
    remote = libsql.connect(turso_url, auth_token=turso_token)

    # --- crear esquema en Turso (idempotente: usa CREATE TABLE IF NOT EXISTS) ---
    print("Creando esquema en Turso ...")
    import db_finanzas as db
    db.crear_esquema(remote)

    # --- tablas a migrar (en orden para respetar FK) ---
    # Orden respeta FKs: tablas padre antes que hijas
    TABLAS = [
        "usuarios",
        "tarjetas_credito",       # referenciada por movimientos.tarjeta_id
        "metas_ahorro",           # referenciada por movimientos.meta_ahorro_id
        "movimientos",
        "historial_actualizaciones",
        "correo_config",
        "vistas_ocultas",
        "presupuesto",
        "presupuesto_categorias",
    ]

    tablas_existentes = {
        r[0] for r in local.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    total = 0
    for tabla in TABLAS:
        if tabla not in tablas_existentes:
            print(f"  {tabla:<30} (no existe en local, omitida)")
            continue

        filas = local.execute(f"SELECT * FROM {tabla}").fetchall()
        if not filas:
            print(f"  {tabla:<30} 0 filas")
            continue

        cols         = filas[0].keys()
        col_names    = ", ".join(cols)
        placeholders = ", ".join(["?"] * len(cols))
        sql          = f"INSERT OR IGNORE INTO {tabla} ({col_names}) VALUES ({placeholders})"

        remote.executemany(sql, [tuple(r) for r in filas])
        remote.commit()
        print(f"  {tabla:<30} {len(filas)} filas migradas")
        total += len(filas)

    local.close()
    print(f"\n✓ Migración completada — {total} filas en total.")
    print("  Podés borrar data/finanzas.db local una vez que verifiques que todo funciona.")


if __name__ == "__main__":
    main()
