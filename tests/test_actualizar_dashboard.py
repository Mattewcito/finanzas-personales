"""
Pruebas de src/actualizar_dashboard.py -- en particular de main(), que
desde 2026-09-05 dejó de ser un "todo o nada" respecto del Excel: si
data/finanzas_personales.xlsx no existe, ya NO lanza FileNotFoundError,
sino que salta la sincronización y regenera los dashboards igual con lo
que ya haya en la tabla `movimientos` (primer paso hacia dejar de
depender del Excel como fuente de datos).

IMPORTANTE -- aislamiento de filesystem:
Este módulo tiene DOS familias de rutas que hay que aislar en los tests,
no solo la BD:
  1. db.DATA_DIR / db.DB_PATH / db.XLSX_PATH -- igual que ya hace
     tests/test_app_integration.py con su fixture app_ctx.
  2. actualizar_dashboard.PROJECT_ROOT y actualizar_dashboard.LOG_PATH --
     se calculan UNA sola vez al importar el módulo (igual que
     UPLOADS_DIR en app.py), y html_path_usuario() los usa para decidir
     DÓNDE escribe cada dashboard_<id>.html. Si no se parchean también,
     main() escribiría de verdad en la carpeta data/ del proyecto real
     (ahí ya viven dashboard_1.html, dashboard_2.html, dashboard_4.html y
     actualizar_dashboard.log) -- exactamente lo que este proyecto pide
     no tocar nunca desde un test.
actualizar_dashboard.TEMPLATE_PATH SÍ se deja apuntando al archivo real
(dashboard/dashboard_finanzas.html): es la plantilla versionada en git,
sin datos reales, y solo se lee -- tal como indica la consigna.

Este archivo NO hace "import app" (esa importación está reservada a
tests/test_app_integration.py, ver su docstring), así que puede convivir
sin problema con el resto de la suite.
"""
import json

import openpyxl
import pytest

import db_finanzas as db
import actualizar_dashboard as ad


# ----------------------------- Fixtures y helpers -----------------------------

