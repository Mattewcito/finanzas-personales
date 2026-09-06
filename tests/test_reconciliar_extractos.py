"""
Pruebas de src/tools/reconciliar_extractos.py -- enfocadas en el cambio
de 2026-09-06 que agregó `password=None` a pdf_text/parse_savings_statement/
parse_card_statement (para poder abrir los PDFs de extracto que llegan
adjuntos por correo cifrados con la cédula del titular, ver
leer_correo.py::_parsear_pdf_adjunto).

No se generan PDFs reales (frágil, no vale la pena) -- se mockea
`pdfplumber.open` para devolver texto de página controlado, y se verifica
que la contraseña efectivamente se propaga hasta ahí (o "" si no se pasa
ninguna, que es lo que pdfplumber espera para un PDF sin cifrar).

Este archivo NO hace "import app" y no toca ningún archivo real en disco
-- "archivo.pdf" nunca se abre de verdad porque pdfplumber.open está
mockeado.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "tools"))
import reconciliar_extractos as rex


class _FakePage:
    def __init__(self, texto):
        self._texto = texto

    def extract_text(self):
        return self._texto


class _FakePDF:
    def __init__(self, paginas_texto):
        self.pages = [_FakePage(t) for t in paginas_texto]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_pdfplumber_open(paginas_texto, capturado):
    def _open(path, password=""):
        capturado["password"] = password
        return _FakePDF(paginas_texto)
    return _open


# ----------------------------- pdf_text() -----------------------------

def test_pdf_text_sin_password_pasa_cadena_vacia_a_pdfplumber(monkeypatch):
    capturado = {}
    monkeypatch.setattr(rex.pdfplumber, "open", _fake_pdfplumber_open(["texto de prueba"], capturado))

    paginas = rex.pdf_text("archivo.pdf")

    assert paginas == ["texto de prueba"]
    assert capturado["password"] == ""


def test_pdf_text_con_password_none_explicito_pasa_cadena_vacia(monkeypatch):
    capturado = {}
    monkeypatch.setattr(rex.pdfplumber, "open", _fake_pdfplumber_open(["texto"], capturado))

    rex.pdf_text("archivo.pdf", password=None)

    assert capturado["password"] == ""


def test_pdf_text_con_password_la_pasa_tal_cual(monkeypatch):
    capturado = {}
    monkeypatch.setattr(rex.pdfplumber, "open", _fake_pdfplumber_open(["texto"], capturado))

    rex.pdf_text("archivo.pdf", password="12345678")

    assert capturado["password"] == "12345678"


def test_pdf_text_con_paginas_vacias_no_rompe(monkeypatch):
    """Página sin texto extraíble (extract_text() devuelve None) -- no
    debe romper, debe convertirse en cadena vacía."""
    capturado = {}

    class _FakePaginaSinTexto:
        def extract_text(self):
            return None

    class _FakePDFConPaginaVacia:
        def __init__(self):
            self.pages = [_FakePaginaSinTexto()]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _open(path, password=""):
        capturado["password"] = password
        return _FakePDFConPaginaVacia()

    monkeypatch.setattr(rex.pdfplumber, "open", _open)

    assert rex.pdf_text("archivo.pdf") == [""]


# ----------------------------- parse_savings_statement() -----------------------------

def test_parse_savings_statement_acepta_password_none_por_defecto(monkeypatch):
    capturado = {}
    texto = "DESDE: 2026/01/01 HASTA: 2026/01/31\n15/01 COMPRA EN ALGO -50,000.00 100,000.00"
    monkeypatch.setattr(rex.pdfplumber, "open", _fake_pdfplumber_open([texto], capturado))

    movimientos, intereses, p_desde, p_hasta = rex.parse_savings_statement("archivo.pdf")

    assert capturado["password"] == ""
    assert p_desde == "2026-01-01"
    assert p_hasta == "2026-01-31"
    assert len(movimientos) == 1
    assert movimientos[0]["fecha"] == "2026-01-15"
    assert movimientos[0]["valor"] == -50000.0
    assert intereses == 0.0


def test_parse_savings_statement_pasa_password_explicito_hasta_pdfplumber(monkeypatch):
    capturado = {}
    texto = "DESDE: 2026/01/01 HASTA: 2026/01/31"
    monkeypatch.setattr(rex.pdfplumber, "open", _fake_pdfplumber_open([texto], capturado))

    rex.parse_savings_statement("archivo.pdf", password="79912345")

    assert capturado["password"] == "79912345"


def test_parse_savings_statement_sin_movimientos_no_rompe(monkeypatch):
    """Caso disperso: extracto de un período sin ningún movimiento (solo
    intereses, o directamente vacío) no debe reventar."""
    capturado = {}
    texto = "DESDE: 2026/01/01 HASTA: 2026/01/31"
    monkeypatch.setattr(rex.pdfplumber, "open", _fake_pdfplumber_open([texto], capturado))

    movimientos, intereses, p_desde, p_hasta = rex.parse_savings_statement("archivo.pdf")

    assert movimientos == []
    assert intereses == 0.0


# ----------------------------- parse_card_statement() -----------------------------

def test_parse_card_statement_acepta_password_none_por_defecto(monkeypatch):
    capturado = {}
    texto = "ESTADO DE CUENTA EN: PESOS\nDetalles del movimiento\n01/01/2026 COMPRA EN ALGO $ 50.000,00"
    monkeypatch.setattr(rex.pdfplumber, "open", _fake_pdfplumber_open([texto], capturado))

    movimientos, intereses, p_desde, p_hasta = rex.parse_card_statement("archivo.pdf", "2011")

    assert capturado["password"] == ""
    assert len(movimientos) == 1
    assert movimientos[0]["moneda"] == "COP"
    assert movimientos[0]["valor"] == 50000.0
    assert movimientos[0]["ultimos4"] == "2011"


def test_parse_card_statement_pasa_password_explicito_hasta_pdfplumber(monkeypatch):
    capturado = {}
    texto = "ESTADO DE CUENTA EN: PESOS\nDetalles del movimiento\n01/01/2026 COMPRA EN ALGO $ 50.000,00"
    monkeypatch.setattr(rex.pdfplumber, "open", _fake_pdfplumber_open([texto], capturado))

    rex.parse_card_statement("archivo.pdf", "2011", password="1122334455")

    assert capturado["password"] == "1122334455"


def test_parse_card_statement_pagina_de_caratula_sin_detalle_no_aporta_movimientos(monkeypatch):
    """Página de resumen/carátula (sin 'Detalles del movimiento') -- debe
    ignorarse, no romper ni contar movimientos de más."""
    capturado = {}
    texto = "ESTADO DE CUENTA EN: PESOS\nSolo caratula, sin detalle de movimientos"
    monkeypatch.setattr(rex.pdfplumber, "open", _fake_pdfplumber_open([texto], capturado))

    movimientos, intereses, p_desde, p_hasta = rex.parse_card_statement("archivo.pdf", "2011")

    assert movimientos == []
