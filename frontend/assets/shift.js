/* ==========================================================================
   Смена планшета станции.

   Планшет живёт отдельно от личных входов: он стоит на полке, к нему подходят
   все по очереди, и требовать личный PIN на каждую марку — значит не получить
   ни одного нажатия. Поэтому у планшета свой PIN, и вводят его дважды за
   вечер: когда смену открывают и когда закрывают.

   Станцию при этом не спрашивают. Планшет бара и планшет кухни отличаются как
   раз PIN-ом, а лишний экран выбора — это лишний способ открыть чужую смену.
   ========================================================================== */

const Shift = {
  state: null,
  onOpen: null,

  async start(onOpen) {
    this.onOpen = onOpen;
    try {
      this.state = await API.get('/api/station/shift');
    } catch (e) {
      this.state = { open: false, configured: true };
    }
    if (this.state.open) this.onOpen(this.state);
    else this.gate();
  },

  gate() {
    this.ask('Смена не открыта', this.state.configured
      ? 'Введите PIN станции'
      : 'PIN станции ещё не задан — это делается в админке',
      async pin => {
        const opened = await API.post('/api/station/shift/open', { pin });
        this.state = opened;
        const gate = document.getElementById('gate');
        if (gate) gate.remove();
        document.body.classList.remove('locked');
        this.onOpen(opened);
      }, { keep: true });
  },

  /** Экран ввода PIN станции. `keep` — не закрывается по фону: пока смена не
      открыта, показывать всё равно нечего. */
  ask(title, hint, submit, options) {
    const keep = !!(options && options.keep);
    document.querySelectorAll('#gate').forEach(n => n.remove());
    document.body.classList.add('locked');

    let pin = '';
    let busy = false;

    const gate = el('div', 'gate');
    gate.id = 'gate';
    gate.innerHTML = `
      <h1>${esc(title)}</h1>
      <div class="dots" id="pin-dots"></div>
      <p class="msg" id="pin-msg">${esc(hint)}</p>
      <div class="pad" id="pin-pad"></div>`;
    if (!keep) {
      const back = el('button', 'btn ghost', 'Отмена');
      back.addEventListener('click', () => {
        gate.remove();
        document.body.classList.remove('locked');
      });
      gate.appendChild(back);
    }
    document.body.appendChild(gate);

    const dots = gate.querySelector('#pin-dots');
    const msg = gate.querySelector('#pin-msg');
    const paint = () => {
      dots.innerHTML = '';
      for (let i = 0; i < 4; i++) dots.appendChild(el('i', i < pin.length ? 'on' : ''));
    };

    const send = async () => {
      if (busy) return;
      busy = true;
      try {
        await submit(pin);
      } catch (e) {
        pin = '';
        paint();
        msg.textContent = e.message || 'Не получилось';
        gate.classList.add('wrong');
        setTimeout(() => gate.classList.remove('wrong'), 400);
        buzz([40, 60, 40]);
      } finally {
        busy = false;
      }
    };

    const pad = gate.querySelector('#pin-pad');
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'clear', '0', 'back'].forEach(key => {
      const b = el('button', key === 'clear' || key === 'back' ? 'action' : '');
      b.type = 'button';
      b.textContent = key === 'clear' ? 'Сброс' : key === 'back' ? '←' : key;
      b.addEventListener('click', () => {
        if (busy) return;
        if (key === 'clear') pin = '';
        else if (key === 'back') pin = pin.slice(0, -1);
        else if (pin.length < 4) pin += key;
        buzz();
        paint();
        if (pin.length === 4) send();
      });
      pad.appendChild(b);
    });

    paint();
  },

  /** Смена закрыта — показываем итог и возвращаем экран PIN. */
  done(text) {
    document.querySelectorAll('.toast').forEach(n => n.remove());
    toast(text, 'good');
    setTimeout(() => location.reload(), 1800);
  }
};
