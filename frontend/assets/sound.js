/* ==========================================================================
   Сигнал «готово».

   Это главное обещание системы: бармен нажал «Готово» — официант услышал.
   Поэтому здесь три уровня, а не один, и каждый закрывает свою дыру.

   1. **Приложение открыто.** Звук идёт через <audio>, то есть по
      медиаканалу. Это ключевая деталь: на iPhone переключатель «без звука»
      глушит системные уведомления и Web Audio, но **не** глушит
      воспроизведение медиа — а с `navigator.audioSession.type = 'playback'`
      это поведение задаётся явно. На Android громкость медиа не зависит от
      режима «без звука» и вибрации. Отсюда правило: сигнал играет как
      музыка, а не как уведомление.

   2. **Сигнал повторяется, пока официант не подтвердил.** Пропущенное
      уведомление хуже лишнего: гость сидит, напиток греется, и никто не
      виноват. Экран при этом держится включённым.

   3. **Приложение свёрнуто.** Тогда доходит push — это уже системное
      уведомление, и его громкость подчиняется настройкам телефона. Честно:
      беззвучный режим здесь звук выключит, и обойти это из браузера нельзя.
      Поэтому уровень 1 — основной, а push — страховка.

   Звук нельзя запустить, пока человек не коснулся экрана: так устроены все
   браузеры. Поэтому на первом же касании мы «прогреваем» дорожки тишиной —
   дальше они играют по команде.
   ========================================================================== */

const Sound = {
  tracks: {},
  unlocked: false,
  timer: null,
  count: 0,
  lock: null,

  REPEAT_MS: 4000,

  /* ------------------------------------------------------------ подготовка */
  init() {
    this.tracks = {
      ready: this.track('/assets/sound/ready.wav'),
      arrived: this.track('/assets/sound/arrived.wav'),
      silence: this.track('/assets/sound/silence.wav')
    };
    // Явно объявляем звук воспроизведением, а не уведомлением. На iOS 16.4+
    // это и есть та настройка, из-за которой сигнал слышно при выключенном
    // звонке.
    try {
      if (navigator.audioSession) navigator.audioSession.type = 'playback';
    } catch (e) { /* нет такой возможности — работаем без неё */ }

    const wake = () => this.unlock();
    ['pointerdown', 'touchstart', 'keydown'].forEach(type =>
      document.addEventListener(type, wake, { once: true, passive: true }));
  },

  track(src) {
    const audio = new Audio(src);
    audio.preload = 'auto';
    audio.volume = 1;
    return audio;
  },

  /** Первое касание экрана разрешает звук. Проигрываем тишину — дальше
      настоящий сигнал уже не упрётся в политику автозапуска. */
  unlock() {
    if (this.unlocked) return;
    this.unlocked = true;
    Object.values(this.tracks).forEach(a => {
      const probe = a.cloneNode();
      probe.volume = 0;
      const done = probe.play();
      if (done && done.catch) done.catch(() => { this.unlocked = false; });
    });
  },

  play(name) {
    const source = this.tracks[name];
    if (!source) return;
    // Копия на каждое проигрывание: два сигнала подряд не должны обрывать
    // друг друга на середине.
    const audio = source.cloneNode();
    audio.volume = 1;
    const done = audio.play();
    if (done && done.catch) done.catch(() => { /* браузер ещё не разрешил */ });
  },

  /* --------------------------------------------------------- «готово» ---- */
  /** Сколько марок ждёт официанта. Ноль — тишина, больше нуля — сигнал
      повторяется, пока он их не заберёт. */
  pending(count) {
    this.count = count;
    if (count > 0) this.arm();
    else this.stop();
  },

  /** Начать звонить. Если уже звоним — ничего не делаем: вторая готовая
      марка не должна бить поверх первой, звонок и так не прекращался. */
  arm() {
    if (this.timer) return;
    this.alert();
    this.timer = setInterval(() => this.alert(), this.REPEAT_MS);
    this.keepAwake(true);
  },

  alert() {
    this.play('ready');
    buzz([220, 120, 220, 120, 320]);
  },

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.keepAwake(false);
  },

  /** Пока сигнал висит, экран не гаснет: телефон в кармане с погашенным
      экраном — это ровно тот случай, когда сигнал теряется. */
  async keepAwake(on) {
    if (!('wakeLock' in navigator)) return;
    if (!on) {
      if (this.lock) { try { await this.lock.release(); } catch (e) { /* уже нет */ } }
      this.lock = null;
      return;
    }
    try { this.lock = await navigator.wakeLock.request('screen'); } catch (e) { /* откажут — ладно */ }
  },

  /* --------------------------------------------------------- станция ----- */
  arrived() {
    this.play('arrived');
    buzz([60, 50, 60]);
  }
};

Sound.init();
