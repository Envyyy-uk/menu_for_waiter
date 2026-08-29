/* ==========================================================================
   Поведінка в режимі застосунку (PWA)

   Подвійний тап вимкнено скрізь одним рядком CSS — `touch-action: manipulation`
   на `html`. Він прибирає саме зум по подвійному тапу, а прокрутку й пінч
   лишає, тож у звичайному браузері нічого не втрачається.

   Свідомо без перехоплення `touchend`: воно гасить не лише зум, а й другий
   тап поспіль по сусідній кнопці — на цьому вже ламалося перемикання розділів.
   ========================================================================== */

(function lockZoomInStandalone() {
  const standalone =
    (window.matchMedia && (window.matchMedia('(display-mode: standalone)').matches ||
                           window.matchMedia('(display-mode: fullscreen)').matches ||
                           window.matchMedia('(display-mode: minimal-ui)').matches)) ||
    window.navigator.standalone === true;

  if (!standalone) return;

  document.documentElement.classList.add('pwa');

  const vp = document.querySelector('meta[name="viewport"]');
  if (vp) {
    vp.setAttribute('content',
      'width=device-width, initial-scale=1, minimum-scale=1, maximum-scale=1, ' +
      'user-scalable=no, viewport-fit=cover');
  }

  // Safari на iOS ігнорує user-scalable у частині версій — гасимо жести напряму.
  // У браузері пінч лишається навмисно: комусь це єдиний спосіб прочитати склад.
  ['gesturestart', 'gesturechange', 'gestureend'].forEach(type =>
    document.addEventListener(type, e => e.preventDefault(), { passive: false }));

  document.addEventListener('dblclick', e => e.preventDefault(), { passive: false });
})();

/* --------------------------------------------------------------------------
   Регистрация service worker.

   Он нужен, чтобы приложение ставилось на домашний экран и открывалось при
   моргнувшей сети. Путь берётся из атрибута на теге <script>, потому что у
   зала и станции разные области видимости.
   -------------------------------------------------------------------------- */
const PWA = {
  registration: null,

  /* Обновиться прямо сейчас.

     Приложение, поставленное на домашний экран, живёт неделями: браузерной
     кнопки перезагрузки в нём нет, и поправка доезжает до официанта только
     после того, как он догадается снести значок и поставить заново. Кнопка
     нужна именно поэтому.

     Кэш чистится весь: иначе оболочка останется прежней и «обновление»
     ничего не изменит. Приложение в этот момент онлайн — оно только что
     узнало о новой версии, — так что терять нечего. */
  async refresh() {
    try {
      if ('serviceWorker' in navigator) {
        const regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map(r => r.update().catch(() => {})));
      }
      if (window.caches) {
        const names = await caches.keys();
        await Promise.all(names.map(n => caches.delete(n)));
      }
    } catch (e) {
      /* Не вышло почистить — перезагрузка всё равно полезнее отказа. */
    }
    location.reload();
  },

  /* Сказать, что вышла новая версия. Не перезагружаем сами: официант может
     стоять с открытым чеком, и терять набранное ради свежего шрифта — плохой
     размен. */
  announce() {
    if (document.getElementById('update-bar')) return;
    const bar = el('div', 'update-bar');
    bar.id = 'update-bar';
    bar.innerHTML = '<span>Вышло обновление</span>';
    const go = el('button', 'btn ok', 'Обновить');
    go.addEventListener('click', () => this.refresh());
    const later = el('button', 'btn ghost', 'Потом');
    later.addEventListener('click', () => bar.remove());
    bar.append(go, later);
    document.body.appendChild(bar);
  },

  watch(reg) {
    this.registration = reg;
    if (!reg) return;

    const offer = worker => {
      if (!worker) return;
      worker.addEventListener('statechange', () => {
        // `controller` есть — значит приложение уже работало на прошлой
        // версии. При самой первой установке говорить не о чем.
        if (worker.state === 'installed' && navigator.serviceWorker.controller) {
          this.announce();
        }
      });
    };
    offer(reg.installing);
    reg.addEventListener('updatefound', () => offer(reg.installing));

    // Проверяем не по таймеру в фоне, а когда экран вернулся к человеку:
    // телефон официанта лежит в кармане часами, и опрос оттуда — это трафик
    // и батарея ни за чем.
    const look = () => { if (!document.hidden) reg.update().catch(() => {}); };
    document.addEventListener('visibilitychange', look);
    setInterval(look, 30 * 60 * 1000);
  }
};

(function registerWorker() {
  if (!('serviceWorker' in navigator)) return;
  const tag = document.querySelector('script[data-sw]');
  if (!tag) return;
  const path = tag.getAttribute('data-sw');
  const scope = tag.getAttribute('data-scope') || '/';
  window.addEventListener('load', () => {
    navigator.serviceWorker.register(path, { scope })
      .then(reg => PWA.watch(reg))
      .catch(() => {
        /* без него приложение работает, просто не ставится на экран */
      });
  });
})();
