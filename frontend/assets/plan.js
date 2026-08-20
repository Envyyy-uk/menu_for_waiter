/* ==========================================================================
   План зала.

   Общий кусок для админки и зала: рисует столы по координатам в процентах.
   Проценты, а не пиксели, — потому что план расставляют на ноутбуке, а
   работают по нему с телефона, и стол у окна должен остаться у окна.

   Перетаскивание живёт здесь же: в админке оно включается, у официанта нет —
   стол, случайно сдвинутый на бегу, это чужая расстановка на весь вечер.
   ========================================================================== */

const Plan = {
  /** Столы одной зоны в порядке, в котором их рисовать. */
  inZone(tables, zone) {
    return tables.filter(t => (t.zone || 'Зал') === zone);
  },

  zones(tables) {
    const seen = [];
    tables.forEach(t => {
      const zone = t.zone || 'Зал';
      if (!seen.includes(zone)) seen.push(zone);
    });
    return seen.length ? seen : ['Зал'];
  },

  /** Место стола. Без координат — раскладываем рядами, чтобы новый стол не
      прятался в углу под уже стоящим. */
  spot(table, index) {
    if (table.x !== null && table.x !== undefined) return { x: table.x, y: table.y };
    const row = Math.floor(index / 4);
    const column = index % 4;
    return { x: 14 + column * 24, y: 14 + row * 20 };
  },

  place(node, spot) {
    node.style.left = spot.x + '%';
    node.style.top = spot.y + '%';
  },

  /** Перетаскивание с прилипанием к сетке: ровный зал читается быстрее
      кривого, а попасть пальцем в ровную сетку проще. */
  drag(field, node, onDrop) {
    let moved = false;

    node.addEventListener('pointerdown', down => {
      if (!field.classList.contains('editing')) return;
      down.preventDefault();
      node.setPointerCapture(down.pointerId);
      node.classList.add('dragging');
      moved = false;

      const move = e => {
        const box = field.getBoundingClientRect();
        const x = clamp(((e.clientX - box.left) / box.width) * 100);
        const y = clamp(((e.clientY - box.top) / box.height) * 100);
        moved = true;
        Plan.place(node, { x: snap(x), y: snap(y) });
      };

      const up = e => {
        node.releasePointerCapture(down.pointerId);
        node.classList.remove('dragging');
        node.removeEventListener('pointermove', move);
        node.removeEventListener('pointerup', up);
        node.removeEventListener('pointercancel', up);
        if (moved) {
          onDrop({
            x: parseFloat(node.style.left),
            y: parseFloat(node.style.top)
          });
        } else if (node.dataset.tap) {
          // Не сдвинули — значит, нажали. Разделять это по времени нельзя:
          // палец всегда чуть уезжает.
          node.dispatchEvent(new CustomEvent('plan-tap'));
        }
      };

      node.addEventListener('pointermove', move);
      node.addEventListener('pointerup', up);
      node.addEventListener('pointercancel', up);
    });
  }
};

const clamp = v => Math.max(4, Math.min(96, v));
const snap = v => Math.round(v / 2) * 2;
