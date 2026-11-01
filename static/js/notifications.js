// مرکز اعلان‌ها: زنگ هدر، toast بالای صفحه، مودال خطا، هشدار قطع اتصال و تبدیل پیام‌های Django به toast/مودال.
// API: Notify.toast(level, title, body), Notify.error({title, body, detail, url, action}), Notify.fast(bool)
(function () {
  "use strict";
  const bell = document.getElementById("ntf-bell");
  if (!bell) return;
  const URLS = { poll: bell.dataset.poll, read: bell.dataset.read, log: bell.dataset.log };
  const KEY = "ntf_after";
  const PATHS = {
    success: '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.8 2.8L16 9.5"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    warning: '<path d="M12 4 3 20h18z"/><path d="M12 10v4M12 17h.01"/>',
    error: '<circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
  };
  const svg = (k, s) => `<svg viewBox="0 0 24 24" width="${s || 20}" height="${s || 20}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[k] || PATHS.info}</svg>`;
  const fa = (n) => String(n).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const csrf = () => (document.cookie.match(/(?:^|; )csrftoken=([^;]+)/) || [])[1] || "";
  const store = {
    get() { try { return sessionStorage.getItem(KEY) || ""; } catch (e) { return ""; } },
    set(v) { try { sessionStorage.setItem(KEY, String(v)); } catch (e) { /* حالت خصوصی */ } },
  };
  const post = (url, data) => fetch(url, {
    method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrf(), Accept: "application/json" },
    body: new URLSearchParams(data || {}),
  }).then((r) => r.json()).catch(() => null);

  // ---------- toast ----------
  let host = null;
  function toast(level, title, body, opts) {
    opts = opts || {};
    if (!host) { host = document.createElement("div"); host.className = "nt-toasts"; host.setAttribute("aria-live", "polite"); document.body.append(host); }
    const t = document.createElement("div");
    t.className = `nt-toast nt-${level}`;
    t.setAttribute("role", level === "error" || level === "warning" ? "alert" : "status");
    t.innerHTML = `<span class="nt-ico">${svg(level)}</span><div class="nt-txt"><b>${esc(title)}</b>${body ? `<span>${esc(body)}</span>` : ""}</div>` +
      (opts.url ? `<a class="nt-go" href="${esc(opts.url)}">${esc(opts.action || "مشاهده")}</a>` : "") +
      `<button type="button" class="nt-x" aria-label="بستن">${svg("close", 16)}</button>`;
    const kill = () => { t.classList.remove("in"); setTimeout(() => t.remove(), 220); };
    t.querySelector(".nt-x").addEventListener("click", kill);
    host.prepend(t);
    while (host.children.length > 4) host.lastElementChild.remove();
    requestAnimationFrame(() => t.classList.add("in"));
    if (!opts.sticky) setTimeout(kill, opts.ms || (level === "error" || level === "warning" ? 9000 : 6000));
    return { close: kill, el: t };
  }

  // ---------- مودال خطا / هشدار ----------
  let modalChain = Promise.resolve();
  function modal(n) {
    modalChain = modalChain.then(() => {
      if (!window.Ui) { toast(n.level, n.title, n.body, n); return null; }
      const body = Ui.el("div", { class: "ui-stack nt-modal" }, n.body && Ui.el("p", { class: "ui-msg" }, n.body));
      if (n.detail && n.detail !== n.body) {
        body.append(Ui.el("details", { class: "nt-detail" }, Ui.el("summary", {}, "جزئیات فنی"), Ui.el("pre", { class: "ltr" }, n.detail)));
      }
      const actions = [{ label: "بستن", value: false, variant: "ghost" }];
      if (n.url) actions.push({ label: n.action || "مشاهده", value: true, variant: "primary" });
      return Ui.dialog({
        title: n.title, kind: n.level === "error" ? "danger" : "warn", body, size: "md", dismissValue: false, actions,
      }).then((go) => { if (go && n.url) location.href = n.url; });
    });
    return modalChain;
  }
  function error(n) { return modal(Object.assign({ level: "error" }, n)); }

  // ---------- زنگ و پنل ----------
  const badge = document.getElementById("ntf-badge");
  const panel = document.getElementById("pop-ntf");
  const list = document.getElementById("ntf-list");
  function setUnread(n) {
    if (!badge) return;
    badge.textContent = n > 99 ? "۹۹+" : fa(n);
    badge.hidden = !n;
    bell.setAttribute("aria-label", n ? `اعلان‌ها، ${fa(n)} خوانده‌نشده` : "اعلان‌ها");
  }
  const ago = (iso) => {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return "هم‌اکنون";
    if (s < 3600) return `${fa(Math.floor(s / 60))} دقیقه پیش`;
    if (s < 86400) return `${fa(Math.floor(s / 3600))} ساعت پیش`;
    return `${fa(Math.floor(s / 86400))} روز پیش`;
  };
  function renderList(items) {
    if (!list) return;
    if (!items.length) {
      list.innerHTML = '<div class="ntf-empty"><span class="nt-ico nt-info">' + svg("info", 22) + '</span><b>اعلانی ندارید</b><span>پایان تحلیل‌ها، دریافت‌ها و خطاها اینجا جمع می‌شود.</span></div>';
      return;
    }
    list.innerHTML = items.map((n) => {
      const inner = `<span class="nt-ico nt-${n.level}">${svg(n.level, 18)}</span><span class="ntf-t"><b>${esc(n.title)}</b>${n.body ? `<span>${esc(n.body)}</span>` : ""}<time>${ago(n.at)}</time></span>`;
      const cls = `ntf-row${n.read ? "" : " new"}`;
      return n.url ? `<a class="${cls}" role="menuitem" href="${esc(n.url)}">${inner}</a>` : `<div class="${cls}">${inner}</div>`;
    }).join("");
  }
  let panelOpen = false;
  async function openPanel() {
    const d = await fetchPoll(true);
    if (d && d.items) renderList(d.items);
    panelOpen = true;
    setTimeout(async () => { const r = await post(URLS.read); if (r) setUnread(r.unread); }, 1200);
  }
  // باز و بسته شدن پنل را shell.js با aria-expanded انجام می‌دهد؛ همان را زیر نظر می‌گیریم
new MutationObserver(() => { if (bell.getAttribute("aria-expanded") === "true") openPanel(); else panelOpen = false; })
    .observe(bell, { attributes: true, attributeFilter: ["aria-expanded"] });
  const markAll = document.getElementById("ntf-readall");
  if (markAll) markAll.addEventListener("click", async () => { const r = await post(URLS.read); if (r) { setUnread(r.unread); list && list.querySelectorAll(".new").forEach((x) => x.classList.remove("new")); } });

  // ---------- poll ----------
  let timer = 0, fast = false, fails = 0, offlineToast = null;
  async function fetchPoll(withPanel) {
    const after = store.get();
    const q = new URLSearchParams();
    if (after) q.set("after", after);
    if (withPanel) q.set("panel", "1");
    try {
      const r = await fetch(`${URLS.poll}?${q}`, { credentials: "same-origin", headers: { Accept: "application/json" } });
      if (r.status === 401 || r.status === 403 || r.redirected) throw new Error("auth");
      if (!r.ok) throw new Error("http");
      const d = await r.json();
      if (fails >= 2 && offlineToast) { offlineToast.close(); offlineToast = null; toast("success", "ارتباط دوباره برقرار شد", "اعلان‌ها و پیشرفت تحلیل‌ها به‌روز می‌شود."); }
      fails = 0;
      return d;
    } catch (e) {
      fails += 1;
      if (fails === 2 && !offlineToast) {
        offlineToast = toast("warning", "ارتباط با سرور قطع شد",
          "پیشرفت کارها روی سرور ادامه دارد؛ به‌محض وصل شدن، نتیجه اینجا اعلام می‌شود.", { sticky: true });
      }
      return null;
    }
  }
  function handle(d) {
    if (!d) return;
    setUnread(d.unread);
    const fresh = d.fresh || [];
    const top = fresh.length ? fresh[fresh.length - 1].id : d.latest;
    if (!store.get() || top > Number(store.get() || 0)) store.set(top);
    let shownModals = 0;
    fresh.forEach((n) => {
      if (n.level === "error" || n.level === "warning") {
        if (shownModals < 2) { shownModals += 1; modal(n); post(URLS.read, { id: n.id }); } else toast(n.level, n.title, n.body, n);
      } else toast(n.level, n.title, n.body, n);
    });
    if (fresh.length) document.dispatchEvent(new CustomEvent("ntf:fresh", { detail: fresh }));
  }
  async function tick() {
    clearTimeout(timer);
    if (!document.hidden) {
      const d = await fetchPoll(false);
      if (d) handle(d);
    }
    timer = setTimeout(tick, fails >= 2 ? 15000 : fast ? 3000 : 12000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });
  window.addEventListener("offline", () => { if (!offlineToast) offlineToast = toast("warning", "اینترنت شما قطع شد", "پس از وصل شدن، اعلان‌ها دوباره بررسی می‌شود.", { sticky: true }); fails = 2; });
  window.addEventListener("online", () => { fails = 2; tick(); });

  // ---------- پیام‌های Django ----------
  function flash() {
    const ul = document.querySelector("ul.messages[data-flash]");
    if (!ul) return;
    ul.querySelectorAll("li").forEach((li) => {
      const text = li.textContent.trim();
      const tags = li.className;
      const level = /error/.test(tags) ? "error" : /warning/.test(tags) ? "warning" : /success/.test(tags) ? "success" : "info";
      if (!text) return;
      if (level === "error" || level === "warning") {
        const title = level === "error" ? "انجام نشد" : "توجه";
        modal({ level, title, body: text });
        post(URLS.log, { level, title: text.slice(0, 160), body: text });
      } else toast(level, text);
    });
  }

  window.Notify = { toast, error, fast(v) { fast = !!v; tick(); } };
  flash();
  tick();
})();
