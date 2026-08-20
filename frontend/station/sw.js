/* ==========================================================================
   Service worker планшета станции.

   Он нужен ради двух вещей: программа ставится на домашний экран, и она
   открывается даже когда сеть моргнула. Данные при этом **не кэшируются
   никогда** — чек из кэша хуже пустого экрана: по нему примут решение,
   а он врёт.
   ========================================================================== */

const VERSION = 'stanciya-1';
const SHELL = [
  '/station/',
  '/assets/styles.css',
  '/assets/api.js',
  '/assets/auth.js',
  '/assets/live.js',
  '/assets/sound.js',
  '/assets/station.js',
  '/assets/pwa.js',
  '/assets/icons/station-192.png'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(names => Promise.all(names.filter(n => n !== VERSION).map(n => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  // Всё живое идёт только в сеть. Ответ сервера — единственный источник правды.
  if (url.pathname.startsWith('/api/') || url.pathname === '/ws') return;

  e.respondWith(
    fetch(e.request)
      .then(res => {
        // Свежая оболочка кладётся в кэш: следующий запуск без сети покажет
        // последнюю версию, а не ту, что была при установке.
        if (res.ok && url.origin === location.origin) {
          const copy = res.clone();
          caches.open(VERSION).then(c => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request).then(hit => hit || caches.match('/station/')))
  );
});
