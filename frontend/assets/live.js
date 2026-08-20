/* ==========================================================================
   Связь с сервером в реальном времени.

   Событие с сервера — это **повод перечитать**, а не само состояние. Получив
   его, экран запрашивает свой список целиком. Так же после обрыва: полная
   перезагрузка, а не доигрывание пропущенного. Доигрывание означало бы, что
   одно потерянное событие тихо оставляет экран устаревшим.

   Тишина — тоже сообщение. Сервер шлёт ping каждые три секунды; если ничего
   не приходит дольше десяти, связь считается потерянной и об этом видно.
   Молчащий сокет и рабочий сокет иначе выглядят одинаково.
   ========================================================================== */

const Live = {
  socket: null,
  lastMessage: 0,
  handlers: {},
  onLink: null,
  timer: null,
  retry: 0,
  online: false,

  SILENCE_MS: 10000,

  on(type, fn) {
    (this.handlers[type] = this.handlers[type] || []).push(fn);
    return this;
  },

  start() {
    this.connect();
    this.timer = setInterval(() => this.watch(), 1000);
    // Экран погас, приложение свернули — сокет мог умереть незаметно.
    // Возвращаемся на передний план: проверяем и перечитываем.
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) this.wake();
    });
    window.addEventListener('online', () => this.wake());
  },

  wake() {
    if (!this.socket || this.socket.readyState > 1) this.connect();
    this.emit('resync', {});
  },

  connect() {
    if (this.socket && this.socket.readyState <= 1) return;
    const url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
    let socket;
    try {
      socket = new WebSocket(url);
    } catch (e) {
      this.setLink(false);
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      this.retry = 0;
      this.lastMessage = Date.now();
      this.setLink(true);
      // Соединились заново — состояние могло уехать, пока нас не было.
      this.emit('resync', {});
    };
    socket.onmessage = e => {
      this.lastMessage = Date.now();
      this.setLink(true);
      let data;
      try { data = JSON.parse(e.data); } catch (err) { return; }
      if (data.type === 'ping' || data.type === 'hello') return;
      this.emit(data.type, data);
    };
    socket.onclose = e => {
      this.setLink(false);
      // 1008 — сессия не подтверждена. Не долбимся в закрытую дверь, а
      // показываем вход.
      if (e.code === 1008) { location.reload(); return; }
      this.retry = Math.min(this.retry + 1, 6);
      setTimeout(() => this.connect(), 500 * this.retry);
    };
    socket.onerror = () => this.setLink(false);
  },

  watch() {
    if (this.online && Date.now() - this.lastMessage > this.SILENCE_MS) {
      this.setLink(false);
      this.connect();
    }
  },

  setLink(up) {
    if (this.online === up) return;
    this.online = up;
    const dot = document.getElementById('link');
    if (dot) dot.classList.toggle('on', up);
    if (this.onLink) this.onLink(up);
  },

  emit(type, data) {
    (this.handlers[type] || []).forEach(fn => fn(data));
  }
};
