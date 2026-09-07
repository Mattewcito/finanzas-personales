"""
tools/qa/playwright_utils.py
==============================
Helpers reutilizables para el agente `qa-responsive` (ver
`.claude/agents/qa-responsive.md`). Existen porque las herramientas de
navegador del panel de Claude Code (Claude_Browser) devuelven las
capturas de pantalla "en línea" para que el modelo las vea, pero NO las
guarda como archivo -- no hay forma de sacarlas a disco para meterlas
después en un Excel. Playwright sí guarda capturas reales en PNG, así
que este módulo es la base para que la corrida de QA responsive
produzca un reporte con capturas de verdad embebidas, no descripciones
de memoria.

Requiere el entorno de `requirements-qa.txt` (Playwright + navegadores
Chromium ya instalados vía `playwright install chromium`) -- ES
DELIBERADAMENTE UN REQUIREMENTS APARTE del `requirements.txt` de la
app: Playwright descarga un binario de navegador de ~150-300MB que no
tiene ningún motivo para viajar dentro de la imagen Docker de
producción/dev, solo se necesita en la máquina donde corre este agente.

Todo acá apunta siempre a `http://127.0.0.1:5001` (el contenedor
`dev`) salvo que se pase `base_url` explícito -- este helper no decide
por su cuenta pegarle a `prod` (puerto 5002), esa regla vive en las
instrucciones del agente, no en el código, así que quien lo use debe
respetarla igual.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL_DEV = "http://127.0.0.1:5001"

# (ancho, alto) -- los mismos 3 breakpoints que usa el resto del
# proyecto para QA manual (ver qa-responsive.md).
BREAKPOINTS = {
    "mobile": (375, 812),
    "tablet": (768, 1024),
    "desktop": (1920, 1080),
}


@dataclass
class SesionQA:
    """Una página de Playwright + todo lo que fuimos acumulando
    durante la corrida (errores de consola, respuestas HTTP fallidas)
    para un breakpoint puntual. Se crea con `nueva_sesion()`."""
    page: object
    browser: object
    playwright: object
    breakpoint: str
    errores_consola: list[str] = field(default_factory=list)
    respuestas_fallidas: list[str] = field(default_factory=list)

    def cerrar(self):
        self.browser.close()
        self.playwright.stop()


def nueva_sesion(breakpoint: str, *, base_url: str = BASE_URL_DEV) -> SesionQA:
    """Abre Chromium headless con el viewport del breakpoint pedido, y
    engancha listeners para capturar errores de consola (`page.on
    ("console")`) y respuestas HTTP con status >= 400 -- ambas cosas
    quedan en la `SesionQA` devuelta para que el agente las revise
    antes de reportar una página como "sin errores"."""
    if breakpoint not in BREAKPOINTS:
        raise ValueError(f"Breakpoint desconocido: {breakpoint!r}. Usá uno de {list(BREAKPOINTS)}")
    ancho, alto = BREAKPOINTS[breakpoint]

    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": ancho, "height": alto})
    page = context.new_page()

    sesion = SesionQA(page=page, browser=browser, playwright=p, breakpoint=breakpoint)

    page.on("console", lambda msg: (
        sesion.errores_consola.append(f"[{msg.type}] {msg.text}")
        if msg.type == "error" else None
    ))
    page.on("response", lambda resp: (
        sesion.respuestas_fallidas.append(f"{resp.status} {resp.url}")
        if resp.status >= 400 else None
    ))

    page.goto(base_url, wait_until="networkidle")
    return sesion


def login(sesion: SesionQA, usuario: str, clave: str) -> None:
    """Llena el form de `/login` y espera a que redirija. Pensado para
    las cuentas descartables que crea el agente vía `docker exec`, no
    para cuentas reales."""
    page = sesion.page
    page.fill('input[name="username"]', usuario)
    page.fill('input[name="password"]', clave)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")


def _frame_dashboard(sesion: SesionQA):
    """El Dashboard vive en un <iframe src="/vista/dashboard"> con
    altura FIJA (`calc(100vh - 60px)`, ver templates/dashboard.html) --
    la página EXTERIOR nunca desborda ni scrollea, todo el contenido
    real vive y scrollea DENTRO de ese iframe. Cualquier chequeo de
    overflow o captura "de toda la página" hecho sobre `sesion.page`
    directamente mide/captura el documento equivocado -- silenciosamente
    da falsos negativos (dice "sin overflow" cuando sí lo hay) o una
    captura idéntica al viewport (nunca el contenido completo). Esta
    función devuelve el Frame real si la página actual lo tiene
    embebido, o None si no (otras páginas del sitio no usan iframe)."""
    return next((f for f in sesion.page.frames if "/vista/dashboard" in f.url), None)


def hay_overflow_horizontal(sesion: SesionQA) -> bool:
    """True si el documento se desborda horizontalmente (obliga a hacer
    scroll lateral de TODO el contenido, no de una tabla en particular
    dentro de su propio contenedor) -- el bug responsive más común y
    más fácil de detectar sin ojo humano. Si la página actual es el
    Dashboard, chequea el documento REAL (dentro del iframe, ver
    `_frame_dashboard`) en vez de la página exterior, que nunca
    desborda por diseño."""
    doc = _frame_dashboard(sesion) or sesion.page
    return doc.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
    )


def capturar(sesion: SesionQA, carpeta: Path, nombre: str, *, full_page: bool = True) -> Path:
    """Guarda un PNG real en `carpeta/<breakpoint>_<nombre>.png` y
    devuelve la ruta -- esa ruta es la que después se lee con el tool
    `Read` (para juicio visual) y se embebe en el Excel con
    `crear_reporte_excel()`.

    Si la página actual es el Dashboard y pedís `full_page=True`, un
    screenshot de `sesion.page` NO sirve (ver `_frame_dashboard`): el
    iframe tiene altura fija, así que "toda la página exterior" es
    igual al viewport, nunca el contenido real. En ese caso capturamos
    directamente el contenedor de contenido (`.wrap`) dentro del
    iframe, que Playwright captura completo aunque no entre en el
    viewport ni haya scroll -- ese es el equivalente real de
    "full_page" para esta app."""
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{sesion.breakpoint}_{nombre}.png"
    frame = _frame_dashboard(sesion)
    if full_page and frame is not None:
        frame.locator(".wrap").screenshot(path=str(destino))
    else:
        sesion.page.screenshot(path=str(destino), full_page=full_page)
    return destino


@dataclass
class Bug:
    """Un hallazgo para una fila del Excel. `severidad` esperado:
    'Crítico' | 'Alto' | 'Medio' | 'Bajo' | 'Cosmético' -- no inventes
    otros valores, así el Excel queda filtrable de forma consistente
    entre corridas."""
    resumen: str
    severidad: str
    pagina: str
    breakpoint: str
    pasos_para_reproducir: str  # numerados, un paso por línea: "1. ...\n2. ..."
    resultado_esperado: str
    resultado_observado: str
    captura: Path | None
    archivo_sugerido: str  # ej. "dashboard/dashboard_finanzas.html" o "N/A"
    agente_sugerido: str  # "frontend-dataviz" | "backend-engineer" | "N/A"


def crear_reporte_excel(bugs: list[Bug], destino: Path, *, corrida: str | None = None) -> Path:
    """Arma el .xlsx de la corrida con una fila por bug, capturas
    embebidas de verdad (no un link, la imagen adentro de la celda) y
    una columna "Estado" en blanco para que quien tome el bug (otro
    agente, o el usuario a mano) la vaya marcando -- este archivo es
    el punto de entrega/handoff, no se edita por código después de
    generado."""
    import openpyxl
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Font

    corrida = corrida or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bugs responsive"

    encabezados = [
        "ID", "Página", "Breakpoint", "Severidad", "Resumen",
        "Pasos para reproducir", "Resultado esperado", "Resultado observado",
        "Captura", "Archivo sugerido", "Agente sugerido", "Estado",
    ]
    ws.append(encabezados)
    for celda in ws[1]:
        celda.font = Font(bold=True)

    anchos = [6, 22, 11, 11, 28, 45, 30, 30, 34, 26, 18, 14]
    for i, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = ancho

    fila = 2
    for i, bug in enumerate(bugs, start=1):
        ws.cell(row=fila, column=1, value=i)
        ws.cell(row=fila, column=2, value=bug.pagina)
        ws.cell(row=fila, column=3, value=bug.breakpoint)
        ws.cell(row=fila, column=4, value=bug.severidad)
        ws.cell(row=fila, column=5, value=bug.resumen)
        ws.cell(row=fila, column=6, value=bug.pasos_para_reproducir)
        ws.cell(row=fila, column=7, value=bug.resultado_esperado)
        ws.cell(row=fila, column=8, value=bug.resultado_observado)
        ws.cell(row=fila, column=10, value=bug.archivo_sugerido)
        ws.cell(row=fila, column=11, value=bug.agente_sugerido)
        ws.cell(row=fila, column=12, value="Nuevo")

        for col in (6, 7, 8):
            ws.cell(row=fila, column=col).alignment = Alignment(wrap_text=True, vertical="top")

        if bug.captura and Path(bug.captura).exists():
            img = XLImage(str(bug.captura))
            img.width, img.height = 220, 160  # miniatura -- la imagen original en PNG queda intacta en qa_reports/
            ws.add_image(img, f"I{fila}")
            ws.row_dimensions[fila].height = 125
        fila += 1

    ws.freeze_panes = "A2"

    resumen = wb.create_sheet("Resumen de la corrida")
    resumen.append(["Fecha de la corrida", corrida])
    resumen.append(["Bugs encontrados", len(bugs)])
    for sev in ("Crítico", "Alto", "Medio", "Bajo", "Cosmético"):
        resumen.append([sev, sum(1 for b in bugs if b.severidad == sev)])

    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino
