"""
app.py
========
Servidor local (Flask, open-source/gratis) que reemplaza a "abrir el HTML
con doble clic" cuando querés algo más que ver el dashboard: subir un
extracto (Excel o PDF) desde el navegador e insertarlo en finanzas.db.

Uso:
    py app.py
Abre solo en el navegador: http://127.0.0.1:5001

Rutas:
  /                    -> Dashboard (el mismo de siempre, embebido)
  /vista/dashboard     -> el archivo data/dashboard_finanzas.html tal cual
  /cargar-extractos    -> formulario para subir un extracto
  /api/cargar-extracto -> (POST) recibe el archivo, lo parsea, inserta con
                          dedup, y regenera el dashboard
"""

import sys
import datetime
import threading
import webbrowser
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import db_finanzas as db
import actualizar_dashboard

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import reconciliar_extractos as rex  # parsers de PDF ya construidos y probados

UPLOADS_DIR = db.DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("dashboard.html", activo="dashboard")


@app.route("/vista/dashboard")
def vista_dashboard():
    return send_from_directory(db.DATA_DIR, "dashboard_finanzas.html")


@app.route("/cargar-extractos")
def cargar_extractos():
    return render_template("cargar_extractos.html", activo="cargar")


@app.route("/api/cargar-extracto", methods=["POST"])
def api_cargar_extracto():
    archivo = request.files.get("archivo")
    tipo = request.form.get("tipo", "")
    if not archivo or not archivo.filename:
        return jsonify(ok=False, error="No se recibió ningún archivo."), 400

    destino = UPLOADS_DIR / archivo.filename
    archivo.save(destino)

    try:
        if tipo == "excel":
            movimientos = _leer_excel_generico(destino)
        elif tipo == "pdf_ahorros":
            crudos = rex.parse_savings_statement(destino)
            movimientos = [rex.normalizar_savings(m) for m in crudos]
        elif tipo == "pdf_tarjeta":
            marca = (request.form.get("marca") or "Credito").strip()
            ultimos4 = (request.form.get("ultimos4") or "").strip()
            if not ultimos4:
                return jsonify(ok=False, error="Falta indicar los últimos 4 dígitos de la tarjeta."), 400
            crudos = rex.parse_card_statement(destino, ultimos4)
            movimientos = [rex.normalizar_card(m, marca) for m in crudos]
        else:
            return jsonify(ok=False, error=f"Tipo de archivo desconocido: {tipo!r}"), 400
    except Exception as e:
        return jsonify(ok=False, error=f"No pude leer el archivo: {e}"), 400

    if not movimientos:
        return jsonify(ok=False, error="No encontré movimientos en ese archivo."), 400

    conn = db.conectar()
    try:
        db.crear_esquema(conn)
        stats = db.insertar_movimientos(conn, movimientos, origen=f"upload_{tipo}")
    finally:
        conn.close()

    actualizar_dashboard.main()  # regenera data/dashboard_finanzas.html con los datos nuevos

    return jsonify(ok=True, **stats)


def _leer_excel_generico(path) -> list[dict]:
    """Lee un .xlsx con las mismas columnas que la tabla movimientos
    (fecha, tipo, categoria, moneda, monto, descripcion, entidad), en la
    primera hoja del archivo."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active

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

        for campo in db.CAMPOS_ESPERADOS:
            d.setdefault(campo, "")

        rows.append(d)
    return rows


if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5001")).start()
    app.run(host="127.0.0.1", port=5001, debug=False)
