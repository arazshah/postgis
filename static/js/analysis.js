/* نوار پیشرفت تحلیل: وضعیت کار را هر ۲ ثانیه می‌پرسد و نوار را نرم جلو می‌برد؛ وقتی کار تمام شد صفحه را تازه می‌کند. */
(() => {
  const list = document.getElementById('hist');
  if (!list || !list.dataset.status) return;
  const fa = n => String(n).replace(/\d/g, d => '۰۱۲۳۴۵۶۷۸۹'[d]);
  const state = {};
  const fmt = s => (s < 60 ? fa(s) + ' ثانیه' : fa(Math.floor(s / 60)) + ' دقیقه و ' + fa(s % 60) + ' ثانیه');
  const paint = (li, id) => {
    const st = state[id]; if (!st) return;
    const bar = li.querySelector('.prog'); if (!bar) return;
    const cap = st.p < 60 ? Math.min(st.p + 35, 90) : st.p + 6;
    st.shown = Math.max(st.shown || 0, st.p);
    if (st.status === 'running') st.shown += (cap - st.shown) * 0.04;
    const v = Math.min(99, Math.round(st.shown));
    bar.firstElementChild.style.width = v + '%';
    bar.setAttribute('aria-valuenow', v);
    li.querySelector('.pct').textContent = fa(v);
    li.querySelector('.el').textContent = fmt(st.elapsed + Math.floor((Date.now() - st.at) / 1000));
    if (st.stage) li.querySelector('.stage').textContent = st.stage;
  };
  const tick = () => list.querySelectorAll('[data-hid]').forEach(li => paint(li, li.dataset.hid));
  const poll = async () => {
    try {
      const r = await fetch(list.dataset.status, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
      if (!r.ok) throw 0;
      const d = await r.json();
      d.items.forEach(i => { const o = state[i.id] || {};
        state[i.id] = {p: i.progress, status: i.status, stage: i.stage, elapsed: i.elapsed, at: Date.now(), shown: o.shown}; });
      if (!d.active) { location.hash = '#history'; location.reload(); return; }
    } catch (e) { /* اتصال لحظه‌ای قطع شد؛ دور بعد دوباره */ }
    setTimeout(poll, 2000);
  };
  setInterval(tick, 400);
  poll();
})();
