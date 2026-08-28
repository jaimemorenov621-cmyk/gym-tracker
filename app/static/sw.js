self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
    // Solo interceptar GET -- este service worker no cachea nada, solo
    // reenvía la petición tal cual, así que interceptar POST/PUT/DELETE no
    // aporta nada y en Android (PWA instalada) puede hacer que el cuerpo de
    // la petición no se pueda reenviar de forma fiable, dejando la promesa
    // colgada sin error visible. Al no llamar a respondWith(), el navegador
    // gestiona la petición exactamente como si no hubiera service worker.
    if (e.request.method !== 'GET') return;
    e.respondWith(fetch(e.request));
});
self.addEventListener('notificationclick', (e) => {
    e.notification.close();
    e.waitUntil(self.clients.openWindow('/'));
});
