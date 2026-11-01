// گالری ابزارها: جست‌وجو و فیلتر دسته بدون بارگذاری دوباره
(() => {
  const root = document.querySelector('[data-tl]');
  if (!root) return;
  const q = root.querySelector('[data-tl-q]');
  const cards = Array.from(root.querySelectorAll('.tl-card'));
  const groups = Array.from(root.querySelectorAll('.tl-group'));
  const none = root.querySelector('.tl-none');
  let cat = 'all';
  const norm = (s) => String(s).toLowerCase().replace(/[يى]/g, 'ی').replace(/ك/g, 'ک');
  const apply = () => {
    const term = norm(q ? q.value.trim() : '');
    let shown = 0;
    cards.forEach((c) => {
      const ok = (cat === 'all' || c.dataset.cat === cat) && (!term || norm(c.dataset.text).includes(term));
      c.hidden = !ok; if (ok) shown++;
    });
    groups.forEach((g) => { g.hidden = !g.querySelector('.tl-card:not([hidden])'); });
    if (none) none.hidden = shown > 0;
  };
  if (q) q.addEventListener('input', apply);
  root.querySelectorAll('[data-tl-cat]').forEach((b) => b.addEventListener('click', () => {
    cat = b.dataset.tlCat;
    root.querySelectorAll('[data-tl-cat]').forEach((x) => { const on = x === b; x.classList.toggle('on', on); x.setAttribute('aria-pressed', on); });
    apply();
  }));
})();
