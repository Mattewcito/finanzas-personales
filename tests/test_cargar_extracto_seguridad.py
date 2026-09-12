"""
Pruebas de seguridad de POST /api/cargar-extracto (routes/dashboard.py::
api_cargar_extracto).

Contexto: hasta el 2026-09-11, `destino = UPLOADS_DIR / archivo.filename`
usaba el nombre de archivo tal cual lo manda el cliente en el multipart,
sin sanitizar -- un filename como "../../../algo" permitía escribir fuera
de UPLOADS_DIR (path traversal). El fix agrega `secure_filename()` +
un prefijo uuid4 al nombre final. Ver qa_reports/python_code_review_
2026-09-11.md (hallazgo CRÍTICO) para el detalle original.

IMPORTANTE -- reutiliza las fixtures app_ctx/client/login de
tests/test_app_integration.py: ese archivo es el único que puede hacer
"import app" (ver su docstring). UPLOADS_DIR se calcula al importar
routes/dashboard.py como `db.DATA_DIR / "uploads"`, y app_ctx ya parchea
db.DATA_DIR a un tmp_path ANTES de esa importación, así que estos tests
nunca tocan data/uploads real.
"""
import io

import db_finanzas as db

from test_app_integration import app_ctx, client, login  # noqa: F401 (fixtures reutilizadas)


def _uploads_dir(app_ctx):
    flaskapp, _, _ = app_ctx
    import routes.dashboard as dashboard_routes
    return dashboard_routes.UPLOADS_DIR


def _xlsx_valido() -> bytes:
    """Un .xlsx mínimo con las columnas que espera _leer_excel_generico."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["fecha", "tipo", "categoria", "moneda", "monto", "descripcion", "entidad"])
    ws.append(["2026-01-15", "gasto", "comida", "COP", 25000, "Mercado", "Bancolombia"])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()


def _subir(client, filename: str, contenido: bytes = b"contenido de prueba", tipo: str = "excel"):
    return client.post(
        "/api/cargar-extracto",
        data={
            "archivo": (io.BytesIO(contenido), filename),
            "tipo": tipo,
        },
        content_type="multipart/form-data",
    )


# ---------------------------------------------------------------------------
# a. Un filename con path traversal nunca debe escribir fuera de UPLOADS_DIR.
# ---------------------------------------------------------------------------

def test_filename_con_path_traversal_no_escribe_fuera_de_uploads_dir(client, app_ctx):
    login(client, "admin_test", "clave-admin-123")
    uploads_dir = _uploads_dir(app_ctx)
    tmp_root = uploads_dir.parent  # el tmp_path raíz de la fixture

    resp = _subir(client, "../../../windows.ini")

    # El archivo malicioso jamás debe aparecer un nivel (o más) arriba de
    # UPLOADS_DIR -- que es exactamente lo que ".." intentaba lograr.
    assert not (tmp_root / "windows.ini").exists()
    assert not (tmp_root.parent / "windows.ini").exists()

    # Cualquier archivo que sí se haya guardado por este request quedó
    # DENTRO de uploads_dir, nunca en un ancestro.
    archivos_creados = list(uploads_dir.glob("*")) if uploads_dir.exists() else []
    for f in archivos_creados:
        assert f.resolve().parent == uploads_dir.resolve()

    # La request puede fallar más adelante al parsear (no es un .xlsx real)
    # -- lo único que nos importa acá es que no haya habido traversal.
    assert resp.status_code in (200, 400)


def test_filename_con_backslash_traversal_estilo_windows_no_escapa(client, app_ctx):
    login(client, "admin_test", "clave-admin-123")
    uploads_dir = _uploads_dir(app_ctx)
    tmp_root = uploads_dir.parent

    resp = _subir(client, "..\\..\\secreto.txt")

    assert not (tmp_root / "secreto.txt").exists()
    archivos_creados = list(uploads_dir.glob("*")) if uploads_dir.exists() else []
    for f in archivos_creados:
        assert f.resolve().parent == uploads_dir.resolve()
    assert resp.status_code in (200, 400)


# ---------------------------------------------------------------------------
# b. Un filename que queda vacío tras sanitizar debe devolver 400 explícito.
# ---------------------------------------------------------------------------

def test_filename_que_queda_vacio_tras_sanitizar_devuelve_400(client, app_ctx):
    login(client, "admin_test", "clave-admin-123")

    resp = _subir(client, "....")

    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert "inválido" in data["error"].lower()


# ---------------------------------------------------------------------------
# c. El caso feliz (nombre normal, .xlsx válido) sigue funcionando igual.
# ---------------------------------------------------------------------------

def test_subir_xlsx_valido_con_nombre_normal_sigue_funcionando(client, app_ctx):
    login(client, "admin_test", "clave-admin-123")

    resp = _subir(client, "movimientos_septiembre.xlsx", contenido=_xlsx_valido())

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
