# -*- coding: utf-8 -*-
"""
Genera los íconos PNG de la PWA a partir del logo SVG de la marca.

Por qué un script y no PNGs hechos a mano: el logo vive como SVG
(src/static/brand/favicon.svg) y los íconos de una PWA tienen que ser
PNG en tamaños fijos. Si la marca cambia, se corre esto de nuevo y
listo. Renderiza con el Chromium de Playwright -- gratis y ya instalado
para QA -- en vez de cairosvg, que en Windows necesita librerías nativas.

    python tools/generar_iconos_pwa.py

Tres variantes, porque cada plataforma recorta distinto:
- "any" (192, 512): el cuadrado redondeado con las esquinas transparentes,
  tal cual el favicon. Android lo muestra así.
- "maskable" (512): Android le aplica su PROPIA máscara (círculo, gota,
  cuadrado según el fabricante). Tiene que ser a sangre completa y con el
  dibujo dentro de la zona segura del 80% central, o la máscara le corta
  el tilde.
- apple-touch-icon (180): iOS redondea las esquinas por su cuenta y pinta
  de negro cualquier transparencia, así que va cuadrado y sin alfa.
"""
import pathlib

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "src" / "static" / "pwa"
MARCA = "#3845D1"   # --brand en tokens.css

# El tilde del logo, en coordenadas del viewBox 32x32 original.
TILDE = '<path d="M8 16.5 L13 21.5 L24 11" stroke="white" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'


def svg_redondeado(lado):
    """El favicon tal cual: cuadrado con rx=10 (sobre 32), esquinas transparentes."""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="{lado}" height="{lado}">
      <rect width="32" height="32" rx="10" fill="{MARCA}"/>{TILDE}</svg>'''


def svg_a_sangre(lado, escala):
    """Fondo de marca a sangre completa, tilde centrado y escalado.
    escala < 1 achica el dibujo hacia el centro (zona segura)."""
    desplazamiento = 16 * (1 - escala)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="{lado}" height="{lado}">
      <rect width="32" height="32" fill="{MARCA}"/>
      <g transform="translate({desplazamiento} {desplazamiento}) scale({escala})">{TILDE}</g></svg>'''


ICONOS = [
    # (archivo, lado, svg, fondo_transparente)
    ("icono-192.png", 192, svg_redondeado(192), True),
    ("icono-512.png", 512, svg_redondeado(512), True),
    # 0.8: todo el tilde cae dentro del círculo de la zona segura.
    ("icono-maskable-512.png", 512, svg_a_sangre(512, 0.8), False),
    # 0.9: iOS recorta menos que Android, el tilde puede ser más grande.
    ("apple-touch-icon.png", 180, svg_a_sangre(180, 0.9), False),
    # Ícono del atajo "Registrar gasto": un "+" en vez del tilde.
    ("atajo-registrar-96.png", 96,
     f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="96" height="96">
       <rect width="32" height="32" rx="10" fill="{MARCA}"/>
       <path d="M16 9 V23 M9 16 H23" stroke="white" stroke-width="2.8" stroke-linecap="round" fill="none"/></svg>''',
     True),
]


def main():
    DESTINO.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        for archivo, lado, svg, transparente in ICONOS:
            pag = nav.new_page(viewport={"width": lado, "height": lado}, device_scale_factor=1)
            fondo = "transparent" if transparente else MARCA
            pag.set_content(
                f'<html><body style="margin:0;background:{fondo}">{svg}</body></html>'
            )
            pag.locator("svg").screenshot(path=str(DESTINO / archivo), omit_background=transparente)
            pag.close()
            print("  generado:", archivo, f"({lado}x{lado})")
        nav.close()


if __name__ == "__main__":
    main()
