/* نوار پیشرفت داده آماده: وضعیت کار را هر ۲ ثانیه می‌پرسد و نوار را نرم جلو می‌برد؛ با پایان کار صفحه را تازه می‌کند. */
(() => {
  const box = document.getElementById('rd-live');
  if (!box || !box.dataset.status) return;
  const fa = n => String(n).replace(/\d/g, d => '۰۱۲۳۴۵۶۷۸۹'[d]);
  const fmt = s => (s < 60 ? fa(s) + ' ثانیه' : fa(Math.floor(s / 60)) + ' دقیقه و ' + fa(s % 60) + ' ثانیه');
  const job = Number(box.dataset.job);
  const bar = box.querySelector('.prog');
  let st = null;
  const paint = () => {
    if (!st) return;
    const cap = st.p < 60 ? Math.min(st.p + 20, 90) : st.p + 5;
    st.shown = Math.max(st.shown || 0, st.p);
    if (st.status === 'running') st.shown += (cap - st.shown) * 0.03;
    const v = Math.min(99, Math.round(st.shown));
    bar.firstElementChild.style.width = v + '%';
    bar.setAttribute('aria-valuenow', v);
    box.querySelector('.pct').textContent = fa(v);
    box.querySelector('.el').textContent = fmt(st.elapsed + Math.floor((Date.now() - st.at) / 1000));
    box.querySelector('.stage').textContent = st.status === 'queued' ? 'در صف؛ به‌زودی شروع می‌شود' : (st.stage || 'در حال شروع');
  };
  const poll = async () => {
    try {
      const r = await fetch(box.dataset.status, {credentials: 'same-origin', headers: {Accept: 'application/json'}});
      if (!r.ok) throw 0;
      const d = await r.json();
      const me = d.items.find(i => i.id === job);
      if (!me || !['queued', 'running'].includes(me.status)) { location.reload(); return; }
      st = {p: me.progress, status: me.status, stage: me.stage, elapsed: me.elapsed, at: Date.now(), shown: st && st.shown};
      paint();
    } catch (e) { /* اتصال لحظه‌ای قطع شد؛ دور بعد دوباره */ }
    setTimeout(poll, 2000);
  };
  setInterval(paint, 400);
  poll();
})();
