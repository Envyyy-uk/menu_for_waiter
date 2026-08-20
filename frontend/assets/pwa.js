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
(function registerWorker() {
  if (!('serviceWorker' in navigator)) return;
  const tag = document.querySelector('script[data-sw]');
  if (!tag) return;
  const path = tag.getAttribute('data-sw');
  const scope = tag.getAttribute('data-scope') || '/';
  window.addEventListener('load', () => {
    navigator.serviceWorker.register(path, { scope }).catch(() => {
      /* без него приложение работает, просто не ставится на экран */
    });
  });
})();
