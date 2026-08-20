/* ==========================================================================
   Service worker приложения официанта.

   Он нужен ради двух вещей: программа ставится на домашний экран, и она
   открывается даже когда сеть моргнула. Данные при этом **не кэшируются
   никогда** — чек из кэша хуже пустого экрана: по нему примут решение,
   а он врёт.
   ========================================================================== */

const VERSION = 'zal-1';
const SHELL = [
  '/',
  '/assets/styles.css',
  '/assets/api.js',
  '/assets/auth.js',
  '/assets/live.js',
  '/assets/sound.js',
  '/assets/sheets.js',
  '/assets/waiter.js',
  '/assets/pwa.js',
  '/assets/icons/waiter-192.png'
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
      .catch(() => caches.match(e.request).then(hit => hit || caches.match('/')))
  );
});

/* --------------------------------------------------------------------------
   Push: сигнал, когда приложение свёрнуто.

   `requireInteraction` держит уведомление на экране, пока его не тронут, —
   мигнувшая и исчезнувшая плашка это ровно тот пропущенный сигнал, из-за
   которого напиток стоит на баре.
   -------------------------------------------------------------------------- */
self.addEventListener('push', e => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch (err) { data = {}; }
  e.waitUntil(
    self.registration.showNotification(data.title || 'Готово', {
      body: data.body || '',
      tag: data.tag || 'ready',
      renotify: true,
      requireInteraction: true,
      vibrate: [220, 120, 220, 120, 320],
      icon: '/assets/icons/waiter-192.png',
      badge: '/assets/icons/waiter-192.png',
      data: { url: data.url || '/' }
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      // Уже открытое окно поднимаем, а не открываем второе: два экрана зала
      // на одном телефоне — это два разных представления о том, что готово.
      for (const client of list) {
        if (client.url.includes(self.location.origin)) return client.focus();
      }
      return self.clients.openWindow(url);
    })
  );
});
