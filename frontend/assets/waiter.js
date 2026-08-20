/* ==========================================================================
   Приложение официанта.

   Оно живёт в кармане и открывается на ходу, поэтому устроено вокруг двух
   вещей: крупная цель под палец и минимум шагов до отправки заказа.

   Экранов три — столы, чек, меню — и они складываются стопкой, как в
   телефоне: «назад» всегда возвращает туда, откуда пришёл.
   ========================================================================== */

const App = {
  me: null,
  menu: null,
  tables: [],
  check: null,
  waiting: [],
  view: 'tables',
  filter: { text: '', category: null },

  /* ------------------------------------------------------------ старт --- */
  async start(me) {
    this.me = me;
    document.getElementById('who').textContent = me.name;
    document.getElementById('out').addEventListener('click', () => Auth.logout());
    document.getElementById('back').addEventListener('click', () => this.back());

    try {
      this.menu = await API.get('/api/menu');
    } catch (e) {
      toast('Меню не загрузилось', 'bad');
    }

    Live.on('check.changed', () => this.refresh())
        .on('ticket.ready', d => this.onReady(d))
        .on('menu.state', () => this.reloadMenu())
        .on('resync', () => this.refresh(true));
    Live.onLink = up => { if (up) this.refresh(); };
    Live.start();
    Push.init();

    await this.refresh(true);
    this.go('tables');
  },

  /* ------------------------------------------------------- данные ------- */
  async refresh(full) {
    try {
      const jobs = [API.get('/api/tables'), API.get('/api/station/waiting')];
      if (this.check) jobs.push(API.get('/api/checks/' + this.check.id));
      const [tables, waiting, check] = await Promise.all(jobs);
      this.tables = tables;
      this.waiting = waiting;
      // Сигнал держится на состоянии, а не на событии: событие можно
      // пропустить, а список ждущих марок врать не умеет.
      Sound.pending(waiting.length);
      if (check) this.check = check;
      this.paint();
    } catch (e) {
      // Последнее известное состояние остаётся на экране: пустой список
      // хуже устаревшего, потому что по нему принимают решения.
      if (e.status === 401) location.reload();
      else if (full) toast('Нет связи с сервером', 'bad');
    }
  },

  async reloadMenu() {
    try { this.menu = await API.get('/api/menu'); } catch (e) { /* оставим старое */ }
    if (this.view === 'menu') this.paint();
  },

  /* ------------------------------------------------------- навигация ---- */
  go(view) {
    this.view = view;
    if (view === 'menu') this.filter = { text: '', category: null };
    this.paint();
    window.scrollTo(0, 0);
  },

  back() {
    if (this.view === 'menu') this.go('check');
    else if (this.view === 'check') { this.check = null; this.go('tables'); }
  },

  /* ---------------------------------------------------------- отрисовка - */
  paint() {
    const title = document.getElementById('title');
    const back = document.getElementById('back');
    back.hidden = this.view === 'tables';

    if (this.view === 'tables') title.textContent = 'Столы';
    else if (this.view === 'check' && this.check) {
      title.textContent = `Стол ${this.check.table} · чек ${this.check.number}`;
    } else if (this.view === 'menu') title.textContent = 'Меню';

    const root = document.getElementById('app');
    root.innerHTML = '';
    root.appendChild(this.readyBar());
    if (this.view === 'tables') root.appendChild(this.tablesView());
    else if (this.view === 'check') root.appendChild(this.checkView());
    else if (this.view === 'menu') root.appendChild(this.menuView());
    this.dock();
  },

  /* -------------------------------------------------------- «готово» ---- */
  /* Полоса липнет к верху экрана: её нельзя пролистать мимо. */
  readyBar() {
    const wrap = el('div', 'ready-bar');
    this.waiting.forEach(t => {
      const row = el('div', 'ready-item');
      row.innerHTML = `
        <div class="body">
          <div class="what">Готово · ${esc(t.station_name)}</div>
          <div class="where">Стол ${esc(t.table)} · ${t.items.length} поз. · ${esc(since(t.ready_at))}</div>
        </div>`;
      const take = el('button', 'btn ok', 'Забрал');
      take.addEventListener('click', () => this.take(t.id));
      row.appendChild(take);
      wrap.appendChild(row);
    });
    return wrap;
  },

  async take(ticketId) {
    buzz(20);
    try {
      await API.post(`/api/station/tickets/${ticketId}/served`);
      await this.refresh();
    } catch (e) { toast(e.message, 'bad'); }
  },

  onReady(data) {
    // Звонок сразу, не дожидаясь ответа сервера со списком: секунда задержки
    // здесь — это официант, который уже отвернулся.
    Sound.arm();
    toast(`Готово · ${data.station_name} · стол ${data.table}`, 'good');
    this.refresh();
  },

  /* ----------------------------------------------------------- столы ---- */
  tablesView() {
    const wrap = el('div', 'screen');
    wrap.appendChild(this.signalRow());
    const zones = {};
    this.tables.forEach(t => (zones[t.zone] = zones[t.zone] || []).push(t));

    Object.entries(zones).forEach(([zone, tables]) => {
      wrap.appendChild(el('div', 'zone-title', esc(zone)));
      const grid = el('div', 'tables');
      tables.forEach(t => grid.appendChild(this.tile(t)));
      wrap.appendChild(grid);
    });
    return wrap;
  },

  /* Разрешение на уведомления спрашивается по кнопке, а не при запуске:
     системный вопрос в первую же секунду учит нажимать «нет», а второго раза
     браузер не даёт. Рядом — проверка звука: убедиться, что телефон звонит,
     лучше в начале смены, чем в середине. */
  signalRow() {
    const row = el('div', 'signal');
    const test = el('button', 'btn ghost', 'Проверить звук');
    test.addEventListener('click', () => { Sound.unlock(); Sound.alert(); });
    row.appendChild(test);

    if (Push.offer()) {
      const ask = el('button', 'btn', 'Включить уведомления');
      ask.addEventListener('click', async () => {
        const ok = await Push.ask();
        toast(ok ? 'Уведомления включены' : 'Уведомления не включились', ok ? 'good' : 'bad');
        this.paint();
      });
      row.appendChild(ask);
    }
    return row;
  },

  tile(table) {
    const checks = table.checks;
    const sum = checks.reduce((n, c) => n + c.total_pence, 0);
    const mine = checks.some(c => c.mine);
    const busy = checks.length > 0;

    const node = el('button', 'tile' + (busy ? (mine ? ' busy mine' : ' busy other') : ''));
    node.type = 'button';

    const flags = checks.flatMap(c => {
      const marks = Object.values(c.stations || {});
      if (c.has_draft) marks.push('draft');
      return marks;
    });
    const seen = [...new Set(flags)];

    node.innerHTML = `
      <span class="num">${esc(table.label)}</span>
      <span class="meta">${busy
        ? esc(checks.map(c => c.waiter || '—').join(', ')) + ' · ' + esc(since(checks[0].opened_at))
        : table.seats + ' ' + plural(table.seats, 'место', 'места', 'мест')}</span>
      <span class="sum">${busy ? money(sum) : ''}</span>
      <span class="flags">${seen.map(f => `<i class="flag ${esc(f)}"></i>`).join('')}</span>`;

    node.addEventListener('click', () => this.tapTable(table));
    return node;
  },

  async tapTable(table) {
    if (table.checks.length === 0) return this.askGuests(table);
    if (table.checks.length === 1) return this.openCheck(table.checks[0].id);

    // Столов с двумя чеками в жизни хватает — компания разделилась, и
    // угадывать за официанта, какой из них он открывает, нельзя.
    Sheet.show(`Стол ${esc(table.label)}`, 'Открытые чеки', sheet => {
      table.checks.forEach(c => {
        const b = el('button', 'btn wide big', `Чек №${c.number} · ${money(c.total_pence)}`);
        b.addEventListener('click', () => { Sheet.hide(); this.openCheck(c.id); });
        sheet.appendChild(b);
        sheet.appendChild(el('div', '', '<div style="height:8px"></div>'));
      });
      const add = el('button', 'btn wide big primary', 'Новый чек');
      add.addEventListener('click', () => { Sheet.hide(); this.askGuests(table); });
      sheet.appendChild(add);
    });
  },

  askGuests(table) {
    let guests = 2;
    Sheet.show(`Стол ${esc(table.label)}`, 'Сколько гостей', sheet => {
      const row = el('div', 'stepper');
      const minus = el('button', '', '−');
      const value = el('span', 'n', String(guests));
      const plus = el('button', '', '+');
      minus.addEventListener('click', () => { guests = Math.max(1, guests - 1); value.textContent = guests; buzz(); });
      plus.addEventListener('click', () => { guests = Math.min(99, guests + 1); value.textContent = guests; buzz(); });
      row.append(minus, value, plus);
      sheet.appendChild(row);
      sheet.appendChild(el('div', '', '<div style="height:16px"></div>'));

      const ok = el('button', 'btn wide big primary', 'Открыть стол');
      ok.addEventListener('click', async () => {
        Sheet.hide();
        try {
          const check = await API.post('/api/checks', { table_id: table.id, guests });
          this.check = check;
          await this.refresh();
          this.go('menu');
        } catch (e) { toast(e.message, 'bad'); }
      });
      sheet.appendChild(ok);
    });
  },

  async openCheck(id) {
    try {
      this.check = await API.get('/api/checks/' + id);
      this.go('check');
    } catch (e) { toast(e.message, 'bad'); }
  },

  /* ------------------------------------------------------------- чек ---- */
  checkView() {
    const c = this.check;
    const wrap = el('div', 'screen');
    if (!c) return wrap;

    const head = el('div', 'muted');
    head.style.margin = '4px 4px 12px';
    head.innerHTML = `${c.guests} ${plural(c.guests, 'гость', 'гостя', 'гостей')}`
      + ` · открыт ${esc(since(c.opened_at))} назад`
      + (c.waiter ? ` · ${esc(c.waiter)}` : '')
      + (c.comment ? `<br><span style="color:var(--warn)">${esc(c.comment)}</span>` : '');
    wrap.appendChild(head);

    if (!c.items.length) {
      wrap.appendChild(el('p', 'faint', 'Пусто. Нажмите «Меню» и наберите заказ.'));
    } else {
      const lines = el('div', 'lines');
      c.items.forEach(i => lines.appendChild(this.line(i)));
      wrap.appendChild(lines);
    }

    const totals = el('div', 'totals');
    totals.innerHTML =
      `<div class="row"><span class="muted">Позиции</span><span>${money(c.subtotal_pence)}</span></div>`
      + (c.discount_pence ? `<div class="row off"><span>Скидка</span><span>−${money(c.discount_pence)}</span></div>` : '')
      + `<div class="row big"><span>Итого</span><span>${money(c.total_pence)}</span></div>`;
    wrap.appendChild(totals);

    return wrap;
  },

  line(item) {
    const state = item.status === 'cancelled' ? 'cancelled'
      : item.status === 'draft' ? 'draft' : '';
    const node = el('div', 'line ' + state);

    // Статус берётся у марки: пока бар не взялся, это «отправлено», и
    // официанту важно видеть именно это, а не «в работе».
    let badge = '';
    if (item.status === 'draft') badge = '<span class="pill draft">черновик</span>';
    else if (item.status === 'cancelled') badge = '<span class="pill">отменено</span>';
    else {
      const ticket = (this.check.orders || [])
        .flatMap(o => o.tickets)
        .find(t => t.id === item.ticket_id);
      const map = { new: ['new', 'отправлено'], accepted: ['accepted', 'готовят'],
                    ready: ['ready', 'готово'], served: ['', 'подано'] };
      const [cls, text] = map[ticket ? ticket.status : 'new'] || ['', ''];
      badge = `<span class="pill ${cls}">${text}</span>`;
    }

    node.innerHTML = `
      <span class="qty">${item.qty}×</span>
      <span class="body">
        <span class="name">${esc(item.name)}</span> ${badge}
        ${item.options.length ? `<div class="opts">${esc(item.options.join(' · '))}</div>` : ''}
        ${item.note ? `<div class="note">${esc(item.note)}</div>` : ''}
        ${item.cancel_reason ? `<div class="opts">причина: ${esc(item.cancel_reason)}</div>` : ''}
      </span>
      <span class="price">${money(item.total_pence)}</span>`;

    if (item.status !== 'cancelled') {
      node.addEventListener('click', () => this.lineMenu(item));
    }
    return node;
  },

  lineMenu(item) {
    const draft = item.status === 'draft';
    Sheet.show(esc(item.name), item.options.join(' · ') || '', sheet => {
      if (draft) {
        let qty = item.qty;
        const row = el('div', 'stepper');
        const minus = el('button', '', '−');
        const value = el('span', 'n', String(qty));
        const plus = el('button', '', '+');
        minus.addEventListener('click', () => { qty = Math.max(0, qty - 1); value.textContent = qty; buzz(); });
        plus.addEventListener('click', () => { qty = Math.min(99, qty + 1); value.textContent = qty; buzz(); });
        row.append(minus, value, plus);
        sheet.appendChild(row);
        sheet.appendChild(el('div', '', '<div style="height:14px"></div>'));

        const save = el('button', 'btn wide big primary', 'Сохранить');
        save.addEventListener('click', async () => {
          Sheet.hide();
          try {
            this.check = await API.patch(
              `/api/checks/${this.check.id}/items/${item.id}`, { qty });
            this.paint();
          } catch (e) { toast(e.message, 'bad'); }
        });
        sheet.appendChild(save);
        sheet.appendChild(el('div', '', '<div style="height:8px"></div>'));
      }

      const kill = el('button', 'btn wide big danger',
        draft ? 'Убрать из чека' : 'Отменить позицию');
      kill.addEventListener('click', () => {
        Sheet.hide();
        if (draft) return this.cancel(item, null);
        // Отправленное уже могли начать делать. Причина не формальность:
        // по ней потом разбираются со списанием.
        Sheet.show('Отменить позицию', 'Бар уже мог начать её делать', s => {
          const input = el('input', 'field');
          input.placeholder = 'Причина: гость передумал, ошибка…';
          s.appendChild(input);
          s.appendChild(el('div', '', '<div style="height:12px"></div>'));
          const go = el('button', 'btn wide big danger', 'Отменить');
          go.addEventListener('click', () => { Sheet.hide(); this.cancel(item, input.value); });
          s.appendChild(go);
        });
      });
      sheet.appendChild(kill);
    });
  },

  async cancel(item, reason) {
    try {
      this.check = await API.post(
        `/api/checks/${this.check.id}/items/${item.id}/cancel`, { reason });
      this.paint();
      this.refresh();
    } catch (e) { toast(e.message, 'bad'); }
  },

  /* ------------------------------------------------------------ меню ---- */
  menuView() {
    const wrap = el('div', 'screen');
    if (!this.menu) return wrap;

    const search = el('div', 'search');
    const input = el('input');
    input.type = 'search';
    input.placeholder = 'Найти позицию';
    input.value = this.filter.text;
    input.addEventListener('input', () => {
      this.filter.text = input.value;
      this.paintDishes(list);
    });
    search.appendChild(input);
    wrap.appendChild(search);

    const chips = el('div', 'chips');
    const all = el('button', 'chip' + (this.filter.category ? '' : ' on'), 'Всё');
    all.addEventListener('click', () => { this.filter.category = null; this.paint(); });
    chips.appendChild(all);
    this.menu.categories.forEach(cat => {
      const chip = el('button', 'chip' + (this.filter.category === cat.key ? ' on' : ''), esc(cat.name));
      chip.addEventListener('click', () => { this.filter.category = cat.key; this.paint(); });
      chips.appendChild(chip);
    });
    wrap.appendChild(chips);

    const list = el('div', 'lines');
    wrap.appendChild(list);
    this.paintDishes(list);
    return wrap;
  },

  paintDishes(list) {
    const text = this.filter.text.trim().toLowerCase();
    const items = this.menu.items.filter(i => {
      if (this.filter.category && i.category !== this.filter.category) return false;
      if (!text) return true;
      // Названия английские, а ищет официант по-русски — поэтому в поиск
      // входят и русские слова из каталога.
      return i.name.toLowerCase().includes(text)
        || (i.description || '').toLowerCase().includes(text)
        || (i.search_terms || []).some(t => t.includes(text));
    });

    list.innerHTML = '';
    if (!items.length) {
      list.appendChild(el('p', 'faint', 'Ничего не нашлось'));
      return;
    }
    items.forEach(i => {
      const off = i.state === 'off';
      const node = el('button', 'dish' + (off ? ' off' : ''));
      node.type = 'button';
      node.innerHTML = `
        <span class="body">
          <span class="name">${esc(i.name)}</span>
          ${i.description ? `<span class="desc">${esc(i.description)}</span>` : ''}
        </span>
        <span class="price">${money(i.price_pence)}</span>`;
      node.addEventListener('click', () => {
        if (off) return toast(`«${i.name}» — стоп`, 'bad');
        this.pick(i);
      });
      list.appendChild(node);
    });
  },

  /* Позиция без вариантов добавляется одним нажатием — это половина меню,
     и лишний экран на ней стоил бы половины смены. */
  pick(item) {
    if (!(item.options || []).length) return this.add(item, {}, 1);
    Options.open(item, (chosen, qty) => this.add(item, chosen, qty));
  },

  async add(item, options, qty) {
    buzz(15);
    try {
      this.check = await API.post(`/api/checks/${this.check.id}/items`, {
        menu_item_id: item.id, qty, options
      });
      toast(`${item.name} · ${qty}×`, 'good');
      this.paint();
    } catch (e) {
      toast(e.message, 'bad');
    }
  },

  /* ---------------------------------------------------------- панель ---- */
  dock() {
    document.querySelectorAll('.dock').forEach(n => n.remove());
    if (this.view === 'tables') return;

    const dock = el('div', 'dock');
    if (this.view === 'menu') {
      const done = el('button', 'btn big primary wide', 'К чеку');
      done.addEventListener('click', () => this.go('check'));
      dock.appendChild(done);
    } else if (this.check) {
      const menu = el('button', 'btn big', 'Меню');
      menu.addEventListener('click', () => this.go('menu'));
      dock.appendChild(menu);

      if (this.check.has_draft) {
        const send = el('button', 'btn big primary', 'Отправить');
        send.addEventListener('click', () => this.send());
        dock.appendChild(send);
      } else if (this.check.items.length) {
        const pay = el('button', 'btn big ok', 'Оплата');
        pay.addEventListener('click', () => Pay.open(this.check));
        dock.appendChild(pay);
      }
    }
    document.body.appendChild(dock);
  },

  async send() {
    buzz(25);
    try {
      this.check = await API.post(`/api/checks/${this.check.id}/send`);
      toast('Отправлено на станции', 'good');
      this.paint();
      this.refresh();
    } catch (e) { toast(e.message, 'bad'); }
  }
};
