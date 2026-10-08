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
    if (e.request.mode === 'navigate') {
        e.respondWith(navigateOrRetryPage(e.request));
        return;
    }
    e.respondWith(fetch(e.request));
});

// Abrir una página sin cobertura (o con el servidor despertando) daba la
// pantalla de error de Chrome (ERR_FAILED) y había que recargar a mano. En
// su lugar: una página propia que reintenta sola cada pocos segundos y en
// cuanto vuelve la conexión. Lo pendiente de guardar sigue en el móvil.
const NAV_TIMEOUT_MS = 20000;

async function navigateOrRetryPage(request) {
    try {
        return await Promise.race([
            fetch(request),
            new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), NAV_TIMEOUT_MS)),
        ]);
    } catch (err) {
        return new Response(retryPageHtml(), {
            status: 503,
            headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'},
        });
    }
}

function retryPageHtml() {
    const en = !/^es/i.test((self.navigator && self.navigator.language) || 'es');
    const t = en
        ? {title: 'No connection', h: "Can't reach Gyre", p: 'Retrying automatically… Your unsaved sets stay on your phone and will be saved when the connection is back.', b: 'Retry now'}
        : {title: 'Sin conexión', h: 'No se puede conectar con Gyre', p: 'Reintentando solo… Las series sin guardar siguen en tu móvil y se guardarán al volver la conexión.', b: 'Reintentar ahora'};
    return `<!doctype html><html lang="${en ? 'en' : 'es'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>${t.title}</title>
<style>
:root{color-scheme:light dark;--bg:#f7f5ff;--fg:#1d1a2e;--muted:#6b6880;--accent:#7c4dff}
@media (prefers-color-scheme:dark){:root{--bg:#0f0d1a;--fg:#ece9ff;--muted:#a19dbb}}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,sans-serif;padding:24px;box-sizing:border-box;text-align:center}
main{max-width:340px}h1{font-size:1.25rem;margin:18px 0 8px}p{color:var(--muted);margin:0 0 22px}
.spin{width:34px;height:34px;margin:0 auto;border:3px solid rgba(124,77,255,.25);border-top-color:var(--accent);border-radius:50%;animation:s 0.9s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}
button{font:inherit;font-weight:700;border:0;border-radius:12px;padding:12px 20px;background:var(--accent);color:#fff}
</style></head><body><main><div class="spin" aria-hidden="true"></div><h1>${t.h}</h1><p>${t.p}</p>
<button type="button" onclick="location.reload()">${t.b}</button></main>
<script>
let wait = 3000;
function again(){ fetch('/healthz', {cache: 'no-store'}).then(r => { if (r.ok) location.reload(); else later(); }).catch(later); }
function later(){ setTimeout(again, wait); wait = Math.min(wait * 1.5, 15000); }
window.addEventListener('online', () => location.reload());
later();
</script></body></html>`;
}
self.addEventListener('notificationclick', (e) => {
    e.notification.close();
    e.waitUntil(self.clients.openWindow('/'));
});
