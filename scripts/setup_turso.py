#!/usr/bin/env python3
"""
setup_turso.py
==============
Crea la base de datos en Turso y escribe el .env listo para usar.

Uso (desde PowerShell con TURSO_API_TOKEN ya seteada):
    cd "C:/Finanzas personales"
    python scripts/setup_turso.py

El script:
  1. Crea la BD "cuadre-finanzas" en la org de Turso
  2. Genera un token de acceso a la BD
  3. Escribe el archivo .env en la raiz del proyecto
"""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

ORG   = "mattewcito"
DB    = "cuadre-finanzas"
API   = "https://api.turso.tech/v1"
ROOT  = Path(__file__).resolve().parent.parent
ENV   = ROOT / ".env"

def request(method, path, body=None):
    token = os.environ.get("TURSO_API_TOKEN", "").strip()
    if not token:
        print("ERROR: TURSO_API_TOKEN no está seteada.")
        print("       Corré:  $env:TURSO_API_TOKEN = \"tu-token\"")
        sys.exit(1)
    url  = f"{API}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type",  "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"ERROR HTTP {e.code}: {err}")
        sys.exit(1)

def main():
    # Determinar el grupo a usar
    print("0. Listando grupos disponibles...")
    groups_resp = request("GET", f"/organizations/{ORG}/groups")
    groups = groups_resp.get("groups", [])
    if not groups:
        # Consultar ubicaciones disponibles y usar la primera
        locs = request("GET", "/locations")
        loc_code = list(locs.get("locations", {}).keys())[0]
        print(f"   No hay grupos. Creando grupo 'default' en {loc_code}...")
        request("POST", f"/organizations/{ORG}/groups",
                {"name": "default", "location": loc_code})
        group_name = "default"
    else:
        group_name = groups[0]["name"]
        print(f"   Usando grupo: '{group_name}'")

    print(f"1. Creando BD '{DB}' en org '{ORG}' (grupo '{group_name}')...")
    try:
        db = request("POST", f"/organizations/{ORG}/databases",
                     {"name": DB, "group": group_name})
        hostname = db["database"]["Hostname"]
        print(f"   OK — hostname: {hostname}")
    except SystemExit:
        # puede que ya exista, intento obtenerla
        print("   (posiblemente ya existe, verificando...)")
        db_info = request("GET", f"/organizations/{ORG}/databases/{DB}")
        hostname = db_info["database"]["Hostname"]
        print(f"   Encontrada — hostname: {hostname}")

    print("2. Generando token de acceso a la BD...")
    tok = request("POST",
                  f"/organizations/{ORG}/databases/{DB}/auth/tokens",
                  {"expiration": "never"})
    db_token = tok["jwt"]
    print("   OK")

    db_url = f"libsql://{hostname}"

    print(f"3. Escribiendo {ENV} ...")
    ENV.write_text(
        f"# Generado por scripts/setup_turso.py — no subir a git\n"
        f"TURSO_DATABASE_URL={db_url}\n"
        f"TURSO_AUTH_TOKEN={db_token}\n",
        encoding="utf-8",
    )
    print(f"   OK — {ENV}")

    print("\n✓ Listo. Ahora corré:")
    print("   python scripts/migrar_a_turso.py")
    print("   (con las mismas vars de entorno seteadas, o después de que el .env esté en su lugar)")

if __name__ == "__main__":
    main()
