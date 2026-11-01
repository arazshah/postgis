/* تاریخچهٔ تحلیل‌ها (کارت‌ها): نوار پیشرفت زنده، فیلتر وضعیت و تازه‌سازی بدون reload.
   وضعیت کار را هر ۲ ثانیه می‌پرسد؛ وقتی کاری تمام شد فقط بخش تاریخچه را دوباره می‌گیرد (نه کل صفحه). */
(() => {
  const wrap = () => document.getElementById('hist-wrap');
  if (!wrap()) return;
  const fa = n => String(n).replace(/\d/g, d => '۰۱۲۳۴۵۶۷۸۹'[d]);
  const state = {};
  let filter = 'all', polling = false, refreshing = false;
  const fmt = s => (s < 60 ? fa(s) + ' ثانیه' : fa(Math.floor(s / 60)) + ' دقیقه و ' + fa(s % 60) + ' ثانیه');
  const list = () => document.getElementById('hist');

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
  setInterval(() => { const l = list(); if (l) l.querySelectorAll('[data-hid]').forEach(li => paint(li, li.dataset.hid)); }, 400);

  const applyFilter = () => {
    const l = list(); if (!l) return;
    let shown = 0;
    l.querySelectorAll('.hc').forEach(li => {
      const s = li.dataset.state;
      const ok = filter === 'all' || (filter === 'done' && (s === 'done' || s === 'empty' || s === 'plan')) || filter === s;
      li.hidden = !ok; if (ok) shown++;
    });
    const none = wrap().querySelector('.hc-none'); if (none) none.hidden = shown > 0;
    wrap().querySelectorAll('[data-hf]').forEach(b => {
      const on = b.dataset.hf === filter; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
    });
  };
  document.addEventListener('click', e => {
    const b = e.target.closest && e.target.closest('[data-hf]');
    if (!b || !wrap() || !wrap().contains(b)) return;
    filter = b.dataset.hf; applyFilter();
  });

  // فقط بخش تاریخچه را عوض می‌کند؛ اگر مودالی باز است صبر می‌کند تا کاربر آن را نبندد
  const refresh = async () => {
    const w = wrap(); if (!w || refreshing) return;
    if (document.querySelector('dialog.dlg[open]')) { setTimeout(refresh, 1500); return; }
    refreshing = true;
    try {
      const r = await fetch(w.dataset.fragment, { credentials: 'same-origin', headers: { Accept: 'text/html' } });
      if (r.ok) { w.outerHTML = await r.text(); applyFilter(); }
    } catch (e) { /* دفعهٔ بعد */ }
    refreshing = false;
    const l = list(); if (l && l.dataset.active) poll();
  };

  const poll = async () => {
    const l = list();
    if (!l || !l.dataset.status || polling) return;
    polling = true;
    if (window.Notify) Notify.fast(true);
    let again = true;
    try {
      const r = await fetch(l.dataset.status, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      if (!r.ok) throw 0;
      const d = await r.json();
      d.items.forEach(i => { const o = state[i.id] || {};
        state[i.id] = { p: i.progress, status: i.status, stage: i.stage, elapsed: i.elapsed, at: Date.now(), shown: o.shown }; });
      if (!d.active) {
        again = false;
        if (window.Notify) Notify.fast(false);
        polling = false;
        refresh();
        return;
      }
    } catch (e) { /* اتصال لحظه‌ای قطع شد؛ دور بعد دوباره */ }
    polling = false;
    if (again) setTimeout(poll, 2000);
  };

  // اعلان تازه (پایان کار) از مرکز اعلان‌ها: تاریخچه تازه شود
  document.addEventListener('ntf:fresh', () => { if (!polling) refresh(); });
  const l0 = list();
  if (l0 && l0.dataset.active) poll();
  applyFilter();
})();
