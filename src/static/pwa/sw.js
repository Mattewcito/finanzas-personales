/* Service worker de Cuadre (PWA, 2026-09-18).
 *
 * Qué hace: permite instalar la app en la pantalla de inicio, sirve los
 * archivos estáticos (estilos, fuentes, íconos) desde caché para que
 * abra rápido, y muestra una pantalla de "sin conexión" en vez del error
 * del navegador cuando no hay señal.
 *
 * Qué NO hace, a propósito: NUNCA guarda en caché páginas HTML ni
 * respuestas de /api/. La app es multiusuario y maneja plata: si se
 * cachearan, en un dispositivo compartido la persona B podría ver el
 * resumen de la persona A después de un cambio de sesión, o cualquiera
 * vería números viejos creyendo que son actuales. Todo lo que tenga
 * datos va siempre a la red.
 *
 * Al cambiar cualquier archivo de PRECACHE, subir VERSION: eso crea una
 * caché nueva y el `activate` borra las viejas.
 */
const VERSION = 'cuadre-v1';
const OFFLINE = '/static/pwa/offline.html';

const PRECACHE = [
  OFFLINE,
  '/static/css/tokens.css',
  '/static/css/base.css',
  '/static/brand/favicon.svg',
  '/static/pwa/icono-192.png',
  '/static/fonts/inter-400.woff2',
  '/static/fonts/inter-500.woff2',
  '/static/fonts/inter-600.woff2',
  '/static/fonts/inter-700.woff2',
  '/static/fonts/plus-jakarta-sans-600.woff2',
  '/static/fonts/plus-jakarta-sans-700.woff2',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(VERSION)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((nombres) => Promise.all(
        nombres.filter((n) => n !== VERSION).map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  // Solo GET del mismo origen. Un POST (registrar un gasto, guardar el
  // presupuesto) jamás pasa por la caché.
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Páginas (incluido el <iframe> del dashboard): siempre red. Si no hay
  // red, la pantalla de sin conexión -- nunca una copia vieja.
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE)));
    return;
  }

  // Estáticos: primero la caché (abre al instante) y en paralelo se
  // refresca desde la red para la próxima vez.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.open(VERSION).then((cache) =>
        cache.match(req).then((guardado) => {
          const deRed = fetch(req)
            .then((resp) => {
              if (resp.ok) cache.put(req, resp.clone());
              return resp;
            })
            .catch(() => guardado);
          return guardado || deRed;
        })
      )
    );
    return;
  }

  // Todo lo demás (incluido /api/*) no se toca: va directo a la red
  // como si el service worker no existiera.
});
