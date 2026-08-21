/* ==========================================================================
   Шторки снизу: варианты позиции и оплата.

   Снизу — потому что до низа экрана большой палец дотягивается, а до верха
   нет. Фон закрывается нажатием: выйти из шторки должно быть так же легко,
   как в неё попасть.
   ========================================================================== */

const Sheet = {
  show(title, sub, build) {
    this.hide();
    // Всплывашка от прошлого действия не должна висеть поверх шторки.
    document.querySelectorAll('.toast').forEach(n => n.remove());
    const bg = el('div', 'sheet-bg');
    bg.id = 'sheet-bg';
    // Закрываем по нажатию, а не по click. После тапа пальцем браузер шлёт
    // ещё и «призрачный» click теми же координатами — а там уже лежит фон
    // только что открывшейся шторки. Карточка стола открывалась и тут же
    // пропадала: со стороны это выглядело как «нажатие не работает».
    bg.addEventListener('pointerdown', e => { e.preventDefault(); this.hide(); });

    const sheet = el('div', 'sheet');
    sheet.id = 'sheet';
    sheet.innerHTML = `<h2>${title}</h2>` + (sub ? `<p class="sub">${sub}</p>` : '');
    const body = el('div');
    sheet.appendChild(body);

    document.body.append(bg, sheet);
    build(body, sheet);
  },

  hide() {
    ['sheet-bg', 'sheet'].forEach(id => {
      const n = document.getElementById(id);
      if (n) n.remove();
    });
  }
};

/* Сколько выборов в группе идут в цене. Правило приходит из каталога:
   «к бутылке два микса бесплатно» — это условие на другой выбор, а не
   свойство самого микса. */
function freeCount(group, chosen) {
  const rule = group.free;
  if (!rule || !rule.count) return 0;
  const when = rule.when || {};
  return Object.keys(when).every(k => chosen[k] === when[k]) ? rule.count : 0;
}

/* ------------------------------------------------------------ варианты --- */
/* Цену считает сервер. Здесь она показывается, чтобы официант назвал её
   гостю до отправки, но в запрос уходит только выбор. */
