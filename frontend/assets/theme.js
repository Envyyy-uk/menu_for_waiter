/* ==========================================================================
   Бумага и ночь.

   Оформление одно — то же, что в печатном меню. Режима два, потому что свет
   в зале разный: днём и в подсобке читают с бумаги, вечером светлая заливка
   на весь экран светит соседнему столу и бьёт по глазам самому официанту.

   Выбор хранится на устройстве, а не на человеке: планшет бара стоит в одном
   свете всю смену, кто бы за ним ни работал.
   ========================================================================== */

const Theme = {
  KEY: 'pos-theme',
  MODES: ['paper', 'night'],

  saved() {
    try {
      const value = localStorage.getItem(this.KEY);
      return this.MODES.includes(value) ? value : null;
    } catch (e) { return null; }        // приватный режим
  },

  current() {
    return document.documentElement.dataset.theme === 'night' ? 'night' : 'paper';
  },

  apply(mode) {
    if (mode === 'night') document.documentElement.dataset.theme = 'night';
    else delete document.documentElement.dataset.theme;
    try { localStorage.setItem(this.KEY, mode); } catch (e) { /* ничего */ }
    // Полоса статуса на телефоне красится под шапку, а не под страницу:
    // шапка тут всегда цвета чернил.
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', mode === 'night' ? '#201c16' : '#1d1a16');
    this.label();
  },

  toggle() {
    this.apply(this.current() === 'night' ? 'paper' : 'night');
  },

  label() {
    const btn = document.getElementById('theme');
    if (!btn) return;
    const night = this.current() === 'night';
    btn.textContent = night ? 'День' : 'Ночь';
    // Именно title, а не aria-label: aria-label подменяет имя кнопки целиком,
    // и «Ночь» перестаёт быть тем, что видно и что читает голосовой доступ.
    btn.title = night ? 'Дневное оформление' : 'Ночное оформление';
  },

  start() {
    const btn = document.getElementById('theme');
    if (btn) btn.addEventListener('click', () => this.toggle());
    this.label();
  }
};

/* Режим ставится ещё до отрисовки — иначе на каждом запуске мигает белым.
   Тот же код продублирован строкой в <head> каждой страницы: до загрузки
   этого файла успевает пройти первый кадр. */
(function preset() {
  const saved = Theme.saved();
  if (saved) Theme.apply(saved);
})();
