# -*- coding: utf-8 -*-
"""
Verificación de la PWA (2026-09-18): que Chrome considere la app
INSTALABLE y que el service worker no guarde datos personales.

La instalabilidad no se verifica a ojo: se le pregunta a Chrome por el
protocolo de DevTools (`Page.getInstallabilityErrors`), que es exactamente
lo que usa para decidir si ofrece "Instalar app". Lista vacía = instalable.

El chequeo que más importa es el último: la app es multiusuario y maneja
plata, así que la caché del service worker NUNCA puede contener una
página ni una respuesta de /api/. Si la tuviera, en un celular compartido
una persona podría ver el resumen de otra.

    python tools/qa/verificar_pwa.py

Necesita el contenedor dev arriba y la cuenta `qa_modal` (ver
verificar_modal_registrar.py). Solo dev: se niega a correr contra 5002.
"""
import json
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
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        pag = ctx.new_page()
        errores = []
        pag.on("pageerror", lambda e: errores.append(str(e)))

        # ------------------------------------------------ manifest público
        r = pag.request.get(BASE + "/manifest.webmanifest")
        check("el manifest responde sin sesión", r.status == 200, "status %s" % r.status)
        check("el manifest tiene el mimetype correcto",
              "application/manifest+json" in r.headers.get("content-type", ""))
        man = json.loads(r.text())
        for campo in ("name", "short_name", "start_url", "display", "icons"):
            check("el manifest declara '%s'" % campo, campo in man)
        check("se abre a pantalla completa (display standalone)", man.get("display") == "standalone")
        for icono in man["icons"] + [i for s in man.get("shortcuts", []) for i in s.get("icons", [])]:
            ri = pag.request.get(BASE + icono["src"])
            check("el ícono %s existe" % icono["src"], ri.status == 200, "status %s" % ri.status)
        tiene_maskable = any("maskable" in i.get("purpose", "") for i in man["icons"])
        check("hay un ícono maskable (Android no le corta el dibujo)", tiene_maskable)
        atajos = {s["url"]: s["name"] for s in man.get("shortcuts", [])}
        check("el atajo 'Registrar gasto' apunta a /registrar", atajos.get("/registrar") == "Registrar gasto")

        # ------------------------------------------------ service worker
        r = pag.request.get(BASE + "/sw.js")
        check("el service worker responde sin sesión", r.status == 200, "status %s" % r.status)
        check("el service worker no se cachea (no-cache)",
              "no-cache" in r.headers.get("cache-control", ""))

        # ------------------------------------------------ entrar y registrar
        pag.goto(BASE + "/login")
        pag.fill('input[name="username"]', USUARIO)
        pag.fill('input[name="password"]', CLAVE)
        pag.click('button[type="submit"]')
        pag.wait_for_load_state("networkidle")
        pag.wait_for_function("navigator.serviceWorker && navigator.serviceWorker.controller !== undefined")
        listo = pag.evaluate("""navigator.serviceWorker.ready.then(function(r){
            return {scope: r.scope, activo: !!r.active};
        })""")
        check("el service worker se registra con alcance en toda la app",
              listo["scope"].rstrip("/") == BASE.rstrip("/") and listo["activo"],
              "scope=%s" % listo["scope"])

        # ------------------------------------------------ instalable según Chrome
        cdp = ctx.new_cdp_session(pag)
        instal = cdp.send("Page.getInstallabilityErrors")
        errs = [e.get("errorId") for e in instal.get("installabilityErrors", [])]
        check("Chrome la considera INSTALABLE", not errs, ", ".join(errs))

        # ------------------------------------------------ nada personal en caché
        # Navegar por varias páginas y pedir la API, y después revisar qué
        # quedó guardado en la caché del service worker.
        for ruta in ("/", "/tarjetas", "/registrar"):
            pag.goto(BASE + ruta)
            pag.wait_for_load_state("networkidle")
        pag.evaluate("fetch('/api/dashboard-data').then(function(r){return r.text()})")
        pag.wait_for_timeout(800)
        cacheado = pag.evaluate("""(async function(){
            var urls = [];
            for (const n of await caches.keys()) {
              const c = await caches.open(n);
              for (const req of await c.keys()) urls.push(new URL(req.url).pathname);
            }
            return urls;
        })()""")
        prohibidas = [u for u in cacheado if not u.startswith("/static/")]
        check("la caché solo tiene archivos estáticos, nunca páginas ni /api/",
              not prohibidas, "encontré: " + ", ".join(prohibidas[:5]))
        check("la pantalla sin conexión quedó precargada", "/static/pwa/offline.html" in cacheado)

        # ------------------------------------------------ sin red
        ctx.set_offline(True)
        pag.goto(BASE + "/", wait_until="domcontentloaded")
        texto = pag.inner_text("body")
        check("sin red muestra la pantalla de 'Sin conexión' y no un error del navegador",
              "Sin conexión" in texto)
        ctx.set_offline(False)

        check("la página no tiró errores de JavaScript", not errores, "; ".join(errores[:2]))
        nav.close()

    fallas = resultados.count(False)
    print("\n%d/%d en verde" % (len(resultados) - fallas, len(resultados)))
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
