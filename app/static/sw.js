// Estáticos versionados (/static/...?v=<fecha>): la URL cambia en cada deploy,
// así que su contenido nunca cambia -> caché primero, red si no está. Si la
// red falla (poca cobertura en el gimnasio, servidor despertando) se sirve la
// versión anterior del mismo archivo: una página con el CSS de ayer es mucho
// mejor que una página sin estilos. El HTML NO se cachea nunca (siempre a la
// red): mostraría datos viejos.
const STATIC_CACHE = 'gyre-static-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => {
    e.waitUntil((async () => {
        const keep = new Set([STATIC_CACHE]);
        for (const key of await caches.keys()) {
            if (!keep.has(key)) await caches.delete(key);
        }
        await self.clients.claim();
    })());
});

function isVersionedStatic(url) {
    return url.origin === self.location.origin
        && url.pathname.startsWith('/static/')
        && url.searchParams.has('v');
}

async function staticFirst(request) {
    const cache = await caches.open(STATIC_CACHE);
    const hit = await cache.match(request);
    if (hit) return hit;
    try {
        const response = await fetch(request);
        if (response.ok) {
            // Solo la última versión de cada archivo: se borran las demás
            // entradas de la misma ruta para que la caché no crezca sin fin.
            const path = new URL(request.url).pathname;
            for (const old of await cache.keys()) {
                if (new URL(old.url).pathname === path) await cache.delete(old);
            }
            await cache.put(request, response.clone());
        }
        return response;
    } catch (err) {
        const fallback = await cache.match(request, { ignoreSearch: true });
        if (fallback) return fallback;
        throw err;
    }
}

self.addEventListener('fetch', (e) => {
    // Solo interceptar GET -- interceptar POST/PUT/DELETE no aporta nada y en
    // Android (PWA instalada) puede hacer que el cuerpo de la petición no se
    // pueda reenviar de forma fiable, dejando la promesa colgada sin error
    // visible. Al no llamar a respondWith(), el navegador gestiona la
    // petición exactamente como si no hubiera service worker.
    if (e.request.method !== 'GET') return;
    const url = new URL(e.request.url);
    if (isVersionedStatic(url)) {
        e.respondWith(staticFirst(e.request));
        return;
    }
    e.respondWith(fetch(e.request));
});
self.addEventListener('notificationclick', (e) => {
    e.notification.close();
    e.waitUntil(self.clients.openWindow('/'));
});