@pytest.fixture
def dashboard_ctx(tmp_path, monkeypatch):
    """Aísla toda la corrida de actualizar_dashboard.main() en tmp_path:
    BD, Excel y las rutas de salida (dashboard_<id>.html, log). Nunca
    toca data/finanzas.db ni data/finanzas_personales.xlsx reales."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "DB_PATH", data_dir / "finanzas.db")
    monkeypatch.setattr(db, "XLSX_PATH", data_dir / "finanzas_personales.xlsx")

    monkeypatch.setattr(ad, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ad, "LOG_PATH", data_dir / "actualizar_dashboard.log")
    # ad.TEMPLATE_PATH NO se toca: sigue apuntando a la plantilla real
    # versionada en git (dashboard/dashboard_finanzas.html), que es
    # segura de leer y no tiene datos reales adentro.

    return data_dir


def crear_admin(nombre_mostrado="Admin Test"):
    """Crea el esquema y un usuario admin en la BD ya parcheada por
    dashboard_ctx. Devuelve su id."""
    conn = db.conectar()
    db.crear_esquema(conn)
    admin_id = db.crear_usuario(conn, "admin_test", "clave-123", "admin", nombre_mostrado)
    conn.close()
    return admin_id


def crear_usuario_normal(nombre_mostrado="Usuario Test"):
    conn = db.conectar()
    user_id = db.crear_usuario(conn, "user_test", "clave-456", "usuario", nombre_mostrado)
    conn.close()
    return user_id


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


def insertar_movimiento_directo_bd(usuario_id, fecha="2026-01-10", monto=50000.0,
                                    descripcion="Compra mercado", categoria="mercado"):
    """Simula un movimiento que ya llegó a la BD por una vía que no es el
    Excel (el escenario que main() ahora debe soportar)."""
    conn = db.conectar()
    db.insertar_movimientos(
        conn,
        [{
            "fecha": fecha, "tipo": "gasto", "categoria": categoria, "moneda": "COP",
            "monto": monto, "descripcion": descripcion, "entidad": "Banco Test",
        }],
        origen="app_manual",
        usuario_id=usuario_id,
    )
    conn.close()


def extraer_bloque_json(html, marcador, prefijo):
    """Extrae y parsea el JSON embebido entre los marcadores de
    comentario que usa inyectar_en_html (ej. 'const DATA = [...]')."""
    inicio = html.index(f"/* __{marcador}_START__ */")
    fin = html.index(f"/* __{marcador}_END__ */")
    bloque = html[inicio:fin]
    json_str = bloque.split(prefijo, 1)[1].rsplit(";", 1)[0].strip()
    return json.loads(json_str)


# ----------------------------- Excel presente: comportamiento sin cambios -----------------------------

def test_main_con_excel_presente_sincroniza_y_regenera_dashboard(dashboard_ctx):
    """Caso feliz: con el Excel presente, main() sigue sincronizando desde
    él (igual que antes del cambio) y regenera el dashboard del usuario."""
    admin_id = crear_admin()
    crear_excel([
        ["2026-01-05", "ingreso", "salario", "COP", 3000000, "Pago nómina", "Empresa"],
        ["2026-01-10", "gasto", "mercado", "COP", 150000, "Compra T.Deb mercado", "Supermercado"],
    ])

    resultado = ad.main()

    assert resultado == 0
    dashboard_path = ad.html_path_usuario(admin_id)
    assert dashboard_path.exists()

    html = dashboard_path.read_text(encoding="utf-8")
    data = extraer_bloque_json(html, "DATA", "const DATA = ")
    assert len(data) == 2
    descripciones = {m["descripcion"] for m in data}
    assert "Pago nómina" in descripciones
    assert "Compra T.Deb mercado" in descripciones

    log_texto = ad.LOG_PATH.read_text(encoding="utf-8")
    assert "OK" in log_texto
    assert "Excel sincronizado" in log_texto

    # La sincronización también debe haber quedado reflejada en la BD.
    conn = db.conectar()
    movimientos_bd = db.obtener_movimientos(conn, usuario_id=admin_id)
    conn.close()
    assert len(movimientos_bd) == 2


def test_main_con_excel_presente_pero_sin_filas_sigue_fallando_como_antes(dashboard_ctx):
    """No es parte del cambio actual: un Excel presente pero sin ninguna
    fila de datos (solo encabezados) sigue siendo un error explícito
    (leer_movimientos_excel lanza ValueError) -- main() debe seguir
    devolviendo 1, no tragarse silenciosamente este otro caso distinto
    de 'el Excel no existe'."""
    crear_admin()
    crear_excel([])  # solo encabezados, cero filas de datos

    resultado = ad.main()

    assert resultado == 1
    log_texto = ad.LOG_PATH.read_text(encoding="utf-8")
    assert "ERROR" in log_texto


# ----------------------------- Excel ausente: comportamiento nuevo -----------------------------

def test_main_sin_excel_no_lanza_excepcion_y_devuelve_cero(dashboard_ctx):
    """El bug que se corrige: antes, si el Excel no existía, main()
    lanzaba FileNotFoundError. Ahora debe devolver 0 sin excepción."""
    admin_id = crear_admin()
    insertar_movimiento_directo_bd(admin_id)
    assert not db.XLSX_PATH.exists()

    resultado = ad.main()

    assert resultado == 0


def test_main_sin_excel_regenera_dashboard_con_lo_que_ya_hay_en_bd(dashboard_ctx):
    """Sin Excel, pero con movimientos ya insertados directo en la BD
    (el escenario objetivo de este cambio), el dashboard debe reflejar
    esos movimientos igual, y el log debe explicar que no hubo Excel."""
    admin_id = crear_admin()
    insertar_movimiento_directo_bd(admin_id, descripcion="Compra sin Excel", monto=75000.0)
    assert not db.XLSX_PATH.exists()

    resultado = ad.main()

    assert resultado == 0
    dashboard_path = ad.html_path_usuario(admin_id)
    assert dashboard_path.exists()

    html = dashboard_path.read_text(encoding="utf-8")
    data = extraer_bloque_json(html, "DATA", "const DATA = ")
    assert len(data) == 1
    assert data[0]["descripcion"] == "Compra sin Excel"

    log_texto = ad.LOG_PATH.read_text(encoding="utf-8")
    assert "Sin Excel activo" in log_texto


def test_main_sin_excel_ni_movimientos_genera_dashboard_vacio_sin_reventar(dashboard_ctx):
    """El caso más disperso posible: ni Excel ni un solo movimiento en la
    BD para ningún usuario. main() no debe reventar (ni con excepción ni
    con NaN%/división por cero al calcular el perfil financiero) y debe
    dejar un dashboard válido, con listas vacías."""
    admin_id = crear_admin()
    assert not db.XLSX_PATH.exists()

    resultado = ad.main()

    assert resultado == 0
    dashboard_path = ad.html_path_usuario(admin_id)
    assert dashboard_path.exists()

    html = dashboard_path.read_text(encoding="utf-8")
    assert extraer_bloque_json(html, "DATA", "const DATA = ") == []
    assert extraer_bloque_json(html, "DEUDA_TARJETAS", "const DEUDA_TARJETAS = ") == []

    perfil = extraer_bloque_json(html, "PERFIL_FINANCIERO", "const PERFIL_FINANCIERO = ")
    assert perfil["arquetipo"] == "Sin datos suficientes"

    log_texto = ad.LOG_PATH.read_text(encoding="utf-8")
    assert "OK" in log_texto


# ----------------------------- Aislamiento entre usuarios -----------------------------

def test_main_sin_excel_no_filtra_movimientos_entre_usuarios(dashboard_ctx):
    """Con el Excel ausente, cada usuario debe seguir viendo solo SUS
    propios movimientos en su propio dashboard_<id>.html -- ninguno debe
    heredar ni ver datos del otro (fuga de datos entre usuarios, el bug
    de regresión ya visto antes en este proyecto)."""
    admin_id = crear_admin()
    user_id = crear_usuario_normal()
    insertar_movimiento_directo_bd(user_id, descripcion="Gasto solo del usuario normal")

    resultado = ad.main()

    assert resultado == 0

    html_admin = ad.html_path_usuario(admin_id).read_text(encoding="utf-8")
    html_user = ad.html_path_usuario(user_id).read_text(encoding="utf-8")

    data_admin = extraer_bloque_json(html_admin, "DATA", "const DATA = ")
    data_user = extraer_bloque_json(html_user, "DATA", "const DATA = ")

    assert data_admin == []
    assert len(data_user) == 1
    assert data_user[0]["descripcion"] == "Gasto solo del usuario normal"


# ----------------------------- html_path_usuario -----------------------------

def test_html_path_usuario_usa_un_archivo_distinto_por_usuario(dashboard_ctx):
    """Cada usuario tiene su propio archivo dashboard_<id>.html -- nunca
    uno combinado -- según el comentario de la propia función."""
    ruta_1 = ad.html_path_usuario(1)
    ruta_2 = ad.html_path_usuario(2)

    assert ruta_1 != ruta_2
    assert ruta_1.name == "dashboard_1.html"
    assert ruta_2.name == "dashboard_2.html"
