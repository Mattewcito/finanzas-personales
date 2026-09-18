# -*- coding: utf-8 -*-
"""
Verificación automatizada del modal "Registrar movimiento" (2026-09-18).

POR QUÉ EXISTE ESTE ARCHIVO
===========================
`pytest` cubre el backend y no ve nada de esto: que Escape cierre el
diálogo, que el foco quede atrapado, que el desplegable de categorías se
ubique bien. Y el panel de navegador de Claude Code tampoco alcanza: manda
las teclas por CDP, lo que genera el `keydown` en el DOM pero NO el
"close request" del navegador, así que ahí Escape parece no funcionar
aunque el código esté bien -- y peor, invita a sacar conclusiones falsas
en las dos direcciones.

Playwright sí dispara el close request real. Con esto apareció un bug que
las dos vías anteriores dejaban pasar: el listener de `animationend` del
cierre quedaba enganchado cuando ganaba el temporizador de respaldo, y la
animación de APERTURA lo volvía a disparar -- el modal se abría y se
cerraba solo ~200 ms después. Se veía como "el botón no responde la
segunda vez".

CÓMO SE CORRE
=============
Necesita el contenedor dev arriba (puerto 5001) y una cuenta de prueba:

    docker compose up -d
    docker exec finanzas-app-dev python -c "
    import sys; sys.path.insert(0, '/app/src')
    import db_finanzas as db
    conn = db.conectar(); db.crear_esquema(conn)
    db.crear_usuario(conn, 'qa_modal', 'QaModal_2026!', 'usuario', 'QA Modal')
    conn.close()"
    python tools/qa/verificar_modal_registrar.py

Sale con código 1 si algo falla, así que sirve tal cual en CI o en un hook.
NUNCA corre contra prod (5002) ni toca cuentas reales.
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE_URL", "http://127.0.0.1:5001")
USUARIO = os.environ.get("QA_USUARIO", "qa_modal")
CLAVE = os.environ.get("QA_CLAVE", "QaModal_2026!")

if "5002" in BASE:
    sys.exit("Este script no corre contra prod. Solo dev (5001).")

resultados = []


def check(nombre, ok, detalle=""):
    resultados.append(ok)
    print(("  OK    " if ok else "  FALLA ") + nombre + (("  -- " + detalle) if detalle else ""))


def main():
    abierto = "document.getElementById('modalRegistrar').open"
    lista_cat = "document.getElementById('regCategoriaLista')"

    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pag = nav.new_page(viewport={"width": 1440, "height": 900})
        errores = []
        pag.on("pageerror", lambda e: errores.append(str(e)))

        pag.goto(BASE + "/login")
        pag.fill('input[name="username"]', USUARIO)
        pag.fill('input[name="password"]', CLAVE)
        pag.click('button[type="submit"]')
        pag.wait_for_load_state("networkidle")

        # -------------------------------------------------- abrir y cerrar
        pag.click("#ctaRegistrar")
        pag.wait_for_timeout(500)
        check("el CTA del menú abre el modal", pag.evaluate(abierto))
        check("el foco entra al primer campo",
              pag.evaluate("document.activeElement && document.activeElement.id") == "regFecha")

        pag.keyboard.press("Escape")
        pag.wait_for_timeout(700)
        check("Escape cierra el modal", not pag.evaluate(abierto))
        check("el body se desbloquea al cerrar",
              not pag.evaluate("document.body.classList.contains('modal-abierto')"))

        # Reabrir: el bug de 2026-09-18 moría acá -- el modal se abría y se
        # cerraba solo a los ~200 ms por un listener de animación colgado.
        pag.click("#ctaRegistrar")
        pag.wait_for_timeout(900)
        check("el CTA vuelve a abrirlo después de haberlo cerrado", pag.evaluate(abierto))

        # ------------------------------------------------- el foco no se va
        # Lo que importa NO es que el foco toque <body> -- eso pasa cuando
        # se va a la barra del navegador y es normal, el propio <dialog>
        # lo trae de vuelta al siguiente Tab. Lo que sería un bug es que
        # aterrice en algo de la página de ATRÁS, que showModal() deja
        # inerte: un menú o un botón del dashboard tras el velo.
        fuga, recorrido = "", []
        for _ in range(24):
            pag.keyboard.press("Tab")
            info = pag.evaluate("""(function(){
              var a = document.activeElement;
              if (!a) return {donde:'null'};
              return { donde: a.id || a.tagName,
                       enElModal: document.getElementById('modalRegistrar').contains(a),
                       enElFondo: !!(document.querySelector('.app-shell') || {}).contains &&
                                  document.querySelector('.app-shell').contains(a) };
            })()""")
            recorrido.append(info["donde"])
            if info.get("enElFondo"):
                fuga = info["donde"]
                break
        volvio = pag.evaluate("document.getElementById('modalRegistrar').contains(document.activeElement)")
        check("el foco nunca aterriza en la página de atrás", not fuga,
              ("se fue a " + fuga) if fuga else "")
        check("el foco vuelve al modal al seguir tabulando", volvio,
              "recorrido: " + " > ".join(recorrido[:14]))

        # ------------------------------------------------------ el combo
        pag.click("#regCategoria")
        pag.wait_for_timeout(400)
        check("el campo Categoría despliega sus sugerencias",
              not pag.evaluate(lista_cat + ".hidden"))

        geo = pag.evaluate("""(function(){
          var l = document.getElementById('regCategoriaLista');
          var i = document.getElementById('regCategoria');
          var d = document.getElementById('modalRegistrar');
          var rl = l.getBoundingClientRect(), ri = i.getBoundingClientRect(), rd = d.getBoundingClientRect();
          return { dx: Math.abs(rl.x - ri.x), dw: Math.abs(rl.width - ri.width),
                   dentro: rl.left >= rd.left - 1 && rl.right <= rd.right + 1 &&
                           rl.top >= rd.top - 1 && rl.bottom <= rd.bottom + 1 };
        })()""")
        check("el desplegable queda alineado con el campo", geo["dx"] < 2 and geo["dw"] < 2,
              "dx=%.1f dw=%.1f" % (geo["dx"], geo["dw"]))
        check("el desplegable no se sale del modal", geo["dentro"])

        # Escape acá cierra SOLO la lista: el modal tiene que seguir abierto.
        pag.keyboard.press("Escape")
        pag.wait_for_timeout(400)
        check("Escape cierra la lista y no el modal",
              pag.evaluate(lista_cat + ".hidden") and pag.evaluate(abierto))

        pag.keyboard.press("Escape")
        pag.wait_for_timeout(700)
        check("el segundo Escape sí cierra el modal", not pag.evaluate(abierto))

        # ---------------------------------------------- click en el fondo
        pag.click("#ctaRegistrar")
        pag.wait_for_timeout(600)
        pag.mouse.click(60, 60)
        pag.wait_for_timeout(700)
        check("un click en el fondo cierra el modal", not pag.evaluate(abierto))

        check("la página no tiró errores de JavaScript", not errores,
              "; ".join(errores[:2]))
        nav.close()

    fallas = resultados.count(False)
    print("\n%d/%d en verde" % (len(resultados) - fallas, len(resultados)))
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