const Options = {
  open(item, done) {
    const chosen = {};
    let qty = 1;

    Sheet.show(esc(item.name), esc(item.description || ''), (body, sheet) => {
      const price = el('div', 'totals');
      const foot = el('div');

      const redraw = () => {
        body.innerHTML = '';
        (item.options || []).forEach(group => {
          // Группа с условием показывается, только когда оно выполнено:
          // марку дарк-лифа не спрашивают у того, кто взял сигарный лист.
          if (group.depends && chosen[group.depends.group] !== group.depends.value) {
            delete chosen[group.key];
            return;
          }
          const block = el('div', 'group');
          block.appendChild(el('h3', '', esc(group.label)
            + (group.required ? '' : ' <span class="faint">— по желанию</span>')));
          // Группа с несколькими выборами — не кнопки, которые тыкают по
          // кругу. Там счётчик: «минус, два, плюс». Круговой тык означает
          // «промахнулся — начинай сначала», а официант в это время считает
          // вслух гостю.
          if (group.mode === 'many') {
            block.appendChild(this.counters(group, chosen, redraw));
            body.appendChild(block);
            return;
          }

          const row = el('div', 'opts');

          group.choices.forEach(choice => {
            const many = group.mode === 'many';
            const picks = many ? (chosen[group.key] || []) : chosen[group.key];
            const count = many ? picks.filter(p => p === choice.key).length : 0;
            const on = many ? count > 0 : picks === choice.key;

            const add = (choice.add_pence || 0) + (group.add_pence || 0);
            const btn = el('button', 'opt' + (on ? ' on' : ''));
            btn.innerHTML = esc(choice.name)
              + (count > 1 ? ` ×${count}` : '')
              + (choice.price_pence !== undefined && choice.price_pence !== null
                  ? ` <span class="add">${money(choice.price_pence)}</span>`
                  : add ? ` <span class="add">+${money(add)}</span>` : '');

            btn.addEventListener('click', () => {
              buzz();
              if (!many) {
                chosen[group.key] = on ? undefined : choice.key;
                if (chosen[group.key] === undefined) delete chosen[group.key];
              } else {
                const list = chosen[group.key] || [];
                const limit = choice.max_qty || 1;
                const have = list.filter(p => p === choice.key).length;
                const rest = list.filter(p => p !== choice.key);
                // Нажатие добавляет ещё один, после предела — сбрасывает.
                // Два микса к бутылке это одна строка чека, а не две.
                const next = have >= limit ? 0 : have + 1;
                chosen[group.key] = rest.concat(Array(next).fill(choice.key));
                if (!chosen[group.key].length) delete chosen[group.key];
              }
              redraw();
            });
            row.appendChild(btn);
          });
          block.appendChild(row);
          body.appendChild(block);
        });

        body.appendChild(price);
        body.appendChild(foot);
        paintPrice();
      };

      const paintPrice = () => {
        const { total, missing } = this.calc(item, chosen);
        price.innerHTML =
          `<div class="row big"><span>${qty}× по</span><span>${money(total)}</span></div>`
          + (missing ? `<div class="row"><span class="muted">Выберите: ${esc(missing)}</span><span></span></div>` : '');

        foot.innerHTML = '';
        const row = el('div', 'stepper');
        const minus = el('button', '', '−');
        const value = el('span', 'n', String(qty));
        const plus = el('button', '', '+');
        minus.addEventListener('click', () => { qty = Math.max(1, qty - 1); value.textContent = qty; buzz(); paintPrice(); });
        plus.addEventListener('click', () => { qty = Math.min(99, qty + 1); value.textContent = qty; buzz(); paintPrice(); });
        row.append(minus, value, plus);
        foot.appendChild(row);
        foot.appendChild(el('div', '', '<div style="height:14px"></div>'));

        const ok = el('button', 'btn wide big primary',
          missing ? 'Выберите вариант' : `Добавить · ${money(total * qty)}`);
        if (missing) ok.disabled = true;
        ok.addEventListener('click', () => { Sheet.hide(); done(chosen, qty); });
        foot.appendChild(ok);
      };

      redraw();
    });
  },

  /* Ряды со счётчиком: слева название, справа «− 2 +». Пока не выбрано,
     справа одна кнопка «+», и ряд не шумит. */
  counters(group, chosen, redraw) {
    const box = el('div', 'counters');
    const list = () => chosen[group.key] || [];

    const setCount = (key, next) => {
      const rest = list().filter(p => p !== key);
      const value = rest.concat(Array(Math.max(0, next)).fill(key));
      if (value.length) chosen[group.key] = value;
      else delete chosen[group.key];
      buzz();
      redraw();
    };

    // Сколько уже включено в цену: к бутылке два микса бесплатно, и считать
    // это в уме официант не должен.
    const free = freeCount(group, chosen);
    let left = Math.min(free, list().length);

    group.choices.forEach(choice => {
      const count = list().filter(p => p === choice.key).length;
      const limit = choice.max_qty || 1;
      const add = (choice.add_pence || 0) + (group.add_pence || 0);
      const covered = Math.min(left, count);
      left -= covered;

      const row = el('div', 'counter' + (count ? ' on' : ''));
      row.appendChild(el('span', 'nm', esc(choice.name)
        + (add
            ? ` <span class="add">${count && covered === count ? 'в цене' : '+' + money(add)}</span>`
            : '')));

      const grip = el('span', 'grip');
      if (count) {
        const minus = el('button', 'step', '−');
        minus.addEventListener('click', () => setCount(choice.key, count - 1));
        grip.append(minus, el('span', 'n', String(count)));
      }
      const plus = el('button', 'step', '+');
      plus.disabled = count >= limit;
      plus.addEventListener('click', () => setCount(choice.key, count + 1));
      grip.appendChild(plus);
      row.appendChild(grip);
      box.appendChild(row);
    });

    if (free) {
      box.appendChild(el('p', 'faint', `Первые ${free} — в цене.`));
    }
    return box;
  },

  /** Та же арифметика, что на сервере, — но только чтобы показать цену.
      Настоящую считает сервер: браузеру верить нельзя. */
  calc(item, chosen) {
    let price = item.price_pence;
    let add = 0;
    const missing = [];

    (item.options || []).forEach(group => {
      if (group.depends && chosen[group.depends.group] !== group.depends.value) return;
      const picked = chosen[group.key];
      if (group.mode === 'many') {
        // Бесплатными уходят самые дорогие: гостю так честнее. Настоящую
        // цену всё равно считает сервер, здесь — чтобы назвать её вслух.
        const prices = (picked || [])
          .map(key => (group.choices.find(c => c.key === key) || {}).add_pence || 0)
          .sort((a, b) => b - a);
        prices.slice(Math.min(freeCount(group, chosen), prices.length))
          .forEach(p => { add += p; });
        if ((picked || []).length) add += group.add_pence || 0;
        return;
      }
      if (!picked) {
        if (group.required) missing.push(group.label);
        return;
      }
      const choice = group.choices.find(c => c.key === picked);
      if (!choice) return;
      if (choice.price_pence !== undefined && choice.price_pence !== null) price = choice.price_pence;
      add += (choice.add_pence || 0) + (group.add_pence || 0);
    });

    return { total: price + add, missing: missing.join(', ') };
  }
};

