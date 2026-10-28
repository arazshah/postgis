// فهرست جدول‌ها در مرورگر پایگاه داده: بازشو با جست‌وجو، یا سنجاق‌شده کنار صفحه
(function () {
  "use strict";
  const layout = document.querySelector("[data-ex-layout]");
  const list = document.querySelector("[data-ex-list]");
  const toggle = document.querySelector("[data-ex-toggle]");
  if (!layout || !list || !toggle) return;
  const pinBtn = list.querySelector("[data-ex-pin]");
  const filter = list.querySelector("[data-ex-filter]");
  const none = list.querySelector(".ex-none");
  const wide = matchMedia("(min-width:901px)");

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
  };
  let pinned = store.get("gp.ex.pin") === "1";
  let open = pinned && store.get("gp.ex.open") !== "0";
  const isDocked = () => pinned && wide.matches;

  function render() {
    const docked = isDocked();
    list.hidden = !open;
    layout.classList.toggle("docked", docked && open);
    layout.classList.toggle("popover", !docked);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    pinBtn.setAttribute("aria-pressed", pinned ? "true" : "false");
    pinBtn.title = pinned ? "برداشتن سنجاق (فهرست دوباره بازشو می‌شود)" : "نمایش فهرست کنار صفحه";
    pinBtn.hidden = !wide.matches;
  }
  function setOpen(v, focus) {
    open = v;
    if (pinned) store.set("gp.ex.open", v ? "1" : "0");
    render();
    if (v && focus && filter && !isDocked()) filter.focus();
  }

  toggle.addEventListener("click", () => setOpen(!open, true));
  pinBtn.addEventListener("click", () => {
    pinned = !pinned;
    store.set("gp.ex.pin", pinned ? "1" : "0");
    if (pinned) store.set("gp.ex.open", "1");
    open = true;
    render();
  });
  wide.addEventListener("change", render);

  // بستن بازشو با کلیک بیرون یا Esc
  document.addEventListener("click", (e) => {
    if (!open || isDocked()) return;
    if (list.contains(e.target) || toggle.contains(e.target)) return;
    setOpen(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && open && !isDocked()) { setOpen(false); toggle.focus(); }
  });

  // جست‌وجوی زنده؛ Enter اولین نتیجه را باز می‌کند
  if (filter) {
    filter.addEventListener("input", () => {
      const q = filter.value.trim().toLowerCase();
      let shown = 0;
      list.querySelectorAll("li[data-name]").forEach((li) => {
        const ok = !q || li.dataset.name.includes(q);
        li.hidden = !ok;
        if (ok) shown += 1;
      });
      list.querySelectorAll("ul").forEach((ul) => {
        const prev = ul.previousElementSibling;
        const any = ul.querySelector("li:not([hidden])");
        ul.hidden = !any;
        if (prev && prev.classList.contains("ex-schema")) prev.hidden = !any;
      });
      if (none) none.hidden = shown > 0;
    });
    filter.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      const a = list.querySelector("li:not([hidden]) a");
      if (a) { e.preventDefault(); location.href = a.href; }
    });
  }

  render();
  // جدول فعلی همیشه در دید باشد
  const cur = list.querySelector("[aria-current=page]");
  if (cur && layout.classList.contains("docked")) cur.scrollIntoView({ block: "nearest" });
})();
