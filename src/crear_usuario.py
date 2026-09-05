"""
crear_usuario.py
==================
Crea (o actualiza la contraseña de) una cuenta de usuario. La contraseña
NUNCA se guarda en texto plano en ningún archivo -- se recibe por línea de
comandos, se hashea (scrypt, vía Werkzeug) y se descarta.

Uso:
    py crear_usuario.py --username tu_usuario --password "..." --rol admin --nombre "Nombre a mostrar"

--rol es "admin" (ve todos los usuarios, puede cambiar de perfil) o
"usuario" (solo ve su propia data).

Si ya existe una cuenta con ese username + rol, actualiza la contraseña
en vez de crear una duplicada.
"""

import argparse
import sys
import db_finanzas as db

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--rol", choices=["admin", "usuario"], required=True)
    ap.add_argument("--nombre", required=True, help="Nombre para mostrar en la app")
    args = ap.parse_args()

    conn = db.conectar()
    try:
        db.crear_esquema(conn)
        existente = conn.execute(
            "SELECT id FROM usuarios WHERE username = ? AND rol = ?", (args.username, args.rol)
        ).fetchone()

        from werkzeug.security import generate_password_hash
        if existente:
            conn.execute(
                "UPDATE usuarios SET password_hash = ?, nombre_mostrado = ? WHERE id = ?",
                (generate_password_hash(args.password), args.nombre, existente["id"]),
            )
            conn.commit()
            print(f"Actualizada: id={existente['id']} username={args.username} rol={args.rol} nombre={args.nombre}")
        else:
            uid = db.crear_usuario(conn, args.username, args.password, args.rol, args.nombre)
            print(f"Creada: id={uid} username={args.username} rol={args.rol} nombre={args.nombre}")

        if args.rol == "admin":
            n = db.asignar_movimientos_sin_dueno_a_admin(conn)
            if n:
                print(f"  {n} movimientos existentes (sin dueño) asignados a esta cuenta admin.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
