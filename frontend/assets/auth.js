/* ==========================================================================
   Вход по PIN.

   Экран перекрывает всё: пока человек не назвался, показывать нечего — ни
   столов, ни марок. Цифры не показываются даже ему самому: PIN вводят в зале,
   при гостях, и через плечо видно всё.

   Приложение зовёт `Auth.start(onReady)` и получает управление только после
   удачного входа.
   ========================================================================== */

const Auth = {
  me: null,
  onReady: null,
  pin: '',
  busy: false,
  // Ровно четыре цифры: набрал — и уже вошёл, без кнопки «войти».
  length: 4,

  async start(onReady) {
    this.onReady = onReady;
    try {
      this.me = await API.get('/api/auth/me');
      this.ready();
    } catch (e) {
      // 401 — просто ещё не вошли. Любая другая ошибка это тоже вход:
      // без имени работать всё равно нельзя.
      this.gate();
    }
  },

  ready() {
    const gate = document.getElementById('gate');
    if (gate) gate.remove();
    document.body.classList.remove('locked');
    if (this.onReady) this.onReady(this.me);
  },

  can(permission) {
    return !!(this.me && this.me.permissions.includes(permission));
  },

  async logout() {
    try { await API.post('/api/auth/logout'); } catch (e) { /* всё равно уходим */ }
    location.reload();
  },

  /* ------------------------------------------------------------ экран --- */
  gate() {
    if (document.getElementById('gate')) return;
    document.body.classList.add('locked');

    const gate = el('div', 'gate');
    gate.id = 'gate';
    gate.innerHTML = `
      <h1>Введите личный PIN</h1>
      <div class="dots" id="pin-dots"></div>
      <p class="msg" id="pin-msg"></p>
      <div class="pad" id="pin-pad"></div>`;
    document.body.appendChild(gate);

    const pad = gate.querySelector('#pin-pad');
    const keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'clear', '0', 'back'];
    keys.forEach(key => {
      const b = el('button', key === 'clear' || key === 'back' ? 'action' : '');
      b.type = 'button';
      b.textContent = key === 'clear' ? 'Сброс' : key === 'back' ? '←' : key;
      if (key === 'clear') b.setAttribute('aria-label', 'Сбросить ввод');
      if (key === 'back') b.setAttribute('aria-label', 'Стереть цифру');
      b.addEventListener('click', () => this.press(key));
      pad.appendChild(b);
    });

    // Планшет с клавиатурой и просто привычка — цифры вводятся и с неё.
    document.addEventListener('keydown', e => {
      if (!document.getElementById('gate')) return;
      if (e.key >= '0' && e.key <= '9') this.press(e.key);
      else if (e.key === 'Backspace') this.press('back');
      else if (e.key === 'Escape') this.press('clear');
      else if (e.key === 'Enter') this.submit();
    });

    this.paint();
  },

  press(key) {
    if (this.busy) return;
    const gate = document.getElementById('gate');
    if (gate) gate.classList.remove('wrong');
    this.message('');

    if (key === 'clear') this.pin = '';
    else if (key === 'back') this.pin = this.pin.slice(0, -1);
    else if (this.pin.length < this.length) this.pin += key;
    buzz();
    this.paint();

    // Набрал четыре — отправляем сами. Лишняя кнопка «войти» в зале это
    // лишнее нажатие пятьдесят раз за смену.
    if (this.pin.length === this.length) this.submit();
  },

  paint() {
    const dots = document.getElementById('pin-dots');
    if (!dots) return;
    dots.innerHTML = '';
    for (let i = 0; i < this.length; i++) {
      dots.appendChild(el('i', i < this.pin.length ? 'on' : ''));
    }
  },

  message(text) {
    const msg = document.getElementById('pin-msg');
    if (msg) msg.textContent = text || '';
  },

  async submit() {
    if (this.busy || this.pin.length !== this.length) return;
    this.busy = true;
    const pin = this.pin;
    try {
      this.me = await API.post('/api/auth/pin', { pin });
      this.pin = '';
      // Роль решает, какое приложение открывать. Официант, попавший на
      // планшет бара, должен увидеть свои столы, а не чужие марки.
      const home = this.me.home || '/';
      if (!location.pathname.startsWith(home) || (home === '/' && location.pathname !== '/')) {
        location.href = home;
        return;
      }
      this.ready();
    } catch (e) {
      this.pin = '';
      this.paint();
      this.message(e.message || 'Не получилось войти');
      const gate = document.getElementById('gate');
      if (gate) { gate.classList.add('wrong'); }
      buzz([40, 60, 40]);
    } finally {
      this.busy = false;
    }
  }
};
