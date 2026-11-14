// جعبه‌ابزار: جست‌وجو، دسته، سطح و «فقط آماده» بدون بارگذاری دوباره؛ و کمک‌های فرم ابزار (نام خروجی خودکار)
(() => {
  const norm = (s) => String(s).toLowerCase().replace(/[يى]/g, 'ی').replace(/ك/g, 'ک').replace(/[‌‏]/g, ' ');
  const fa = (n) => String(n).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);

  const root = document.querySelector('[data-tb]');
  if (root) {
    const q = root.querySelector('[data-tb-q]');
    const tiles = Array.from(root.querySelectorAll('.tb-main .tb-group .tb-tile'));
    const groups = Array.from(root.querySelectorAll('.tb-group'));
    const feat = root.querySelector('[data-tb-feat]');
    const none = root.querySelector('[data-tb-none]');
    const ready = root.querySelector('[data-tb-ready]');
    const st = { cat: 'all', level: 'all' };
    const apply = () => {
      const term = norm(q.value.trim());
      const counts = {}; let shown = 0;
      tiles.forEach((t) => {
        const base = (st.level === 'all' || t.dataset.level === st.level) && (!ready.checked || t.dataset.ready === '1')
          && (!term || norm(t.dataset.text).includes(term));
        counts[t.dataset.cat] = (counts[t.dataset.cat] || 0) + (base ? 1 : 0);
        const ok = base && (st.cat === 'all' || t.dataset.cat === st.cat);
        t.hidden = !ok; if (ok) shown++;
      });
      groups.forEach((g) => { g.hidden = !g.querySelector('.tb-tile:not([hidden])'); });
      if (feat) feat.hidden = !!term || st.cat !== 'all' || st.level !== 'all' || ready.checked;
      if (none) none.hidden = shown > 0;
      root.querySelectorAll('[data-tb-n]').forEach((b) => {
        b.textContent = fa(b.dataset.tbN === 'all' ? Object.values(counts).reduce((a, c) => a + c, 0) : (counts[b.dataset.tbN] || 0));
      });
    };
    q.addEventListener('input', apply);
    ready.addEventListener('change', apply);
    const pick = (attr, key, cls) => root.querySelectorAll(`[${attr}]`).forEach((b) => b.addEventListener('click', () => {
      st[key] = b.getAttribute(attr);
      root.querySelectorAll(`[${attr}]`).forEach((x) => { const on = x === b; x.classList.toggle(cls, on); x.setAttribute('aria-pressed', on); });
      apply();
    }));
    root.querySelectorAll('[data-tb-cat]').forEach((b) => b.addEventListener('click', () => {
      st.cat = b.dataset.tbCat;
      root.querySelectorAll('[data-tb-cat]').forEach((x) => { const on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-pressed', on); });
      apply();
    }));
    pick('data-tb-level', 'level', 'on');
    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && !/^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName)) { e.preventDefault(); q.focus(); }
    });
    apply();
  }

  // فرم ابزار: نام خروجی را تا وقتی کاربر دستی ننوشته از نام لایه و ابزار پر می‌کند
  const out = document.getElementById('f-output');
  const form = document.querySelector('.tl-form');
  if (out && form) {
    const first = form.querySelector('select[name=layer]');
    const key = out.dataset.tool || 'result';
    let touched = out.dataset.touched === '1';
    out.addEventListener('input', () => { touched = true; });
    const sync = () => {
      if (touched || !first || !first.value) return;
      const n = first.value.split('.').pop().toLowerCase().replace(/[^a-z0-9_]/g, '');
      if (/^[a-z_]/.test(n)) out.value = (n + '_' + key).slice(0, 60);
    };
    if (first) first.addEventListener('change', sync);
    const adv = form.querySelector('details.tl-adv');
    if (adv && adv.querySelector('.err')) adv.open = true;
  }
})();