/* --------------------------------------------------------------- оплата -- */
const Pay = {
  open(check) {
    const due = check.due_pence;
    Sheet.show('Оплата', `Стол ${esc(check.table)} · чек №${check.number}`, body => {
      body.appendChild(this.summary(check));

      const card = el('button', 'btn wide big primary', `Карта · ${money(due)}`);
      card.addEventListener('click', () => this.close(check, [{ method: 'card', amount_pence: due }]));

      const cash = el('button', 'btn wide big', `Наличные · ${money(due)}`);
      cash.addEventListener('click', () => this.cash(check));

      const split = el('button', 'btn wide big ghost', 'Пополам: карта и наличные');
      split.addEventListener('click', () => this.split(check));

      [card, cash, split].forEach(b => {
        body.appendChild(b);
        body.appendChild(el('div', '', '<div style="height:8px"></div>'));
      });

      // Скидка живёт здесь, а не в чеке: её дают перед тем, как назвать
      // сумму. После закрытия чек уже документ, и править его нечем.
      if (Auth.can('checks.discount')) {
        const off = el('button', 'btn wide ghost',
          check.discount_pence ? `Скидка · −${money(check.discount_pence)}` : 'Скидка');
        off.addEventListener('click', () => this.discount(check));
        body.appendChild(off);
      }
    });
  },

  /* Скидку даёт менеджер и не молча: причина остаётся на чеке и видна потом
     в оплатах. Скидка без причины — просто минус в кассе, и разбираться с
     ней через неделю будет некому. */
  discount(check) {
    const sum = check.subtotal_pence;
    Sheet.show('Скидка', `Позиции ${money(sum)}`, body => {
      let value = check.discount_pence || 0;

      const shown = el('p', 'sub');
      const paint = () => {
        shown.innerHTML = value
          ? `Скидка <b>−${money(value)}</b> · к оплате <b>${money(Math.max(0, sum - value))}</b>`
          : 'Скидки нет';
      };

      // Ползунок, а не четыре кнопки: скидку называют в процентах и любую —
      // «десять» и «пятьдесят» одинаково законны. Шаг в пять процентов
      // потому, что скидки в три процента не бывает, а промахнуться пальцем
      // по проценту легко.
      const pc = el('div', 'percent');
      const bar = el('input', 'range');
      bar.type = 'range';
      bar.min = '0';
      bar.max = '100';
      bar.step = '5';
      bar.value = sum ? String(Math.round((value / sum) * 20) * 5) : '0';
      const mark = el('span', 'pc', bar.value + '%');
      pc.append(bar, mark);
      body.appendChild(pc);

      bar.addEventListener('input', () => {
        mark.textContent = bar.value + '%';
        value = Math.round(sum * Number(bar.value) / 100);
        input.value = (value / 100).toFixed(2);
        paint();
      });
      body.appendChild(el('div', '', '<div style="height:10px"></div>'));

      const input = el('input', 'field');
      input.type = 'text';
      input.inputMode = 'decimal';
      input.placeholder = 'Своя сумма, £';
      if (value) input.value = (value / 100).toFixed(2);
      input.addEventListener('input', () => {
        value = Math.round(parseFloat((input.value || '0').replace(',', '.')) * 100) || 0;
        // Ползунок идёт следом: две цифры об одном не должны спорить.
        bar.value = sum ? String(Math.min(100, Math.round((value / sum) * 20) * 5)) : '0';
        mark.textContent = bar.value + '%';
        paint();
      });
      body.appendChild(input);
      body.appendChild(shown);
      paint();

      const why = el('input', 'field');
      why.placeholder = 'Причина: постоянный гость, ждали долго…';
      if (check.discount_reason) why.value = check.discount_reason;
      body.appendChild(why);
      body.appendChild(el('div', '', '<div style="height:12px"></div>'));

      const save = el('button', 'btn wide big primary', 'Применить');
      save.addEventListener('click', () => {
        if (value > sum) return toast('Скидка больше суммы чека', 'bad');
        this.applyDiscount(check, value, why.value.trim());
      });
      body.appendChild(save);

      if (check.discount_pence) {
        body.appendChild(el('div', '', '<div style="height:8px"></div>'));
        const drop = el('button', 'btn wide ghost', 'Убрать скидку');
        drop.addEventListener('click', () => this.applyDiscount(check, 0, ''));
        body.appendChild(drop);
      }
    });
  },

  async applyDiscount(check, pence, reason) {
    try {
      const updated = await API.post(`/api/checks/${check.id}/discount`,
        { discount_pence: pence, reason: reason || null });
      App.check = updated;
      App.paint();
      toast(pence ? 'Скидка применена' : 'Скидка убрана', 'good');
      this.open(updated);
    } catch (e) { toast(e.message, 'bad'); }
  },

  summary(check) {
    const box = el('div', 'totals');
    box.innerHTML =
      `<div class="row"><span class="muted">Позиции</span><span>${money(check.subtotal_pence)}</span></div>`
      + (check.discount_pence ? `<div class="row off"><span>Скидка</span><span>−${money(check.discount_pence)}</span></div>` : '')
      + `<div class="row big"><span>К оплате</span><span>${money(check.due_pence)}</span></div>`;
    return box;
  },

  /* Сдачу считает касса, а не официант в уме на глазах у гостя. */
  cash(check) {
    const due = check.due_pence;
    Sheet.show('Наличные', `К оплате ${money(due)}`, body => {
      const input = el('input', 'field');
      input.type = 'text';
      input.inputMode = 'decimal';
      input.placeholder = 'Сколько дали, £';
      body.appendChild(input);

      const change = el('p', 'muted');
      change.style.margin = '10px 2px';
      body.appendChild(change);

      const round = [due, Math.ceil(due / 1000) * 1000, Math.ceil(due / 2000) * 2000, Math.ceil(due / 5000) * 5000];
      const quick = el('div', 'opts');
      [...new Set(round)].forEach(sum => {
        const b = el('button', 'opt', money(sum));
        b.addEventListener('click', () => { input.value = (sum / 100).toFixed(2); recount(); });
        quick.appendChild(b);
      });
      body.appendChild(quick);
      body.appendChild(el('div', '', '<div style="height:12px"></div>'));

      const ok = el('button', 'btn wide big ok', `Принял ${money(due)}`);
      body.appendChild(ok);

      const recount = () => {
        const given = Math.round(parseFloat((input.value || '0').replace(',', '.')) * 100);
        if (!given || given < due) { change.textContent = ''; return; }
        change.innerHTML = `Сдача: <b style="color:var(--ok)">${money(given - due)}</b>`;
      };
      input.addEventListener('input', recount);

      ok.addEventListener('click', () => {
        const given = Math.round(parseFloat((input.value || '0').replace(',', '.')) * 100);
        this.close(check, [{
          method: 'cash',
          amount_pence: due,
          tendered_pence: given >= due ? given : due
        }]);
      });
    });
  },

  split(check) {
    const due = check.due_pence;
    let card = Math.round(due / 2);
    Sheet.show('Пополам', `Всего ${money(due)}`, body => {
      const input = el('input', 'field');
      input.type = 'text';
      input.inputMode = 'decimal';
      input.value = (card / 100).toFixed(2);
      body.appendChild(el('p', 'sub', 'Сколько по карте — остальное наличными'));
      body.appendChild(input);

      const rest = el('p', 'muted');
      rest.style.margin = '10px 2px';
      body.appendChild(rest);
      body.appendChild(el('div', '', '<div style="height:12px"></div>'));

      const ok = el('button', 'btn wide big ok', 'Закрыть чек');
      body.appendChild(ok);

      const recount = () => {
        card = Math.round(parseFloat((input.value || '0').replace(',', '.')) * 100);
        const cash = due - card;
        const bad = !(card > 0 && cash > 0);
        rest.innerHTML = bad
          ? '<span style="color:var(--danger)">Обе части должны быть больше нуля</span>'
          : `Карта ${money(card)} · наличные ${money(cash)}`;
        ok.disabled = bad;
      };
      input.addEventListener('input', recount);
      recount();

      ok.addEventListener('click', () => this.close(check, [
        { method: 'card', amount_pence: card },
        { method: 'cash', amount_pence: due - card }
      ]));
    });
  },

  async close(check, payments) {
    buzz(30);
    try {
      await API.post(`/api/checks/${check.id}/close`, { payments });
      Sheet.hide();
      toast('Чек закрыт', 'good');
      App.check = null;
      App.go('tables');
      App.refresh();
    } catch (e) {
      toast(e.message, 'bad');
    }
  }
};
