"""
Pruebas de src/actualizar_dashboard.py -- desde 2026-09-05 este script ya
NO genera HTML por usuario (no existen más inyectar_en_html(),
html_path_usuario() ni TEMPLATE_PATH): el dashboard ahora es dinámico y
pide sus datos vía GET /api/dashboard-data (ver
tests/test_app_integration.py). Lo único que le queda a main() es
sincronizar data/finanzas.db desde data/finanzas_personales.xlsx, si el
Excel existe -- si no existe, no hace nada y no es un error.

IMPORTANTE -- aislamiento de filesystem:
Este módulo tiene DOS familias de rutas que hay que aislar en los tests,
no solo la BD:
  1. db.DATA_DIR / db.DB_PATH / db.XLSX_PATH -- igual que ya hace
     tests/test_app_integration.py con su fixture app_ctx.
  2. actualizar_dashboard.PROJECT_ROOT y actualizar_dashboard.LOG_PATH --
     se calculan UNA sola vez al importar el módulo (igual que
     UPLOADS_DIR en app.py). Si no se parchean también, main() escribiría
     de verdad en la carpeta data/ del proyecto real (actualizar_dashboard.log)
     -- exactamente lo que este proyecto pide no tocar nunca desde un test.

Este archivo NO hace "import app" (esa importación está reservada a
tests/test_app_integration.py, ver su docstring), así que puede convivir
sin problema con el resto de la suite.
"""
import openpyxl
import pytest

import db_finanzas as db
import actualizar_dashboard as ad


# ----------------------------- Fixtures y helpers -----------------------------

@pytest.fixture
def dashboard_ctx(tmp_path, monkeypatch):
    """Aísla toda la corrida de actualizar_dashboard.main() en tmp_path:
    BD, Excel y la ruta de salida del log. Nunca toca data/finanzas.db ni
    data/finanzas_personales.xlsx reales."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "DB_PATH", data_dir / "finanzas.db")
    monkeypatch.setattr(db, "XLSX_PATH", data_dir / "finanzas_personales.xlsx")

    monkeypatch.setattr(ad, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ad, "LOG_PATH", data_dir / "actualizar_dashboard.log")

    return data_dir


def crear_admin(nombre_mostrado="Admin Test"):
    """Crea el esquema y un usuario admin en la BD ya parcheada por
    dashboard_ctx. Devuelve su id."""
    conn = db.conectar()
    db.crear_esquema(conn)
    admin_id = db.crear_usuario(conn, "admin_test", "clave-123", "admin", nombre_mostrado)
    conn.close()
    return admin_id


def crear_excel(filas):
    """Crea el Excel esperado por db_finanzas.leer_movimientos_excel() en
    la ruta ya parcheada (db.XLSX_PATH), con la hoja 'movimientos' y sus
    columnas exactas."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "movimientos"
    ws.append(["fecha", "tipo", "categoria", "moneda", "monto", "descripcion", "entidad"])
    for fila in filas:
        ws.append(fila)
    wb.save(db.XLSX_PATH)


# ----------------------------- Excel presente -----------------------------

def test_main_con_excel_presente_sincroniza_movimientos_a_la_bd(dashboard_ctx):
    """Caso feliz: con el Excel presente, main() sincroniza su contenido
    hacia la BD (asignado a la cuenta admin, como hace
    sincronizar_desde_excel) y deja un log 'OK'."""
    admin_id = crear_admin()
    crear_excel([
        ["2026-01-05", "ingreso", "salario", "COP", 3000000, "Pago nómina", "Empresa"],
        ["2026-01-10", "gasto", "mercado", "COP", 150000, "Compra T.Deb mercado", "Supermercado"],
    ])

    resultado = ad.main()

    assert resultado == 0

    log_texto = ad.LOG_PATH.read_text(encoding="utf-8")
    assert "OK" in log_texto
    assert "Excel sincronizado" in log_texto

    conn = db.conectar()
    movimientos_bd = db.obtener_movimientos(conn, usuario_id=admin_id)
    conn.close()
    assert len(movimientos_bd) == 2
    descripciones = {m["descripcion"] for m in movimientos_bd}
    assert "Pago nómina" in descripciones
    assert "Compra T.Deb mercado" in descripciones


def test_main_con_excel_presente_pero_sin_filas_sigue_siendo_un_error(dashboard_ctx):
    """Un Excel presente pero sin ninguna fila de datos (solo encabezados)
    sigue siendo un error explícito (leer_movimientos_excel lanza
    ValueError) -- main() debe seguir devolviendo 1, no confundir este
    caso con 'el Excel no existe'."""
    crear_admin()
    crear_excel([])  # solo encabezados, cero filas de datos

    resultado = ad.main()

    assert resultado == 1
    log_texto = ad.LOG_PATH.read_text(encoding="utf-8")
    assert "ERROR" in log_texto


# ----------------------------- Excel ausente -----------------------------

def test_main_sin_excel_no_lanza_excepcion_y_devuelve_cero(dashboard_ctx):
    """El bug que se corrigió con el cambio anterior: si el Excel no
    existe, main() no debe lanzar FileNotFoundError -- debe devolver 0
    sin tocar la BD."""
    crear_admin()
    assert not db.XLSX_PATH.exists()

    resultado = ad.main()

    assert resultado == 0
    log_texto = ad.LOG_PATH.read_text(encoding="utf-8")
    assert "OK" in log_texto
    assert "sin Excel activo" in log_texto


def test_main_sin_excel_ni_usuarios_ni_movimientos_no_revienta(dashboard_ctx):
    """El caso más disperso posible: ni Excel ni un solo usuario/movimiento
    en la BD. main() solo se encarga de sincronizar -- no calcula ningún
    perfil ni agregación -- así que debe seguir devolviendo 0 sin
    reventar, incluso con la BD recién creada."""
    assert not db.XLSX_PATH.exists()

    resultado = ad.main()

    assert resultado == 0
    log_texto = ad.LOG_PATH.read_text(encoding="utf-8")
    assert "OK" in log_texto


def test_main_crea_el_esquema_si_la_bd_no_existia_todavia(dashboard_ctx):
    """main() debe poder correr desde cero (BD inexistente, primera
    corrida) sin que haga falta invocar crear_esquema() a mano antes --
    ya lo hace internamente."""
    assert not db.DB_PATH.exists()

    resultado = ad.main()

    assert resultado == 0
    assert db.DB_PATH.exists()


def test_main_no_pisa_movimientos_ya_insertados_por_otra_via(dashboard_ctx):
    """Sin Excel, los movimientos que ya llegaron a la BD por otra vía
    (ej. registro manual o leer_correo.py) deben seguir intactos después
    de correr main() -- no debe borrar ni alterar nada fuera del bloque
    'gmail_bot_excel'."""
    admin_id = crear_admin()
    conn = db.conectar()
    db.insertar_movimientos(
        conn,
        [{
            "fecha": "2026-01-10", "tipo": "gasto", "categoria": "mercado", "moneda": "COP",
            "monto": 50000.0, "descripcion": "Compra sin Excel", "entidad": "Banco Test",
        }],
        origen="app_manual",
        usuario_id=admin_id,
    )
    conn.close()
    assert not db.XLSX_PATH.exists()

    resultado = ad.main()

    assert resultado == 0
    conn = db.conectar()
    movimientos = db.obtener_movimientos(conn, usuario_id=admin_id)
    conn.close()
    assert len(movimientos) == 1
    assert movimientos[0]["descripcion"] == "Compra sin Excel"
