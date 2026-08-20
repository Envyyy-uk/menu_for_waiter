/* ==========================================================================
   Сигнал «готово».

   Пока — простой звук через Web Audio. В спринте 6 он заменяется на такой,
   который пробивается сквозь выключенный звонок телефона, повторяется, пока
   официант не подтвердил, и доходит push-ом, когда приложение свёрнуто.
   ========================================================================== */

const Sound = {
  ctx: null,

  unlock() {
    // Звук на телефоне разрешается только после касания экрана — поэтому
    // контекст создаётся на первом же нажатии, а не при загрузке.
    if (this.ctx) return;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    this.ctx = new Ctx();
    if (this.ctx.state === 'suspended') this.ctx.resume();
  },

  alert() {
    this.unlock();
    buzz([120, 80, 120]);
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    [0, 0.28].forEach(offset => {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.5, now + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.22);
      osc.connect(gain).connect(this.ctx.destination);
      osc.start(now + offset);
      osc.stop(now + offset + 0.24);
    });
  },

  /** Новая марка на станции — короткий двойной сигнал. */
  arrived() {
    this.unlock();
    buzz([60, 50, 60]);
    this.beep(660, 0);
    this.beep(660, 0.18);
  },

  beep(hz, offset) {
    if (!this.ctx) return;
    const now = this.ctx.currentTime + offset;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = hz;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.5, now + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.2);
    osc.connect(gain).connect(this.ctx.destination);
    osc.start(now);
    osc.stop(now + 0.22);
  },

  stop() { /* повтор сигнала появится в спринте 6 */ }
};

document.addEventListener('pointerdown', () => Sound.unlock(), { once: true });
