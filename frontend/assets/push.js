/* ==========================================================================
   Подписка на push.

   Это второй уровень сигнала, не первый. Главный звук живёт в открытом
   приложении и идёт по медиаканалу — его слышно при выключенном звонке.
   Push нужен на случай, когда приложение свёрнуто, и он честно подчиняется
   настройкам телефона.

   Разрешение спрашивается **не при запуске**, а по кнопке. Системный вопрос,
   выскочивший в первую же секунду, учит нажимать «нет» — а второго раза
   браузер не даёт.
   ========================================================================== */

const Push = {
  key: null,
  enabled: false,

  async init() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
    try {
      const info = await API.get('/api/push/key');
      this.enabled = info.enabled;
      this.key = info.public_key;
    } catch (e) { return; }
    if (!this.enabled) return;

    // Разрешение уже дано в прошлую смену — молча обновляем подписку:
    // endpoint протухает, и без обновления push однажды перестаёт доходить.
    if (Notification.permission === 'granted') this.subscribe();
  },

  /** Нужна ли кнопка «включить уведомления». */
  offer() {
    return this.enabled && 'Notification' in window && Notification.permission === 'default';
  },

  async ask() {
    if (!this.enabled) return false;
    let answer;
    try { answer = await Notification.requestPermission(); } catch (e) { return false; }
    if (answer !== 'granted') return false;
    return this.subscribe();
  },

  async subscribe() {
    try {
      const reg = await navigator.serviceWorker.ready;
      const existing = await reg.pushManager.getSubscription();
      const sub = existing || await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: this.toBytes(this.key)
      });
      const raw = sub.toJSON();
      await API.post('/api/push/subscribe', {
        endpoint: raw.endpoint,
        keys: { p256dh: raw.keys.p256dh, auth: raw.keys.auth }
      });
      return true;
    } catch (e) {
      return false;
    }
  },

  /** Ключ приходит в base64url, а браузеру нужен массив байтов. */
  toBytes(key) {
    const pad = '='.repeat((4 - key.length % 4) % 4);
    const base64 = (key + pad).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(base64);
    return Uint8Array.from(raw, c => c.charCodeAt(0));
  }
};
