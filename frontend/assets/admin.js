/* ==========================================================================
   Админка: смена, персонал, столы, меню, журнал.

   Её открывают в подсобке, а не на бегу, поэтому здесь допустимы таблицы.
   Недопустимо другое: чтобы что-то менялось молча. Всё, что двигает деньги
   или доступ, попадает в журнал, и журнал открыт из того же окна.
   ========================================================================== */

const Admin = {
  me: null,
  tab: 'report',
  data: {},

  TABS: [
    { key: 'report', name: 'Смена', need: 'reports' },
    { key: 'users', name: 'Персонал', need: 'users.manage' },
    { key: 'tables', name: 'Столы', need: 'tables.manage' },
    { key: 'menu', name: 'Меню', need: 'items.edit' },
    { key: 'audit', name: 'Журнал', need: 'audit.view' }
  ],

  async start(me) {
    this.me = me;
    document.getElementById('who').textContent = me.name + ' · ' + me.role_name;
    document.getElementById('out').addEventListener('click', () => Auth.logout());

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

    Live.on('check.changed', () => { if (this.tab === 'report') this.load(); });
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
      if (this.tab === 'users') this.data.users = await API.get('/api/admin/users');
      if (this.tab === 'tables') this.data.tables = await API.get('/api/admin/tables');
      if (this.tab === 'menu') {
        this.data.menu = await API.get('/api/menu');
        this.data.sync = await API.get('/api/admin/menu/sync');
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

  /* -------------------------------------------------------- персонал ---- */
  view_users() {
    const wrap = el('div', 'panel');
    wrap.appendChild(el('h2', '', 'Персонал'));
    wrap.appendChild(el('p', 'hint',
      'Вход только по личному PIN из четырёх цифр. PIN показывается один раз — '
      + 'дальше в базе только хеш, и подсмотреть его нельзя даже отсюда.'));

    const form = el('div', 'form');
    const fields = el('div', 'line-fields');
    const name = el('input', 'field');
    name.placeholder = 'Имя';
    const role = el('select', 'field');
    [['waiter', 'Официант'], ['bar', 'Бар'], ['kitchen', 'Кухня'],
     ['manager', 'Менеджер'], ['admin', 'Администратор']].forEach(([k, n]) => {
      const o = el('option', '', esc(n));
      o.value = k;
      role.appendChild(o);
    });
    const pin = el('input', 'field');
    pin.placeholder = 'PIN (пусто — придумает сам)';
    pin.inputMode = 'numeric';
    pin.maxLength = 4;
    fields.append(name, role, pin);
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

    const toggle = el('button', 'btn ' + (user.active ? 'danger' : ''),
      user.active ? 'Отключить' : 'Включить');
    toggle.addEventListener('click', async () => {
      try {
        await API.patch(`/api/admin/users/${user.id}`, { active: !user.active });
        this.load();
      } catch (e) { toast(e.message, 'bad'); }
    });
    box.appendChild(toggle);
    return box;
  },

  showPin(user) {
    Sheet.show(esc(user.name), 'Запишите: второй раз он не покажется', body => {
      const box = el('div', 'pin-shown');
      box.innerHTML = `<div class="code">${esc(user.pin)}</div>
        <div class="note">Личный PIN. Им сотрудник входит в своё приложение.</div>`;
      body.appendChild(box);
      const ok = el('button', 'btn wide big primary', 'Записал');
      ok.addEventListener('click', () => Sheet.hide());
      body.appendChild(ok);
    });
  },

  /* ------------------------------------------------------------ столы --- */
  view_tables() {
    const wrap = el('div', 'panel');
    wrap.appendChild(el('h2', '', 'Столы'));
    wrap.appendChild(el('p', 'hint',
      'Стол с открытым чеком выключить нельзя: чек повиснет в никуда, и денег '
      + 'за него никто не возьмёт.'));

    const form = el('div', 'form');
    const fields = el('div', 'line-fields');
    const label = el('input', 'field');
    label.placeholder = 'Номер';
    const zone = el('input', 'field');
    zone.placeholder = 'Зона (Зал, Терраса…)';
    zone.value = 'Зал';
    const seats = el('input', 'field');
    seats.type = 'number';
    seats.value = '4';
    seats.min = '1';
    fields.append(label, zone, seats);
    form.appendChild(fields);

    const add = el('button', 'btn primary', 'Добавить стол');
    add.addEventListener('click', async () => {
      if (!label.value.trim()) return toast('Впишите номер', 'bad');
      try {
        await API.post('/api/admin/tables', {
          label: label.value.trim(),
          zone: zone.value.trim() || 'Зал',
          seats: Number(seats.value) || 4,
          position: Number(label.value) || 0
        });
        label.value = '';
        this.load();
      } catch (e) { toast(e.message, 'bad'); }
    });
    form.appendChild(add);
    wrap.appendChild(form);

    wrap.appendChild(this.table(
      ['Стол', 'Зона', 'Мест', 'Открытых чеков', ''],
      this.data.tables.map(t => [
        esc(t.label),
        esc(t.zone),
        { num: t.seats },
        { num: t.open_checks || '' },
        { actions: this.tableActions(t) }
      ]),
      this.data.tables.map(t => (t.active ? '' : 'off'))
    ));
    return wrap;
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

    wrap.appendChild(this.table(
      ['Позиция', 'Категория', 'Станция', 'Цена', 'Состояние', ''],
      this.data.menu.items.map(i => [
        esc(i.name),
        esc((this.data.menu.categories.find(c => c.key === i.category) || {}).name || ''),
        esc(i.station_name),
        { num: money(i.price_pence) },
        i.state === 'off' ? '<span style="color:var(--danger)">стоп</span>' : 'в продаже',
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

  /* ---------------------------------------------------------- журнал ---- */
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
      'user.create': 'Новый сотрудник',
      'user.edit': 'Правка сотрудника',
      'user.pin': 'Смена PIN',
      'pin.failed': 'Неверный PIN'
    };

    wrap.appendChild(this.table(
      ['Когда', 'Кто', 'Что', 'Подробности'],
      this.data.audit.map(r => [
        `<span class="when">${esc(new Date(r.at).toLocaleString('ru-RU'))}</span>`,
        esc(r.who),
        `<span class="what">${esc(names[r.action] || r.action)}</span>`,
        `<span class="detail">${esc(r.entity)} ${esc(this.detail(r))}</span>`
      ])
    ));
    return wrap;
  },

  detail(row) {
    const parts = [];
    if (row.before) parts.push('было: ' + JSON.stringify(row.before, null, 0));
    if (row.after) parts.push('стало: ' + JSON.stringify(row.after, null, 0));
    return parts.join(' · ');
  },

  /* --------------------------------------------------------- таблица ---- */
  table(head, rows, classes) {
    const node = el('table', 'grid');
    node.innerHTML = '<thead><tr>' + head.map(h => `<th>${esc(h)}</th>`).join('') + '</tr></thead>';
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
    return node;
  }
};
