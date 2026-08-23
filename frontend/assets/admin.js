/* ==========================================================================
   Админка: смена, персонал, столы, меню, журнал.

   Её открывают в подсобке, а не на бегу, поэтому здесь допустимы таблицы.
   Недопустимо другое: чтобы что-то менялось молча. Всё, что двигает деньги
   или доступ, попадает в журнал, и журнал открыт из того же окна.
   ========================================================================== */

/* Роли и длина PIN. В зале четыре цифры, в админке шесть: оттуда правят
   цены, роли, склад и видно все оплаты, а четыре цифры это всего десять
   тысяч вариантов. Сервер считает так же — здесь только подсказка. */
const ROLE_LIST = [
  ['waiter', 'Официант'], ['bar', 'Бармен'], ['kitchen', 'Кухня'],
  ['manager', 'Менеджер'], ['admin', 'Администратор'], ['owner', 'Владелец']
];
const ADMIN_ROLES = ['owner', 'admin', 'manager'];
const pinLength = role => (ADMIN_ROLES.includes(role) ? 6 : 4);
const digits = n => (n === 4 ? '4 цифры' : n + ' цифр');

const Admin = {
  me: null,
  tab: 'report',
  zone: 'Зал',
  hours: 24,
  days: 30,
  data: {},

  TABS: [
    { key: 'report', name: 'Смена', need: 'reports' },
    { key: 'payments', name: 'Оплаты', need: 'payments.view' },
    { key: 'timesheet', name: 'Табель', need: 'timesheet.view' },
    { key: 'users', name: 'Персонал', need: 'users.view' },
    { key: 'tables', name: 'Столы', need: 'tables.manage' },
    { key: 'stations', name: 'Станции', need: 'stations.manage' },
    { key: 'menu', name: 'Меню', need: 'items.edit' },
    { key: 'stock', name: 'Склад', need: 'stock.view' },
    { key: 'inventory', name: 'Инвентаризация', need: 'stock.view' },
    { key: 'audit', name: 'Журнал', need: 'audit.view' }
  ],

  async start(me) {
    this.me = me;
    document.getElementById('who').textContent = me.name + ' · ' + me.role_name;
    document.getElementById('out').addEventListener('click', () => Auth.logout());

    // Менеджер и администратор работают в зале так же, как официант: скидку
    // и отмену позиции они дают у стола, а не из подсобки. Вход у них один —
    // через админку, поэтому дорога в зал должна быть отсюда.
    if (Auth.can('checks.edit')) document.getElementById('hall').hidden = false;

    const allowed = this.TABS.filter(t => Auth.can(t.need));
    if (!allowed.length) {
      document.getElementById('app').innerHTML =
        '<div class="panel"><p class="hint">Для этой роли админка пуста.</p></div>';
      return;
    }
    this.tab = allowed[0].key;

    const bar = document.getElementById('tabs');
    allowed.forEach(t => {
      const b = el('button', 'tab', esc(t.name));
      b.dataset.key = t.key;
      b.addEventListener('click', () => this.go(t.key));
      bar.appendChild(b);
    });

    Live.on('check.changed', () => {
      if (this.tab === 'report' || this.tab === 'payments') this.load();
    });

    // Склад обновляется сам. Смысл экрана в том, чтобы видеть остаток
    // сейчас, а не тот, что был на момент открытия вкладки.
    Live.on('stock.changed', () => {
      if (this.tab === 'stock') this.load();
    });

    // А это уже новость: позиция ушла в «мало» или кончилась. Её говорят
    // вслух и там, где админ сейчас, а не только на вкладке склада.
    Live.on('stock.low', d => {
      toast(`${d.title}: ${d.body}`, 'bad', 6000);
      Sound.alert();
    });

    Live.on('menu.changed', () => { if (this.tab === 'menu') this.load(); });
    Live.on('menu.state', () => { if (this.tab === 'menu') this.load(); });
    Live.on('tables.changed', () => { if (this.tab === 'tables') this.load(); });
    Live.start();
    this.go(this.tab);
  },

  go(tab) {
    this.tab = tab;
    document.querySelectorAll('.tab').forEach(b => b.classList.toggle('on', b.dataset.key === tab));
    this.load();
  },

  async load() {
    const root = document.getElementById('app');
    try {
      if (this.tab === 'report') this.data.report = await API.get('/api/admin/report');
      if (this.tab === 'payments') {
        this.data.payments = await API.get('/api/admin/payments?hours=' + this.hours);
      }
      if (this.tab === 'timesheet') {
        this.data.timesheet = await API.get('/api/admin/timesheet?days=' + this.days);
      }
      if (this.tab === 'users') this.data.users = await API.get('/api/admin/users');
      if (this.tab === 'tables') this.data.tables = await API.get('/api/admin/tables');
      if (this.tab === 'stations') {
        this.data.stations = await API.get('/api/admin/stations');
        this.data.shifts = await API.get('/api/admin/shifts');
      }
      if (this.tab === 'menu') {
        this.data.menu = await API.get('/api/menu');
        this.data.sync = await API.get('/api/admin/menu/sync');
      }
      if (this.tab === 'stock') {
        this.data.stock = await API.get('/api/stock');
        this.data.recipes = await API.get('/api/stock/recipes');
        this.data.menu = await API.get('/api/menu');
      }
      if (this.tab === 'inventory') {
        this.data.inventory = await API.get(
          '/api/stock/inventory' + (this.month ? '?month=' + this.month : ''));
      }
      if (this.tab === 'audit') this.data.audit = await API.get('/api/admin/audit');
    } catch (e) {
      if (e.status === 401) return location.reload();
      toast(e.message, 'bad');
      return;
    }
    root.innerHTML = '';
    root.appendChild(this['view_' + this.tab]());
  },

  /* ---------------------------------------------------------- смена ----- */
  view_report() {
    const r = this.data.report;
    const wrap = el('div', 'panel');
    wrap.appendChild(el('h2', '', 'Смена'));
    wrap.appendChild(el('p', 'hint',
      'Последние сутки. Смена в баре кончается за полночь, поэтому «сегодня» '
      + 'здесь — это 24 часа назад, а не календарный день.'));

    const figures = el('div', 'figures');
    const put = (label, value, cls) => {
      const box = el('div', 'figure ' + (cls || ''));
      box.innerHTML = `<div class="label">${esc(label)}</div><div class="value">${value}</div>`;
      figures.appendChild(box);
    };
    put('Выручка', money(r.revenue_pence));
    put('Наличными', money(r.cash_pence), 'cash');
    put('Картой', money(r.card_pence), 'card');
    put('Чеков', r.checks);
    put('Средний чек', money(r.average_pence));
    put('Гостей', r.guests);
    if (r.discount_pence) put('Скидки', money(r.discount_pence), 'warn');
    if (r.cancelled.count) {
      put('Отмены', `${r.cancelled.count} · ${money(r.cancelled.amount_pence)}`, 'warn');
    }
    wrap.appendChild(figures);

    if (r.by_waiter.length) {
      wrap.appendChild(el('h2', '', 'По официантам'));
      wrap.appendChild(this.table(
        ['Официант', 'Чеков', 'Гостей', 'Сумма'],
        r.by_waiter.map(w => [
          esc(w.name),
          { num: w.checks },
          { num: w.guests },
          { num: money(w.amount_pence) }
        ])
      ));
    }

    if (r.top_items.length) {
      wrap.appendChild(el('h2', '', 'Что заказывали'));
      wrap.appendChild(this.table(
        ['Позиция', 'Продано'],
        r.top_items.map(i => [esc(i.name), { num: i.qty }])
      ));
    }
    return wrap;
  },

  /* ---------------------------------------------------------- оплаты ---- */
  /* Отчёт отвечает «сколько всего», этот список — «за что именно». Его
     открывают, когда касса не сошлась или гость вернулся со словами «мне
     посчитали лишнее»: здесь видно позиции, скидку с причиной и то, что
     отменили до оплаты. */
  view_payments() {
    const d = this.data.payments;
    const wrap = el('div', 'panel');
    wrap.appendChild(el('h2', '', 'Оплаты'));
    wrap.appendChild(el('p', 'hint',
      'Закрытые чеки. Нажмите строку — покажет, что было внутри: позиции, '
      + 'скидку с причиной и отменённое до оплаты.'));

    const pick = el('div', 'row-actions');
    [[24, 'Сутки'], [72, 'Три дня'], [168, 'Неделя']].forEach(([h, name]) => {
      const b = el('button', 'btn' + (this.hours === h ? ' primary' : ''), name);
      b.addEventListener('click', () => { this.hours = h; this.load(); });
      pick.appendChild(b);
    });
    wrap.appendChild(pick);

    const figures = el('div', 'figures');
    const put = (label, value, cls) => {
      const box = el('div', 'figure ' + (cls || ''));
      box.innerHTML = `<div class="label">${esc(label)}</div><div class="value">${value}</div>`;
      figures.appendChild(box);
    };
    put('Чеков', d.checks);
    put('Наличными', money(d.cash_pence), 'cash');
    put('Картой', money(d.card_pence), 'card');
    if (d.discount_pence) put('Скидки', money(d.discount_pence), 'warn');
    wrap.appendChild(figures);

    if (!d.rows.length) {
      wrap.appendChild(el('p', 'hint', 'За этот срок ничего не закрывали.'));
      return wrap;
    }

    const box = el('div', 'scroller');
    const node = el('table', 'grid');
    node.innerHTML = '<thead><tr>'
      + ['Время', 'Стол', 'Чек', 'Официант', 'Скидка', 'Чем платили', 'Сумма']
        .map(h => `<th>${esc(h)}</th>`).join('')
      + '</tr></thead>';
    const body = el('tbody');
    d.rows.forEach(r => {
      const tr = el('tr', 'clickable');
      tr.innerHTML = `<td>${esc(this.when(r.closed_at))}</td>
        <td>${esc(r.table)}</td>
        <td class="num">№${r.number}</td>
        <td>${esc(r.waiter)}</td>
        <td>${r.discount_pence ? '−' + money(r.discount_pence) : ''}</td>
        <td>${esc(this.methods(r.payments))}</td>
        <td class="num">${money(r.total_pence)}</td>`;
      tr.addEventListener('click', () => this.showCheck(r));
      body.appendChild(tr);
    });
    node.appendChild(body);
    box.appendChild(node);
    wrap.appendChild(box);
    return wrap;
  },

  /* В табеле дата обязательна. «04:23» без числа — это про сегодня или про
     прошлый вторник? По табелю считают зарплату, гадать в нём нечего. */
  stamp(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
      + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  },

  when(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const day = d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
    const time = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    // Сегодняшнее без даты: за смену её видеть незачем.
    const today = new Date().toDateString() === d.toDateString();
    return today ? time : day + ' ' + time;
  },

  methods(list) {
    const names = { card: 'карта', cash: 'наличные' };
    return [...new Set(list.map(p => names[p.method] || p.method))].join(' + ') || '—';
  },

  showCheck(r) {
    Sheet.show(`Стол ${esc(r.table)} · чек №${r.number}`,
      `${esc(this.when(r.closed_at))} · ${esc(r.waiter)} · ${r.guests} гост.`, body => {
      const lines = el('div', 'totals');
      let html = r.items.map(i =>
        `<div class="row"><span>${i.qty}× ${esc(i.name)}`
        + (i.options.length ? `<span class="muted"> · ${esc(i.options.join(' · '))}</span>` : '')
        + `</span><span>${money(i.total_pence)}</span></div>`).join('');
      html += `<div class="row"><span class="muted">Позиции</span><span>${money(r.subtotal_pence)}</span></div>`;
      if (r.discount_pence) {
        html += `<div class="row off"><span>Скидка${r.discount_reason
          ? ' · ' + esc(r.discount_reason) : ''}</span><span>−${money(r.discount_pence)}</span></div>`;
      }
      r.payments.forEach(p => {
        const name = p.method === 'cash' ? 'Наличные' : 'Карта';
        const change = p.tendered_pence && p.tendered_pence > p.amount_pence
          ? ` <span class="muted">(дали ${money(p.tendered_pence)}, сдача ${money(p.tendered_pence - p.amount_pence)})</span>`
          : '';
        html += `<div class="row"><span>${name}${change}</span><span>${money(p.amount_pence)}</span></div>`;
      });
      html += `<div class="row big"><span>Итого</span><span>${money(r.total_pence)}</span></div>`;
      lines.innerHTML = html;
      body.appendChild(lines);

      if (r.cancelled.length) {
        body.appendChild(el('p', 'hint', 'Отменено до оплаты:'));
        const off = el('div', 'totals');
        off.innerHTML = r.cancelled.map(i =>
          `<div class="row off"><span>${i.qty}× ${esc(i.name)}`
          + (i.reason ? `<span class="muted"> · ${esc(i.reason)}</span>` : '')
          + '</span><span></span></div>').join('');
        body.appendChild(off);
      }

      const ok = el('button', 'btn wide big primary', 'Закрыть');
      ok.addEventListener('click', () => Sheet.hide());
      body.appendChild(el('div', '', '<div style="height:12px"></div>'));
      body.appendChild(ok);
    });
  },

  /* ---------------------------------------------------------- табель ---- */
  /* Отчёт отвечает «сколько заведение заработало», табель — «сколько
     отработал человек». Путать нельзя: зарплату платят за часы. */
  view_timesheet() {
    const d = this.data.timesheet;
    const wrap = el('div', 'panel');
    wrap.appendChild(el('h2', '', 'Табель'));
    wrap.appendChild(el('p', 'hint',
      'Смену открывает и закрывает сам человек в своём приложении: пришёл — '
      + 'открыл, ушёл — закрыл. Часы считает сервер, в минутах: округление до '
      + 'часа в обе стороны — это чужие деньги. Табель хранится год.'));

    const pick = el('div', 'row-actions');
    [[7, 'Неделя'], [30, 'Месяц'], [365, 'Год']].forEach(([n, name]) => {
      const b = el('button', 'btn' + (this.days === n ? ' primary' : ''), name);
      b.addEventListener('click', () => { this.days = n; this.load(); });
      pick.appendChild(b);
    });
    wrap.appendChild(pick);

    if (!d.people.length) {
      wrap.appendChild(el('p', 'hint', 'За этот срок смен не закрывали.'));
      return wrap;
    }

    wrap.appendChild(el('h2', '', 'Часы'));
    wrap.appendChild(this.table(
      ['Сотрудник', 'Роль', 'Смен', 'Отработано', 'Выручка'],
      d.people.map(p => [
        esc(p.name), esc(p.role_name),
        { num: p.shifts },
        { num: esc(p.hours_text) },
        { num: money(p.revenue_pence) }
      ])
    ));

    wrap.appendChild(el('h2', '', 'Смены'));
    wrap.appendChild(this.table(
      ['Сотрудник', 'Открыл', 'Закрыл', 'Отработано', ''],
      d.shifts.map(s => [
        esc(s.name),
        esc(this.stamp(s.opened_at)),
        s.closed_at ? esc(this.stamp(s.closed_at)) : '<span class="faint">идёт</span>',
        { num: esc(s.hours_text) },
        s.auto_closed
          ? '<span style="color:var(--warn)">закрыта сама</span>'
          : ''
      ]),
      d.shifts.map(s => (s.closed_at ? '' : 'off'))
    ));
    return wrap;
  },

  /* -------------------------------------------------------- персонал ---- */
  view_users() {
    const wrap = el('div', 'panel');
    wrap.appendChild(el('h2', '', 'Персонал'));
    wrap.appendChild(el('p', 'hint',
      'Вход только по личному PIN. В зале он из четырёх цифр, в админке — из '
      + 'шести: отсюда правят цены, роли и склад. Свой PIN каждый меняет сам; '
      + 'здесь его сбрасывают, когда забыли. PIN показывается один раз — '
      + 'дальше в базе только хеш, и подсмотреть его нельзя даже отсюда.'));
    wrap.appendChild(el('p', 'hint',
      'PIN планшета бара и кухни — отдельный, он живёт во вкладке «Станции». '
      + 'Им открывают и закрывают смену на планшете, и задаёт его тот же, кто '
      + 'заводит персонал.'));
    wrap.appendChild(this.ownPin());

    // Менеджеру список нужен ради одного: найти того, кто забыл PIN. Заводить
    // людей и менять роли он не может, поэтому формы просто нет.
    if (!Auth.can('users.manage')) {
      wrap.appendChild(this.table(
        ['Имя', 'Роль', 'PIN', ''],
        this.data.users.map(u => [
          esc(u.name), esc(u.role_name),
          u.has_pin ? 'задан' : '<span style="color:var(--danger)">нет</span>',
          { actions: this.userActions(u) }
        ]),
        this.data.users.map(u => (u.active ? '' : 'off'))
      ));
      return wrap;
    }

    const form = el('div', 'form');
    const fields = el('div', 'line-fields');
    const name = el('input', 'field');
    name.placeholder = 'Имя';
    const role = el('select', 'field');
    ROLE_LIST.forEach(([k, n]) => {
      const o = el('option', '', esc(n));
      o.value = k;
      role.appendChild(o);
    });
    const pin = el('input', 'field');
    pin.inputMode = 'numeric';
    const fitPin = () => {
      const need = pinLength(role.value);
      pin.maxLength = need;
      pin.placeholder = `PIN, ${digits(need)} (пусто — придумает сам)`;
      if (pin.value.length > need) pin.value = pin.value.slice(0, need);
    };
    role.addEventListener('change', fitPin);
    fitPin();
    fields.append(
      this.field('Имя', name),
      this.field('Роль', role),
      this.field('PIN', pin, 'пусто — придумает сам')
    );
    form.appendChild(fields);

    const create = el('button', 'btn primary', 'Завести сотрудника');
    create.addEventListener('click', async () => {
      if (!name.value.trim()) return toast('Впишите имя', 'bad');
      try {
        const made = await API.post('/api/admin/users', {
          name: name.value.trim(), role: role.value, pin: pin.value.trim() || null
        });
        name.value = ''; pin.value = '';
        await this.load();
        this.showPin(made);
      } catch (e) { toast(e.message, 'bad'); }
    });
    form.appendChild(create);
    wrap.appendChild(form);

    wrap.appendChild(this.table(
      ['Имя', 'Роль', 'PIN', ''],
      this.data.users.map(u => [
        esc(u.name),
        esc(u.role_name),
        u.has_pin ? 'задан' : '<span style="color:var(--danger)">нет</span>',
        { actions: this.userActions(u) }
      ]),
      this.data.users.map(u => (u.active ? '' : 'off'))
    ));
    return wrap;
  },

  /* Свой PIN меняют здесь же: администратор в приложение зала не заходит, а
     менять его раз в жизни всё равно приходится — хотя бы после первого
     входа с PIN из письма. */
  ownPin() {
    const box = el('div', 'row-actions');
    if (!Auth.can('pin.self')) return box;
    const go = el('button', 'btn', 'Сменить свой PIN');
    go.addEventListener('click', () => this.changeOwnPin());
    box.appendChild(go);
    return box;
  },

  changeOwnPin() {
    const need = (Auth.me && Auth.me.pin_length) || 4;
    Sheet.show('Свой PIN', `${digits(need)}. Старый нужен обязательно.`, body => {
      const field = (place) => {
        const f = el('input', 'field');
        f.type = 'password';
        f.inputMode = 'numeric';
        f.maxLength = need;
        f.placeholder = place;
        return f;
      };
      const old = field('Старый PIN');
      const fresh = field('Новый PIN');
      body.append(old, el('div', '', '<div style="height:8px"></div>'), fresh,
                  el('div', '', '<div style="height:12px"></div>'));

      const save = el('button', 'btn wide big primary', 'Сохранить');
      save.addEventListener('click', async () => {
        if (old.value.length !== need || fresh.value.length !== need) {
          return toast(`PIN — ровно ${digits(need)}`, 'bad');
        }
        try {
          await API.post('/api/auth/pin/change', { old: old.value, new: fresh.value });
          Sheet.hide();
          toast('PIN изменён', 'good');
        } catch (e) { toast(e.message, 'bad'); }
      });
      body.appendChild(save);
    });
  },

  userActions(user) {
    const box = el('div', 'row-actions');
    const reset = el('button', 'btn', 'Новый PIN');
    reset.addEventListener('click', async () => {
      try {
        this.showPin(await API.post(`/api/admin/users/${user.id}/pin`, {}));
        this.load();
      } catch (e) { toast(e.message, 'bad'); }
    });
    box.appendChild(reset);

    if (!Auth.can('users.manage')) return box;

    // Роль меняется здесь же. Переезд между залом и админкой меняет длину
    // PIN, поэтому сервер сразу выдаёт новый — иначе человек остаётся
    // снаружи со старым PIN не той длины.
    const role = el('select', 'field slim');
    ROLE_LIST.forEach(([k, n]) => {
      const o = el('option', '', esc(n));
      o.value = k;
      if (k === user.role) o.selected = true;
      role.appendChild(o);
    });
    role.addEventListener('change', async () => {
      try {
        const out = await API.patch(`/api/admin/users/${user.id}`, { role: role.value });
        await this.load();
        if (out.pin) this.showPin(out);
        else toast('Роль изменена', 'good');
      } catch (e) { toast(e.message, 'bad'); this.load(); }
    });
    box.appendChild(role);

    const toggle = el('button', 'btn ' + (user.active ? 'danger' : ''),
      user.active ? 'Отключить' : 'Включить');
    toggle.addEventListener('click', async () => {
      try {
        await API.patch(`/api/admin/users/${user.id}`, { active: !user.active });
        this.load();
      } catch (e) { toast(e.message, 'bad'); }
    });
    box.appendChild(toggle);

    // Заведённого по ошибке надо убирать совсем, иначе за год список
    // персонала зарастает опечатками. Того, кто уже работал, — только
    // выключить: отчёт за прошлый месяц должен знать, чья это выручка.
    if (!user.worked && user.id !== this.me.id) {
      const drop = el('button', 'btn danger', 'Убрать совсем');
      drop.addEventListener('click', async () => {
        try {
          await API.del(`/api/admin/users/${user.id}`);
          toast('Сотрудник убран', 'good');
          this.load();
        } catch (e) { toast(e.message, 'bad'); }
      });
      box.appendChild(drop);
    }
    return box;
  },

  showPin(user) {
    Sheet.show(esc(user.name), 'Запишите: второй раз он не покажется', body => {
      const box = el('div', 'pin-shown');
      box.innerHTML = `<div class="code">${esc(user.pin)}</div>
        <div class="note">Личный PIN из ${esc(String(user.pin_length || pinLength(user.role)))} цифр.
          Им сотрудник входит в своё приложение${ADMIN_ROLES.includes(user.role)
            ? ' — в админку, по адресу /admin/' : ''}.</div>`;
      body.appendChild(box);
      const ok = el('button', 'btn wide big primary', 'Записал');
      ok.addEventListener('click', () => Sheet.hide());
      body.appendChild(ok);
    });
  },

  /* ------------------------------------------------------------ столы --- */
  /* Зал расставляется мышью, а не таблицей координат. Официант потом видит
     ровно эту картинку, поэтому и рисовать её должен тот, кто зал знает. */
  view_tables() {
    const wrap = el('div', 'panel');
    wrap.appendChild(el('h2', '', 'Расстановка столов'));
    wrap.appendChild(el('p', 'hint',
      'Перетащите столы так, как они стоят в зале. Нажмите на стол, чтобы '
      + 'поменять номер, число мест или убрать его. Официант видит эту же '
      + 'картинку — и находит стол глазами, а не по списку.'));

    const zones = Plan.zones(this.data.tables);
    if (!zones.includes(this.zone)) this.zone = zones[0];

    if (zones.length > 1) {
      const row = el('div', 'zones');
      zones.forEach(zone => {
        const chip = el('button', 'chip' + (zone === this.zone ? ' on' : ''), esc(zone));
        chip.addEventListener('click', () => { this.zone = zone; this.load(); });
        row.appendChild(chip);
      });
      wrap.appendChild(row);
    }

    const field = el('div', 'plan editing');
    const mine = Plan.inZone(this.data.tables, this.zone);
    mine.forEach((table, n) => field.appendChild(this.spot(field, table, n)));
    if (!mine.length) {
      field.appendChild(el('p', 'plan-hint',
        '<span style="position:absolute;left:0;right:0;top:44%;text-align:center">'
        + 'В этой зоне пока нет столов</span>'));
    }
    wrap.appendChild(field);

    const bar = el('div', 'plan-bar');
    const add = el('button', 'btn primary', 'Добавить стол');
    add.addEventListener('click', () => this.addTable(mine));
    bar.appendChild(add);

    const addZone = el('button', 'btn', 'Новая зона');
    addZone.addEventListener('click', () => this.addZone());
    bar.appendChild(addZone);

    bar.appendChild(el('span', 'grow'));
    bar.appendChild(el('span', 'muted',
      `${mine.length} ${plural(mine.length, 'стол', 'стола', 'столов')}`
      + ` · ${mine.reduce((n, t) => n + t.seats, 0)} мест`));
    wrap.appendChild(bar);

    const off = this.data.tables.filter(t => !t.active);
    if (off.length) {
      wrap.appendChild(el('h2', '', 'Выключенные'));
      wrap.appendChild(el('p', 'hint',
        'Не показываются официанту, но остаются в истории.'));
      wrap.appendChild(this.table(
        ['Стол', 'Зона', 'Мест', ''],
        off.map(t => [esc(t.label), esc(t.zone), { num: t.seats },
                      { actions: this.tableActions(t) }]),
        off.map(() => 'off')
      ));
    }
    return wrap;
  },

  spot(field, table, index) {
    const node = el('button', 'spot' + (table.seats >= 4 ? ' wide' : ''));
    node.type = 'button';
    node.dataset.tap = '1';
    node.innerHTML = `<span class="n">${esc(table.label)}</span>
      <span class="seats">${table.seats} ${plural(table.seats, 'место', 'места', 'мест')}</span>`;
    Plan.place(node, Plan.spot(table, index));

    Plan.drag(field, node, async spot => {
      try {
        await API.post('/api/admin/tables/plan', {
          tables: [{ id: table.id, x: spot.x, y: spot.y, zone: this.zone }]
        });
        table.x = spot.x;
        table.y = spot.y;
      } catch (e) { toast(e.message, 'bad'); this.load(); }
    });
    node.addEventListener('plan-tap', () => this.editTable(table));
    return node;
  },

  editTable(table) {
    Sheet.show('Стол ' + esc(table.label), esc(table.zone), body => {
      const fields = el('div', 'line-fields');
      const label = el('input', 'field');
      label.value = table.label;
      label.placeholder = 'Номер';
      const seats = el('input', 'field');
      seats.type = 'number';
      seats.min = '1';
      seats.value = table.seats;
      fields.append(label, seats);
      body.appendChild(fields);
      body.appendChild(el('div', '', '<div style="height:12px"></div>'));

      const save = el('button', 'btn wide big primary', 'Сохранить');
      save.addEventListener('click', async () => {
        Sheet.hide();
        try {
          await API.patch(`/api/admin/tables/${table.id}`, {
            label: label.value.trim() || table.label,
            seats: Number(seats.value) || table.seats
          });
          this.load();
        } catch (e) { toast(e.message, 'bad'); }
      });
      body.appendChild(save);
      body.appendChild(el('div', '', '<div style="height:8px"></div>'));

      // Стол, по которому были чеки, удалить нельзя: закрытый чек должен
      // знать, где сидели. Такой выключают.
      const kill = el('button', 'btn wide big danger',
        table.ever_used ? 'Выключить стол' : 'Убрать стол');
      kill.addEventListener('click', async () => {
        Sheet.hide();
        try {
          if (table.ever_used) {
            await API.patch(`/api/admin/tables/${table.id}`, { active: false });
          } else {
            await API.del(`/api/admin/tables/${table.id}`);
          }
          this.load();
        } catch (e) { toast(e.message, 'bad'); }
      });
      body.appendChild(kill);
    });
  },

  addTable(existing) {
    // Номер предлагаем следующий по счёту: чаще всего он и нужен, а спорить
    // с подсказкой дешевле, чем вспоминать, какой был последним.
    const numbers = this.data.tables.map(t => parseInt(t.label, 10)).filter(n => !isNaN(n));
    const next = String((numbers.length ? Math.max(...numbers) : 0) + 1);

    Sheet.show('Новые столы', esc(this.zone), body => {
      const fields = el('div', 'line-fields');
      const label = el('input', 'field');
      label.value = next;
      label.placeholder = 'Номер';
      const seats = el('input', 'field');
      seats.type = 'number';
      seats.min = '1';
      seats.value = '4';
      // Зал ставят один раз и целиком: двадцать столов по одному — это
      // двадцать одинаковых форм подряд.
      const count = el('input', 'field');
      count.type = 'number';
      count.min = '1';
      count.max = '40';
      count.value = '1';
      fields.append(label, seats, count);
      body.appendChild(fields);
      body.appendChild(el('p', 'hint',
        'Номер, мест за столом, сколько столов. Занятые номера пропускаются.'));
      body.appendChild(el('div', '', '<div style="height:12px"></div>'));

      const ok = el('button', 'btn wide big primary', 'Поставить в зал');
      ok.addEventListener('click', async () => {
        Sheet.hide();
        const many = Math.max(1, Math.min(40, Number(count.value) || 1));
        const spot = Plan.spot({}, existing.length);
        try {
          if (many > 1) {
            const start = parseInt(label.value, 10);
            const made = await API.post('/api/admin/tables/batch', {
              count: many,
              start: isNaN(start) ? null : start,
              zone: this.zone,
              seats: Number(seats.value) || 4
            });
            toast(`Столов добавлено: ${made.tables.length}`, 'good');
          } else {
            await API.post('/api/admin/tables', {
              label: label.value.trim() || next,
              zone: this.zone,
              seats: Number(seats.value) || 4,
              position: existing.length + 1,
              x: spot.x,
              y: spot.y
            });
          }
          this.load();
        } catch (e) { toast(e.message, 'bad'); }
      });
      body.appendChild(ok);
    });
  },

  addZone() {
    Sheet.show('Новая зона', 'Терраса, второй зал, летник', body => {
      const name = el('input', 'field');
      name.placeholder = 'Название зоны';
      body.appendChild(name);
      body.appendChild(el('div', '', '<div style="height:12px"></div>'));
      const ok = el('button', 'btn wide big primary', 'Создать и добавить стол');
      ok.addEventListener('click', () => {
        const zone = name.value.trim();
        if (!zone) return toast('Впишите название', 'bad');
        Sheet.hide();
        this.zone = zone;
        this.addTable([]);
      });
      body.appendChild(ok);
    });
  },

  tableActions(table) {
    const box = el('div', 'row-actions');
    const toggle = el('button', 'btn ' + (table.active ? 'danger' : ''),
      table.active ? 'Выключить' : 'Включить');
    toggle.addEventListener('click', async () => {
      try {
        await API.patch(`/api/admin/tables/${table.id}`, { active: !table.active });
        this.load();
      } catch (e) { toast(e.message, 'bad'); }
    });
    box.appendChild(toggle);

    // Стол, по которому никогда не было чеков, можно убрать совсем — он ни
    // на что не ссылается. По которому были — только выключить: закрытый
    // чек должен знать, где сидели.
    if (!table.ever_used) {
      const drop = el('button', 'btn danger', 'Убрать совсем');
      drop.addEventListener('click', async () => {
        try {
          await API.del(`/api/admin/tables/${table.id}`);
          this.load();
        } catch (e) { toast(e.message, 'bad'); }
      });
      box.appendChild(drop);
    }
    return box;
  },

  /* ---------------------------------------------------------- станции --- */
  view_stations() {
    const wrap = el('div', 'panel');
    wrap.appendChild(el('h2', '', 'Планшеты станций'));
    wrap.appendChild(el('p', 'hint',
      'Смену планшета открывают и закрывают PIN-ом. Подходит личный PIN '
      + 'бармена или кухаря — тогда в смене остаётся имя. Если на баре двое, '
      + 'второй не открывает свою смену, а встаёт в эту: на планшете кнопка '
      + '«+ Ещё человек». Смена одна на станцию, потому что очередь марок '
      + 'общая. PIN станции ниже — запасной, на случай забытого своего: он '
      + 'открывает смену без имени.'));

    wrap.appendChild(this.table(
      ['Станция', 'PIN', 'Смена', ''],
      this.data.stations.map(s => [
        esc(s.name),
        s.has_pin ? 'задан' : '<span style="color:var(--danger)">не задан</span>',
        s.shift.open
          ? `<span style="color:var(--ok)">открыта с ${esc(new Date(s.shift.opened_at)
              .toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }))}</span>`
          : '<span class="faint">закрыта</span>',
        { actions: this.stationActions(s) }
      ])
    ));

    if (this.data.shifts.length) {
      wrap.appendChild(el('h2', '', 'Смены'));
      wrap.appendChild(el('p', 'hint',
        'Открытая смена — это ответ на вопрос «кто-нибудь вообще смотрит на бар?». '
        + 'Если марки висят, а смена не открыта, планшет просто не включили.'));
      // «Кто» — тот, чей PIN ввели. Пусто значит, что вошли общим PIN
      // станции: смена засчитана, но имени за ней нет.
      const who = name => (name
        ? esc(name)
        : '<span class="faint">по PIN станции</span>');
      wrap.appendChild(this.table(
        ['Станция', 'Кто был', 'Открыл', 'Открыта', 'Закрыл', 'Закрыта', 'Марок'],
        this.data.shifts.map(s => [
          esc(s.name),
          // Смена одна на станцию, а людей в ней бывает несколько, и часы у
          // каждого свои: один отработал три, другой семь. Кто уже ушёл
          // домой — бледнее: видно, кто на баре прямо сейчас.
          s.people && s.people.length
            ? s.people.map(x => {
                const line = `${esc(x.name)} <span class="faint">${esc(x.hours_text)}</span>`;
                return x.here ? line : `<span class="faint">${esc(x.name)} ${esc(x.hours_text)}</span>`;
              }).join('<br>')
            : '<span class="faint">—</span>',
          who(s.opened_by),
          esc(new Date(s.opened_at).toLocaleString('ru-RU')),
          s.closed_at ? who(s.closed_by) : '',
          s.closed_at
            ? esc(new Date(s.closed_at).toLocaleString('ru-RU'))
              + (s.note ? ` <span class="faint">· ${esc(s.note)}</span>` : '')
            : '<span style="color:var(--ok)">идёт</span>',
          { num: s.tickets_done || '' }
        ])
      ));
    }
    return wrap;
  },

  stationActions(station) {
    const box = el('div', 'row-actions');
    const set = el('button', 'btn', station.has_pin ? 'Сменить PIN' : 'Задать PIN');
    set.addEventListener('click', () => {
      Sheet.show(esc(station.name), 'PIN планшета — четыре цифры', body => {
        const input = el('input', 'field');
        input.inputMode = 'numeric';
        input.maxLength = 4;
        input.placeholder = 'Новый PIN станции';
        body.appendChild(input);
        body.appendChild(el('div', '', '<div style="height:12px"></div>'));
        const ok = el('button', 'btn wide big primary', 'Сохранить');
        ok.addEventListener('click', async () => {
          if (input.value.length !== 4) return toast('PIN — ровно четыре цифры', 'bad');
          Sheet.hide();
          try {
            await API.post('/api/admin/stations/pin',
              { station: station.station, pin: input.value });
            toast('PIN станции сохранён', 'good');
            this.load();
          } catch (e) { toast(e.message, 'bad'); }
        });
        body.appendChild(ok);
      });
    });
    box.appendChild(set);
    return box;
  },

  /* ------------------------------------------------------------- меню --- */
  view_menu() {
    const wrap = el('div', 'panel');
    wrap.appendChild(el('h2', '', 'Меню'));
    wrap.appendChild(el('p', 'hint',
      'Цена — это деньги, поэтому её изменение попадает в журнал с именем. '
      + 'Стоп-лист ставят бар и кухня со своего планшета: кончилось у них.'));
    wrap.appendChild(this.syncBox());
    wrap.appendChild(this.categoryStops());

    wrap.appendChild(this.table(
      ['Позиция', 'Категория', 'Станция', 'Цена', 'Состояние', ''],
      this.data.menu.items.map(i => [
        esc(i.name),
        esc((this.data.menu.categories.find(c => c.key === i.category) || {}).name || ''),
        esc(i.station_name),
        { num: money(i.price_pence) },
        i.state === 'off' ? '<span style="color:var(--danger)">стоп</span>'
          : i.state === 'soon' ? '<span style="color:var(--warn)">скоро · с сайта</span>'
          : 'в продаже',
        { actions: this.menuActions(i) }
      ])
    ));
    return wrap;
  },

  /* Меню приезжает с сайта само. Здесь видно, когда оно приезжало в
     последний раз, — и кнопка на случай «поправил цену и хочу увидеть
     сейчас», чтобы не ждать следующей проверки. */
  syncBox() {
    const state = this.data.sync || {};
    const box = el('div', 'sync');

    if (!state.enabled) {
      box.classList.add('off');
      box.innerHTML = '<div class="body"><b>Меню ведётся здесь.</b>'
        + '<div class="muted">Синхронизация с сайтом выключена: в настройках '
        + 'сервера пуст адрес каталога.</div></div>';
      return box;
    }

    const bad = state.status === 'error';
    if (bad) box.classList.add('bad');
    const when = state.at ? new Date(state.at).toLocaleString('ru-RU') : 'ещё не ходили';
    box.innerHTML = `<div class="body">
        <b>${bad ? 'Меню не обновилось' : 'Меню приезжает с сайта'}</b>
        <div class="muted">${esc(when)}${bad ? ' · ' + esc(state.error || '') : ''}</div>
        <div class="faint">Цены и позиции ведутся в админке гостевого меню.
          Правка здесь продержится до следующей проверки.</div>
      </div>`;

    const now = el('button', 'btn', 'Обновить сейчас');
    now.addEventListener('click', async () => {
      now.disabled = true;
      now.textContent = 'Идём за меню…';
      try {
        const result = await API.post('/api/admin/menu/sync', {});
        const r = result.report;
        if (result.status === 'error') toast(result.error || 'Не получилось', 'bad');
        else if (!r || (!r.added.length && !r.updated.length && !r.removed.length)) {
          toast('Меню и так свежее', 'good');
        } else {
          toast(`Обновлено: +${r.added.length} ~${r.updated.length} −${r.removed.length}`, 'good');
        }
      } catch (e) { toast(e.message, 'bad'); }
      this.load();
    });
    box.appendChild(now);
    return box;
  },

  /* Стоп на целый раздел. Кончился газ — встали все кальяны, а не один;
     снимать стоп с двенадцати позиций по одной, когда газ привезли, — то же
     самое наоборот. */
  categoryStops() {
    const box = el('div', 'form');
    const cats = this.data.menu.categories || [];
    if (!cats.length) return box;

    box.appendChild(el('p', 'hint', 'Стоп на целый раздел:'));
    const row = el('div', 'row-actions');
    row.style.justifyContent = 'flex-start';
    row.style.flexWrap = 'wrap';

    cats.forEach(cat => {
      const mine = this.data.menu.items.filter(i => i.category === cat.key);
      if (!mine.length) return;
      const off = mine.every(i => i.local_state === 'off');
      const b = el('button', 'btn' + (off ? ' danger' : ''),
        esc(cat.name) + (off ? ' · стоп' : ''));
      b.addEventListener('click', async () => {
        try {
          await API.post('/api/menu/category/state',
            { category: cat.key, state: off ? 'on' : 'off' });
          toast(off ? `${cat.name} — снова в продаже` : `${cat.name} — стоп`, 'good');
          this.load();
        } catch (e) { toast(e.message, 'bad'); }
      });
      row.appendChild(b);
    });
    box.appendChild(row);
    return box;
  },

  menuActions(item) {
    const box = el('div', 'row-actions');
    const price = el('button', 'btn', 'Цена');
    price.addEventListener('click', () => {
      Sheet.show(esc(item.name), 'Новая цена, £', body => {
        const input = el('input', 'field');
        input.inputMode = 'decimal';
        input.value = (item.price_pence / 100).toFixed(2);
        body.appendChild(input);
        body.appendChild(el('div', '', '<div style="height:12px"></div>'));
        const ok = el('button', 'btn wide big primary', 'Сохранить');
        ok.addEventListener('click', async () => {
          const pence = Math.round(parseFloat((input.value || '0').replace(',', '.')) * 100);
          if (!(pence >= 0)) return toast('Не похоже на цену', 'bad');
          Sheet.hide();
          try {
            await API.patch(`/api/admin/menu/${item.id}`, { price_pence: pence });
            this.load();
          } catch (e) { toast(e.message, 'bad'); }
        });
        body.appendChild(ok);
      });
    });
    box.appendChild(price);

    const stop = el('button', 'btn ' + (item.state === 'off' ? '' : 'danger'),
      item.state === 'off' ? 'Вернуть' : 'Стоп');
    stop.addEventListener('click', async () => {
      try {
        await API.post(`/api/menu/${item.id}/state`, { state: item.state === 'off' ? 'on' : 'off' });
        this.load();
      } catch (e) { toast(e.message, 'bad'); }
    });
    box.appendChild(stop);
    return box;
  },

  /* ------------------------------------------------------------ склад --- */
  view_stock() {
    const wrap = el('div', 'panel');
    const data = this.data.stock;
    wrap.appendChild(el('h2', '', 'Склад'));
    wrap.appendChild(el('p', 'hint',
      'Остаток — это сумма движений, а не число, которое кто-то правит: иначе '
      + 'на вопрос «куда делось полбутылки» ответить нечем. Продажи '
      + 'списываются сами, когда позиция уходит на станцию.'));

    // Позиции, которые ещё не заполняли, — не тревога, а список дел.
    if ((data.new || []).length) {
      wrap.appendChild(el('p', 'hint',
        `Не заполнено: ${data.new.length} ${plural(data.new.length, 'позиция', 'позиции', 'позиций')}`
        + ' — впишите, сколько стоит на полке. Кнопка «Движение» в строке.'));
    }

    if (data.out.length || data.low.length) {
      const alarm = el('div', 'sync' + (data.out.length ? ' bad' : ''));
      alarm.innerHTML = `<div class="body">
        ${data.out.length ? `<b>Кончилось: ${esc(data.out.join(', '))}</b>` : ''}
        ${data.low.length ? `<div class="muted">Заканчивается: ${esc(data.low.join(', '))}</div>` : ''}
      </div>`;
      wrap.appendChild(alarm);
    }

    const form = el('div', 'form');
    const fields = el('div', 'line-fields');
    const name = el('input', 'field');
    name.placeholder = 'Название (Absolut, лимоны…)';
    const unit = el('select', 'field');
    data.units.forEach(u => {
      const o = el('option', '', esc(u.name));
      o.value = u.key;
      unit.appendChild(o);
    });
    const qty = el('input', 'field');
    qty.type = 'number';
    qty.step = '0.001';
    qty.placeholder = 'Сколько сейчас';
    const low = el('input', 'field');
    low.type = 'number';
    low.step = '0.001';
    low.placeholder = 'Порог «мало»';
    fields.append(
      this.field('Название', name),
      this.field('В чём считаем', unit),
      this.field('Сколько сейчас', qty),
      this.field('Порог «мало»', low, 'ниже него позиция попадёт в тревогу')
    );
    form.appendChild(fields);

    // Заготовка по меню. Сорок позиций руками — вечер работы, и на середине
    // бросают; количество всё равно вписывает тот, кто посмотрел на полку.
    // Кнопка остаётся на месте и когда склад уже начали заводить руками:
    // позиции, у которых правила нет, всё равно надо чем-то закрыть, а
    // угадывать, почему кнопка пропала, никто не должен.
    {
      const fill = el('button', 'btn', 'Заполнить по меню');
      fill.addEventListener('click', async () => {
        try {
          const made = await API.post('/api/stock/fill');
          // Ноль — тоже ответ, и его надо объяснить: иначе кнопка выглядит
          // сломанной, хотя заводить было нечего.
          // Исправленные важнее заведённых: человек нажал кнопку второй раз
          // и должен узнать, что у него молча чинили счёт бутылок.
          const fixed = made.fixed
            ? ` Исправлено правил: ${made.fixed} — считались штуками там, где наливают.`
            : '';
          toast((made.items
            ? `Заведено позиций: ${made.items}. Количество впишите сами.`
            : 'Всё уже заведено: у каждой позиции меню есть правило.') + fixed,
            'good', 6000);
          this.load();
        } catch (e) { toast(e.message, 'bad'); }
      });
      wrap.appendChild(fill);
      wrap.appendChild(el('p', 'hint',
        'Заведёт по строке на каждую позицию меню и правило списания: что '
        + 'наливают — в миллилитрах, «сколько выбрали, столько и ушло»; '
        + 'остальное поштучно. Микс к крепкому свяжется с той же банкой, что '
        + 'стоит в меню отдельной строкой. Количество останется нулевым. '
        + 'Нажать можно ещё раз: заведённое не тронет, а правила, считавшие '
        + 'штуками там, где наливают, — починит.'));
    }

    const add = el('button', 'btn primary', 'Завести позицию');
    add.addEventListener('click', async () => {
      if (!name.value.trim()) return toast('Впишите название', 'bad');
      try {
        await API.post('/api/stock', {
          name: name.value.trim(),
          unit: unit.value,
          quantity: Number(qty.value) || 0,
          low_at: Number(low.value) || 0
        });
        name.value = ''; qty.value = ''; low.value = '';
        this.load();
      } catch (e) { toast(e.message, 'bad'); }
    });
    form.appendChild(add);
    wrap.appendChild(form);

    wrap.appendChild(this.table(
      ['Позиция', 'Остаток', 'Порог', ''],
      data.items.map(i => [
        esc(i.name),
        { num: `${i.quantity} ${i.unit_name}` },
        { num: i.low_at ? `${i.low_at} ${i.unit_name}` : '' },
        { actions: this.stockActions(i) }
      ]),
      data.items.map(i => (i.state === 'out' ? 'off' : ''))
    ));

    wrap.appendChild(el('h2', '', 'Что с чего списывается'));
    wrap.appendChild(el('p', 'hint',
      'Это и есть то, что списывается само: правило говорит, сколько уходит '
      + 'на одну порцию, и дальше склад считает без вас. Заполняется один раз '
      + '— во время смены сюда не заходят.'));

    // Правило с нулём не списывает ничего. Это половина ответа на вопрос
    // «почему остаток не двигается», поэтому такие строки идут первыми и
    // пересчитаны в заголовке.
    const rules = [...this.data.recipes].sort((a, b) => {
      const empty = (a.per_unit ? 1 : 0) - (b.per_unit ? 1 : 0);
      return empty || a.menu_item.localeCompare(b.menu_item, 'ru');
    });
    const blank = rules.filter(r => !r.per_unit).length;
    if (blank) {
      wrap.appendChild(el('p', 'hint',
        `Без расхода: ${blank} ${plural(blank, 'правило', 'правила', 'правил')} `
        + '— по ним пока не списывается ничего. Впишите, сколько уходит на порцию, '
        + 'в поле справа; они собраны наверху списка.'));
    }

    wrap.appendChild(this.recipeForm());
    wrap.appendChild(this.table(
      ['Позиция меню', 'Вариант', 'Списывается', ''],
      rules.map(r => [
        esc(r.menu_item),
        r.options_text ? esc(r.options_text) : '<span class="faint">любой</span>',
        { num: r.per_unit
            ? `${r.per_unit} ${r.unit_name} · ${esc(r.stock_item)}`
            : `<span class="gap bad">— ${esc(r.stock_item)}</span>` },
        { actions: this.recipeActions(r) }
      ]),
      rules.map(r => (r.per_unit ? '' : 'off'))
    ));
    return wrap;
  },

  stockActions(item) {
    const box = el('div', 'row-actions');

    const move = el('button', 'btn', 'Движение');
    move.addEventListener('click', () => {
      Sheet.show(esc(item.name), `Остаток ${item.quantity} ${item.unit_name}`, body => {
        const amount = el('input', 'field');
        amount.type = 'number';
        amount.step = '0.001';
        amount.placeholder = 'Сколько';
        body.appendChild(amount);
        body.appendChild(el('div', '', '<div style="height:10px"></div>'));

        const note = el('input', 'field');
        note.placeholder = 'Примечание (необязательно)';
        body.appendChild(note);
        body.appendChild(el('div', '', '<div style="height:12px"></div>'));

        const send = async (reason, useCounted) => {
          const value = Number(amount.value);
          if (!value && !useCounted) return toast('Впишите количество', 'bad');
          Sheet.hide();
          try {
            await API.post(`/api/stock/${item.id}/move`, useCounted
              ? { counted: value, reason: 'count', note: note.value }
              : { delta: value, reason, note: note.value });
            this.load();
          } catch (e) { toast(e.message, 'bad'); }
        };

        const arrival = el('button', 'btn wide big primary', 'Приход');
        arrival.addEventListener('click', () => send('in', false));
        const off = el('button', 'btn wide big danger', 'Списать');
        off.addEventListener('click', () => send('off', false));
        const counted = el('button', 'btn wide big', 'Насчитали на полке');
        counted.addEventListener('click', () => send('count', true));
        [arrival, off, counted].forEach(b => {
          body.appendChild(b);
          body.appendChild(el('div', '', '<div style="height:8px"></div>'));
        });
      });
    });
    box.appendChild(move);

    // Единицу меняют, когда поняли, как это считают на самом деле: сок
    // приезжает пачками, а наливают его в стакан. Кнопка есть, пока по
    // позиции не было движений: «3» в штуках и «3» в миллилитрах — разные
    // три, и менять единицу под чужой цифрой нельзя.
    if (item.state === 'new') {
      const unit = el('button', 'btn', 'Единица');
      unit.addEventListener('click', () => {
        Sheet.show(esc(item.name), `Сейчас считается в «${esc(item.unit_name)}»`, body => {
          body.appendChild(el('p', 'hint',
            'Миллилитры — если наливают: сок из пачки, вино из бутылки. '
            + 'Граммы — если взвешивают. Штуки — если берут целиком: банка, '
            + 'бутылка пива.'));
          (this.data.stock.units || []).forEach(u => {
            const b = el('button', 'btn wide big' + (u.key === item.unit ? ' primary' : ''),
                         esc(u.name));
            b.addEventListener('click', async () => {
              Sheet.hide();
              try {
                await API.patch(`/api/stock/${item.id}`, { unit: u.key });
                toast(`${item.name} теперь считается в «${u.name}»`, 'good');
                this.load();
              } catch (e) { toast(e.message, 'bad'); }
            });
            body.appendChild(b);
            body.appendChild(el('div', '', '<div style="height:8px"></div>'));
          });
        });
      });
      box.appendChild(unit);
    }

    const history = el('button', 'btn', 'История');
    history.addEventListener('click', async () => {
      try {
        const rows = await API.get(`/api/stock/${item.id}/moves`);
        Sheet.show(esc(item.name), 'Куда делось', body => {
          body.appendChild(this.table(
            ['Когда', 'Что', 'Сколько', 'Кто'],
            rows.map(r => [
              `<span class="when">${esc(new Date(r.at).toLocaleString('ru-RU'))}</span>`,
              esc(r.reason_name) + (r.note ? ` <span class="faint">${esc(r.note)}</span>` : ''),
              { num: (r.delta > 0 ? '+' : '') + r.delta },
              esc(r.who)
            ])
          ));
        });
      } catch (e) { toast(e.message, 'bad'); }
    });
    box.appendChild(history);
    return box;
  },

  recipeForm() {
    const form = el('div', 'form');

    // Списывать нечего, пока склад пуст. Форма из пустых списков — это
    // кнопка, которая молча ничего не делает.
    if (!this.data.stock.items.length) {
      form.appendChild(el('p', 'hint',
        'Сначала заведите позицию склада — то, что будет списываться. '
        + 'Правило связывает её с позицией меню.'));
      return form;
    }

    const fields = el('div', 'line-fields');

    const dish = el('select', 'field');
    (this.data.menu.items || []).forEach(i => {
      const o = el('option', '', esc(i.name));
      o.value = i.id;
      dish.appendChild(o);
    });
    const good = el('select', 'field');
    this.data.stock.items.forEach(i => {
      const o = el('option', '', esc(i.name));
      o.value = i.id;
      good.appendChild(o);
    });
    const per = el('input', 'field');
    per.type = 'number';
    per.step = '0.001';
    per.placeholder = '50';
    const variant = el('select', 'field');

    // Единица берётся у выбранного продукта: «50» без миллилитров — это
    // пятьдесят чего угодно.
    const unitOf = () => {
      const item = this.data.stock.items.find(i => i.id === good.value);
      return item ? item.unit_name : '';
    };
    const perBox = this.field('Сколько уходит', per, unitOf());
    good.addEventListener('change', () => {
      perBox.querySelector('.field-hint').textContent = unitOf();
    });

    fields.append(
      this.field('Позиция меню', dish),
      this.field('Вариант', variant, 'у водки — объём, у пиццы вариантов нет'),
      this.field('Что списать со склада', good),
      perBox
    );
    form.appendChild(fields);

    // Варианты подставляются от выбранной позиции: у пиццы их нет, у водки
    // семь, и печатать их руками — верный способ ошибиться.
    const fillVariants = () => {
      const item = (this.data.menu.items || []).find(i => i.id === dish.value);
      variant.innerHTML = '';
      const any = el('option', '', 'любой вариант');
      any.value = '';
      variant.appendChild(any);
      ((item && item.options) || []).forEach(g => {
        (g.choices || []).forEach(c => {
          const o = el('option', '', esc(`${g.label}: ${c.name}`));
          o.value = JSON.stringify({ [g.key]: c.key });
          variant.appendChild(o);
        });
      });
    };
    dish.addEventListener('change', fillVariants);
    fillVariants();

    const add = el('button', 'btn primary', 'Добавить правило');
    add.addEventListener('click', async () => {
      if (!Number(per.value)) return toast('Впишите расход', 'bad');
      try {
        await API.post('/api/stock/recipes', {
          menu_item_id: dish.value,
          stock_item_id: good.value,
          per_unit: Number(per.value),
          options: variant.value ? JSON.parse(variant.value) : {}
        });
        per.value = '';
        this.load();
      } catch (e) { toast(e.message, 'bad'); }
    });
    form.appendChild(add);
    return form;
  },

  recipeActions(recipe) {
    const box = el('div', 'row-actions');

    // Расход правится прямо в строке. Заготовка ставит ноль там, где цифру
    // знает только человек, и переписывать её удалением правила — тридцать
    // лишних движений на одно меню.
    const per = el('input', 'field slim');
    per.type = 'number';
    per.step = '0.001';
    per.value = recipe.per_unit;
    per.title = 'Сколько уходит на одну порцию';
    per.addEventListener('change', async () => {
      try {
        await API.patch(`/api/stock/recipes/${recipe.id}`,
          { per_unit: Number(per.value) || 0 });
        toast('Расход записан', 'good');
        this.load();
      } catch (e) { toast(e.message, 'bad'); }
    });
    box.appendChild(per);

    const kill = el('button', 'btn danger', 'Убрать');
    kill.addEventListener('click', async () => {
      try {
        await API.del(`/api/stock/recipes/${recipe.id}`);
        this.load();
      } catch (e) { toast(e.message, 'bad'); }
    });
    box.appendChild(kill);
    return box;
  },

  /* ---------------------------------------------------------- журнал ---- */
  /* -------------------------------------------------- инвентаризация ---- */
  /* Лист на сегодня: сколько должно быть, сколько есть, и куда делась
     разница. Записывается разница, а не новое число: само число ничего не
     объясняет, объясняет расхождение. */
  view_inventory() {
    const d = this.data.inventory;
    const wrap = el('div', 'panel');
    wrap.appendChild(el('h2', '', 'Инвентаризация'));
    wrap.appendChild(el('p', 'hint',
      'Слева расчётный остаток — сколько должно быть по чекам и приходам. '
      + 'Впишите, сколько стоит на полке: в историю попадёт разница, и по ней '
      + 'потом видно, когда расхождение началось.'));

    if (!d.sheet.length) {
      wrap.appendChild(el('p', 'hint', 'Склад пуст — считать нечего.'));
      return wrap;
    }

    const rows = d.sheet.map(i => {
      const field = el('input', 'field slim');
      field.type = 'number';
      field.step = '0.001';
      field.placeholder = 'сколько есть';
      field.dataset.id = i.id;
      field.dataset.expected = i.expected;

      const gap = el('span', 'gap');
      field.addEventListener('input', () => {
        const actual = parseFloat(field.value.replace(',', '.'));
        if (isNaN(actual)) { gap.textContent = ''; gap.className = 'gap'; return; }
        const diff = Math.round((actual - i.expected) * 1000) / 1000;
        gap.textContent = diff === 0 ? 'сходится' : (diff > 0 ? '+' : '') + diff + ' ' + i.unit_name;
        gap.className = 'gap ' + (diff === 0 ? 'ok' : diff < 0 ? 'bad' : 'warn');
      });

      return [
        esc(i.name),
        { num: `${i.expected} ${esc(i.unit_name)}` },
        { actions: field },
        { actions: gap }
      ];
    });

    wrap.appendChild(this.table(
      ['Позиция', 'Должно быть', 'Сколько есть', 'Разница'], rows));

    const save = el('button', 'btn primary', 'Записать пересчёт');
    save.addEventListener('click', async () => {
      const fields = [...document.querySelectorAll('.panel .field.slim')]
        .filter(f => f.value.trim() !== '');
      if (!fields.length) return toast('Впишите хотя бы одну позицию', 'bad');
      let done = 0;
      for (const f of fields) {
        try {
          await API.post(`/api/stock/${f.dataset.id}/move`, {
            reason: 'count',
            counted: Number(f.value.replace(',', '.')),
            note: 'инвентаризация'
          });
          done += 1;
        } catch (e) { toast(e.message, 'bad'); }
      }
      toast(`Пересчитано позиций: ${done}`, 'good');
      this.load();
    });
    wrap.appendChild(save);

    // История по месяцам: через полгода вопрос звучит не «что там сейчас», а
    // «когда расхождение началось».
    if (d.months.length) {
      wrap.appendChild(el('h2', '', 'Прошлые пересчёты'));
      const pick = el('div', 'row-actions');
      pick.style.justifyContent = 'flex-start';
      d.months.forEach(m => {
        const b = el('button', 'btn' + (m === d.month ? ' primary' : ''), this.monthName(m));
        b.addEventListener('click', () => { this.month = m; this.load(); });
        pick.appendChild(b);
      });
      wrap.appendChild(pick);

      const past = d.history.rows;
      if (past.length) {
        wrap.appendChild(this.table(
          ['Когда', 'Позиция', 'Разница', 'Кто'],
          past.map(r => [
            esc(this.stamp(r.at)),
            esc(r.name),
            `<span class="gap ${r.difference < 0 ? 'bad' : r.difference > 0 ? 'warn' : 'ok'}">`
              + `${r.difference > 0 ? '+' : ''}${r.difference} ${esc(r.unit_name)}</span>`,
            esc(r.who)
          ])
        ));
      }
    }
    return wrap;
  },

  monthName(key) {
    const [y, m] = key.split('-');
    const names = ['январь','февраль','март','апрель','май','июнь',
                   'июль','август','сентябрь','октябрь','ноябрь','декабрь'];
    return `${names[Number(m) - 1]} ${y}`;
  },

  view_audit() {
    const wrap = el('div', 'panel journal');
    wrap.appendChild(el('h2', '', 'Журнал'));
    wrap.appendChild(el('p', 'hint',
      'Кто, что и когда. Пишется на каждом действии, которое двигает деньги, '
      + 'доступ или наличие.'));

    const names = {
      'check.close': 'Чек закрыт',
      'check.discount': 'Скидка',
      'item.cancel': 'Отмена позиции',
      'item.edit': 'Правка меню',
      'item.state': 'Стоп-лист',
      'category.state': 'Стоп на раздел',
      'user.create': 'Новый сотрудник',
      'user.edit': 'Правка сотрудника',
      'user.delete': 'Сотрудник убран',
      'user.pin': 'Смена PIN',
      'user.pin_self': 'Сменил свой PIN',
      'pin.failed': 'Неверный PIN',
      'stock.move': 'Движение склада',
      'station.pin': 'PIN станции',
      'shift.open': 'Смена станции открыта',
      'shift.join': 'Встал на смену станции',
      'shift.leave': 'Ушёл со смены станции',
      'shift.close': 'Смена станции закрыта',
      'work.open': 'Смена открыта',
      'work.close': 'Смена закрыта',
      'menu.sync': 'Меню с сайта',
      'item.price_sync': 'Цена приехала с сайта',
      'item.gone': 'Позиции больше нет в меню',
      'table.edit': 'Правка стола'
    };

    wrap.appendChild(this.table(
      ['Когда', 'Кто', 'Что', 'Подробности'],
      this.data.audit.map(r => [
        `<span class="when">${esc(new Date(r.at).toLocaleString('ru-RU'))}</span>`,
        esc(r.who),
        `<span class="what">${esc(names[r.action] || r.action)}</span>`,
        `<span class="detail">${esc([this.about(r), this.detail(r)].filter(Boolean).join(' · '))}</span>`
      ])
    ));
    return wrap;
  },

  /* Журнал читают глазами, а не разбирают. Сырой JSON в строке —
     «{"delta":1000,"reason":"in"}» — это не запись о том, что случилось, а
     дамп, который приходится расшифровывать в уме. */
  /* «user:f791af6b-29c5-…» человеку не говорит ничего, а имя стоит рядом в
     подробностях. Показываем только то, что читается. */
  about(row) {
    const entity = String(row.entity || '');
    // «user:f791af6b-29c5-…» не говорит ничего, а «station:bar» повторяет то,
    // что и так написано в подробностях.
    if (/^[a-z]+:[0-9a-f]{8}-/i.test(entity)) return '';
    if (entity === 'menu' || entity.startsWith('station:')) return '';
    return entity
      .replace(/^check:/, 'чек ')
      .replace(/^item:/, '')
      .replace(/^table:/, 'стол ')
      .replace(/^stock:/, '')
      .replace(/^category:/, 'раздел ');
  },

  detail(row) {
    const words = {
      delta: 'на', reason: 'причина', note: 'заметка', name: 'имя',
      role: 'роль', state: 'состояние', price_pence: 'цена', minutes: 'минут',
      hours: 'отработано', discount_pence: 'скидка', total_pence: 'итого',
      station: 'станция', tickets: 'марок', count: 'позиций', auto: 'сама',
      payments: 'оплата', pin_length: 'длина PIN', active: 'включён'
    };
    const money2 = v => '£' + (Number(v) / 100).toFixed(2);
    const one = (key, value) => {
      if (value === null || value === undefined || value === '') return '';
      if (key === 'payments' && Array.isArray(value)) {
        return 'оплата: ' + value.map(p =>
          `${p.method === 'cash' ? 'наличные' : 'карта'} ${money2(p.amount_pence)}`).join(' + ');
      }
      if (String(key).endsWith('_pence')) return `${words[key] || key}: ${money2(value)}`;
      if (typeof value === 'boolean') return value ? (words[key] || key) : '';
      if (typeof value === 'object') return '';
      const names = {
        in: 'приход', sale: 'продажа', return: 'возврат',
        off: 'списание', count: 'инвентаризация',
        on: 'в продаже', soon: 'скоро', bar: 'бар', kitchen: 'кухня',
        waiter: 'официант', manager: 'менеджер', admin: 'администратор',
        owner: 'владелец'
      };
      return `${words[key] || key}: ${names[value] || value}`;
    };
    const flat = obj => Object.keys(obj || {})
      .map(k => one(k, obj[k])).filter(Boolean).join(', ');

    const parts = [];
    const was = flat(row.before);
    const now = flat(row.after);
    if (was) parts.push('было — ' + was);
    if (now) parts.push(was ? 'стало — ' + now : now);
    return parts.join(' · ');
  },

  /* --------------------------------------------------------- таблица ---- */
  /* Таблица кладётся в прокручиваемую коробку.
     Без неё длинная строка растягивает страницу шире экрана, браузер на
     телефоне отъезжает, чтобы всё влезло, — и кнопки становятся размером со
     спичечную головку, а шторка уезжает за край. Проверяли: «Персонал»
     разъезжался до 555 px на экране в 390. */
  /* Поле с подписью. Ряд из четырёх безымянных окошек — это загадка: в
     каком порядке заполнять и что означает третье, знает только тот, кто
     это писал. Подпись стоит одной строки кода. */
  field(label, node, hint) {
    const box = el('div', 'field-box');
    box.appendChild(el('label', '', esc(label)));
    box.appendChild(node);
    if (hint) box.appendChild(el('span', 'field-hint', esc(hint)));
    return box;
  },

  table(head, rows, classes) {
    const box = el('div', 'scroller');
    const node = el('table', 'grid');
    // Заголовок числовой колонки прижимается вправо — туда же, где стоят
    // сами числа. Иначе «ЧЕКОВ» висит над пустотой, а единица — на ладонь
    // правее, и таблица читается как набор случайных цифр.
    const numeric = head.map((h, i) =>
      rows.length > 0 && rows.every(cells => cells[i] && cells[i].num !== undefined));
    node.innerHTML = '<thead><tr>'
      + head.map((h, i) => `<th${numeric[i] ? ' class="num"' : ''}>${esc(h)}</th>`).join('')
      + '</tr></thead>';
    const body = el('tbody');
    rows.forEach((cells, n) => {
      const tr = el('tr', (classes || [])[n] || '');
      cells.forEach(cell => {
        if (cell && cell.actions) {
          const td = el('td');
          td.appendChild(cell.actions);
          tr.appendChild(td);
        } else if (cell && cell.num !== undefined) {
          tr.appendChild(el('td', 'num', String(cell.num)));
        } else {
          tr.appendChild(el('td', '', cell));
        }
      });
      body.appendChild(tr);
    });
    node.appendChild(body);
    box.appendChild(node);
    return box;
  }
};
