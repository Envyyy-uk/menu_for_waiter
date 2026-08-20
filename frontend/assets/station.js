/* ==========================================================================
   Планшет бара и кухни.

   Экран стоит на полке и на него смотрят издалека, между делом. Отсюда всё
   устройство: крупные карточки, две кнопки, и ни одного места, где нужно
   что-то выбирать или искать. Марка пришла — её видно; взяли — цвет
   поменялся; отдали — она ушла.

   Потеря связи закрывает экран целиком. Тихий устаревший список хуже ошибки:
   по нему готовят то, что уже отменили, и не готовят то, что заказали.
   ========================================================================== */

// Сколько секунд марка может лежать не взятой, прежде чем начнёт кричать.
// То же число живёт на сервере (`late_ticket_seconds`) — там оно нужно для
// отчётов, здесь для того, чтобы карточка краснела без перезагрузки.
const LATE_SECONDS = 120;

const Board = {
  me: null,
  station: null,
  tickets: [],
  tick: null,

  async start(me) {
    this.me = me;
    document.getElementById('who').textContent = me.name;
    document.getElementById('out').addEventListener('click', () => Auth.logout());

    Live.on('ticket.new', d => this.arrived(d))
        .on('ticket.changed', () => this.refresh())
        .on('resync', () => this.refresh());
    Live.onLink = up => this.setLink(up);
    Live.start();

    await this.refresh();
    // Ожидание пересчитывается каждую секунду: «две минуты» на экране должны
    // означать две минуты, а не «столько было, когда пришёл заказ».
    this.tick = setInterval(() => this.paint(), 1000);

    // Экран не должен гаснуть посреди смены — до него не дотягиваются мокрой
    // рукой каждые полминуты.
    this.keepAwake();
  },

  async refresh() {
    try {
      const data = await API.get('/api/station/queue');
      this.station = data;
      this.tickets = data.tickets;
      document.getElementById('title').textContent = data.station_name;
      this.paint();
    } catch (e) {
      if (e.status === 401) location.reload();
    }
  },

  arrived(event) {
    // Новая марка — звук и вибрация: бармен смотрит на экран не всегда.
    Sound.arrived();
    this.refresh();
  },

  setLink(up) {
    document.getElementById('offline').hidden = up;
  },

  /* ------------------------------------------------------------ экран --- */
  paint() {
    const board = document.getElementById('board');
    const state = document.getElementById('state');
    board.innerHTML = '';

    if (!this.tickets.length) {
      board.appendChild(el('p', 'empty', 'Пусто. Новые заказы появятся сами.'));
      state.textContent = '';
      return;
    }

    const waiting = this.tickets.filter(t => t.status === 'new').length;
    state.textContent = waiting
      ? `${waiting} ${plural(waiting, 'новая', 'новых', 'новых')}`
      : `${this.tickets.length} в работе`;

    this.tickets.forEach(t => board.appendChild(this.mark(t)));
  },

  mark(ticket) {
    const waited = this.waitedFor(ticket);
    const late = ticket.status === 'new' && waited >= LATE_SECONDS;

    const node = el('div', `mark ${ticket.status}${late ? ' late' : ''}`);

    const head = el('div', 'mark-head');
    head.innerHTML = `
      <span class="table">${esc(ticket.table || '—')}</span>
      <span class="meta">
        чек №${ticket.check_number} · подача ${ticket.order_number}
        ${ticket.waiter ? '· ' + esc(ticket.waiter) : ''}
      </span>
      <span class="waited">${this.clock(waited)}</span>`;
    node.appendChild(head);

    const items = el('div', 'mark-items');
    ticket.items.forEach(i => {
      const row = el('div', 'mark-item');
      row.innerHTML = `
        <span class="n">${i.qty}×</span>
        <span class="what">
          <b>${esc(i.name)}</b>
          ${i.options.length ? `<span class="opts">${esc(i.options.join(' · '))}</span>` : ''}
          ${i.note ? `<span class="note">${esc(i.note)}</span>` : ''}
        </span>`;
      items.appendChild(row);
    });
    // Отменённое остаётся зачёркнутым: бармен уже мог начать делать, и об
    // отмене он должен узнать, а не догадаться по пустому столу.
    ticket.cancelled.forEach(i => {
      const row = el('div', 'mark-item gone');
      row.innerHTML = `
        <span class="n">${i.qty}×</span>
        <span class="what">
          <b>${esc(i.name)}</b>
          <span class="why">отменено</span>
        </span>`;
      items.appendChild(row);
    });
    node.appendChild(items);

    if (ticket.comment) {
      node.appendChild(el('div', 'mark-note', esc(ticket.comment)));
    }

    const foot = el('div', 'mark-foot');
    if (ticket.status === 'new') {
      foot.appendChild(this.button('Принял', 'accepted', ticket));
      foot.appendChild(this.button('Готово', 'ready', ticket, 'ok'));
    } else if (ticket.status === 'accepted') {
      foot.appendChild(this.button('Готово', 'ready', ticket, 'ok'));
    } else {
      // Готовое ждёт официанта. Убирает его он сам — тем же нажатием гасится
      // сигнал у него в телефоне.
      foot.appendChild(el('div', 'muted', 'Ждёт официанта'));
    }
    node.appendChild(foot);
    return node;
  },

  button(text, target, ticket, kind) {
    const b = el('button', 'btn big ' + (kind || ''), text);
    b.addEventListener('click', async () => {
      b.disabled = true;   // мокрый палец жмёт дважды
      buzz(20);
      try {
        await API.post(`/api/station/tickets/${ticket.id}/${target}`);
        await this.refresh();
      } catch (e) {
        toast(e.message, 'bad');
        b.disabled = false;
      }
    });
    return b;
  },

  waitedFor(ticket) {
    const from = ticket.sent_at ? new Date(ticket.sent_at).getTime() : Date.now();
    return Math.max(0, Math.floor((Date.now() - from) / 1000));
  },

  clock(seconds) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return m + ':' + String(s).padStart(2, '0');
  },

  async keepAwake() {
    if (!('wakeLock' in navigator)) return;
    const grab = async () => {
      try { await navigator.wakeLock.request('screen'); } catch (e) { /* откажут — ладно */ }
    };
    grab();
    document.addEventListener('visibilitychange', () => { if (!document.hidden) grab(); });
  }
};
