/* ==========================================================================
   Клиент API и мелочи, которые нужны всем трём приложениям.

   Одна привычка проходит через весь файл: не верить одному удачному ответу.
   Сервер не ответил — показываем последнее известное состояние и честно
   говорим, что связь пропала. Молчаливый устаревший экран хуже ошибки.
   ========================================================================== */

const API = {
  async request(method, path, body) {
    const res = await fetch(path, {
      method,
      cache: 'no-store',
      credentials: 'same-origin',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) {
      const err = new Error(detailOf(data) || `${path}: ${res.status}`);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  },

  get(path, params) {
    const url = new URL(path, location.origin);
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
    });
    return this.request('GET', url.pathname + url.search);
  },

  post(path, body) { return this.request('POST', path, body); },
  patch(path, body) { return this.request('PATCH', path, body); },
  del(path) { return this.request('DELETE', path); }
};

/** Сервер отвечает ошибкой либо строкой, либо объектом с полем message. */
function detailOf(data) {
  const d = data && data.detail;
  if (!d) return null;
  if (typeof d === 'string') return d;
  if (typeof d.message === 'string') return d.message;
  return null;
}

/* ------------------------------------------------------------- мелочи --- */
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html !== undefined) n.innerHTML = html;
  return n;
};

const esc = s => String(s == null ? '' : s)
  .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/** Цена хранится в пенсах — в деньгах дробей быть не должно. */
const money = pence => '£' + (Math.round(pence) / 100).toFixed(2);

/** «3 мин», «1 ч 20 мин» — на экране важна давность, а не время суток. */
function since(iso) {
  if (!iso) return '';
  const mins = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return mins + ' мин';
  const h = Math.floor(mins / 60);
  return h + ' ч ' + (mins % 60) + ' мин';
}

/** Русские окончания: 1 гость, 2 гостя, 5 гостей. */
function plural(n, one, few, many) {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

let toastTimer = null;
function toast(text, kind, ms) {
  document.querySelectorAll('.toast').forEach(n => n.remove());
  const node = el('div', 'toast' + (kind ? ' ' + kind : ''), esc(text));
  document.body.appendChild(node);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.remove(), ms || (kind === 'bad' ? 4200 : 2400));
}

/** Короткая вибрация как подтверждение нажатия. На iOS её нет — и ладно. */
function buzz(pattern) {
  if (navigator.vibrate) { try { navigator.vibrate(pattern || 12); } catch (e) { /* нет */ } }
}
