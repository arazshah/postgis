// دستیار هوشمند: دکمه شناور پایین‌چپ و پنجره گفتگو؛ بدون کتابخانه خارجی و بدون innerHTML (همه گره‌ها با DOM ساخته می‌شوند)
(function () {
  "use strict";
  const script = document.currentScript;
  if (!script) return;
  const URLS = { config: script.dataset.config, ask: script.dataset.ask, feedback: script.dataset.feedback, kb: script.dataset.kb };
  const STORE = "gp-assistant-v1";
  const MAX_KEEP = 12;
  let cfg = null, panel, log, input, sendBtn, fab, busy = false, history = [], csrf = "";

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function safeHref(h) { return /^\/(?!\/)/.test(h) || /^https:\/\//i.test(h); }

  // ---- نمایش متن پاسخ (نشانه‌گذاری ساده): پاراگراف، فهرست، **درشت**، `کد`، [n] و [متن](آدرس)
  const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[(\d{1,2})\]|\[[^\]]+\]\([^)\s]+\))/g;
  function inline(parent, text, sources) {
    let last = 0, m;
    INLINE.lastIndex = 0;
    while ((m = INLINE.exec(text)) !== null) {
      if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      const tok = m[0];
      if (tok.startsWith("**")) parent.appendChild(el("strong", "", tok.slice(2, -2)));
      else if (tok.startsWith("`")) { const c = el("code", "", tok.slice(1, -1)); c.dir = "ltr"; parent.appendChild(c); }
      else if (m[2]) {
        const s = (sources || []).find((x) => x.n === Number(m[2]));
        if (s && safeHref(s.url)) {
          const a = el("a", "gpa-cite", m[2]); a.href = s.url; a.title = s.title;
          const sup = el("sup"); sup.appendChild(a); parent.appendChild(sup);
        } else parent.appendChild(el("sup", "gpa-cite", m[2]));
      } else {
        const mm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok);
        if (mm && safeHref(mm[2])) { const a = el("a", "", mm[1]); a.href = mm[2]; if (mm[2][0] !== "/") { a.target = "_blank"; a.rel = "noopener"; } parent.appendChild(a); }
        else parent.appendChild(document.createTextNode(tok));
      }
      last = m.index + tok.length;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }
  function render(target, text, sources) {
    target.textContent = "";
    const lines = text.replace(/\r/g, "").split("\n");
    let list = null, para = null, code = null;
    const flush = () => { para = null; list = null; };
    for (const raw of lines) {
      if (raw.trim().startsWith("```")) {
        if (code) { code = null; } else { flush(); const pre = el("pre"); const c = el("code"); c.dir = "ltr"; pre.appendChild(c); target.appendChild(pre); code = c; }
        continue;
      }
      if (code) { code.textContent += (code.textContent ? "\n" : "") + raw; continue; }
      const line = raw.trim();
      if (!line) { flush(); continue; }
      const ul = /^[-*•]\s+(.*)$/.exec(line), ol = /^(\d+|[۰-۹]+)[.)]\s+(.*)$/.exec(line);
      if (ul || ol) {
        const tag = ol ? "ol" : "ul";
        if (!list || list.tagName.toLowerCase() !== tag) { list = el(tag); target.appendChild(list); }
        para = null;
        const li = el("li"); inline(li, (ul || ol)[ul ? 1 : 2], sources); list.appendChild(li);
      } else {
        list = null;
        if (!para) { para = el("p"); target.appendChild(para); } else para.appendChild(el("br"));
        inline(para, line, sources);
      }
    }
  }

  // ---- ذخیره گفتگو فقط در همین تب مرورگر
  function save() { try { sessionStorage.setItem(STORE, JSON.stringify(history.slice(-MAX_KEEP))); } catch (e) { /* ignore */ } }
  function load() { try { const v = JSON.parse(sessionStorage.getItem(STORE) || "[]"); if (Array.isArray(v)) history = v; } catch (e) { history = []; } }

  function scroll() { log.scrollTop = log.scrollHeight; }
  function addMsg(role, text, sources) {
    const box = el("div", "gpa-msg gpa-" + role);
    const body = el("div", "gpa-body");
    if (role === "user") body.textContent = text; else render(body, text, sources);
    box.appendChild(body); log.appendChild(box); scroll();
    return { box, body };
  }
  function suggestions(items) {
    const wrap = el("div", "gpa-sugg");
    items.forEach((q) => { const b = el("button", "gpa-chip", q); b.type = "button"; b.addEventListener("click", () => ask(q)); wrap.appendChild(b); });
    return wrap;
  }
  function note(text) { const n = el("div", "gpa-note", text); log.appendChild(n); scroll(); return n; }

  function addLinks(box, items, label) {
    if (!items || !items.length) return;
    const w = el("div", "gpa-links");
    w.appendChild(el("span", "gpa-links-t", label || "منبع:"));
    items.forEach((s) => { if (!safeHref(s.url)) return; const a = el("a", "", s.n ? s.n + ". " + s.title : s.title); a.href = s.url; w.appendChild(a); });
    box.appendChild(w);
  }
  function addFeedback(box, id, token) {
    const w = el("div", "gpa-fb");
    w.appendChild(el("span", "", "مفید بود؟"));
    [["👍", true], ["👎", false]].forEach(([label, val]) => {
      const b = el("button", "gpa-fbbtn", label); b.type = "button"; b.setAttribute("aria-label", val ? "مفید بود" : "مفید نبود");
      b.addEventListener("click", () => {
        w.textContent = "ممنون از بازخوردتان.";
        fetch(URLS.feedback, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: JSON.stringify({ id, token, helpful: val }) }).catch(() => {});
      });
      w.appendChild(b);
    });
    box.appendChild(w);
  }

  function setBusy(v) { busy = v; sendBtn.disabled = v; input.disabled = v; panel.classList.toggle("gpa-busy", v); }

  async function ask(text) {
    text = (text || "").trim();
    if (!text || busy || !cfg) return;
    const intro = log.querySelector(".gpa-sugg"); if (intro) intro.remove();
    addMsg("user", text);
    input.value = ""; autosize();
    const bot = addMsg("bot", ""); bot.box.classList.add("gpa-typing");
    setBusy(true);
    let acc = "", sources = [], answered = false, noans = null, doneEv = null;
    try {
      const resp = await fetch(URLS.ask, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ message: text, history: history.slice(-8), path: location.pathname, title: document.title.slice(0, 120) }),
      });
      if (!resp.ok || !resp.body) {
        let msg = "ارسال سؤال ممکن نشد؛ دوباره امتحان کنید.";
        try { const j = await resp.json(); if (j.error) msg = j.error; } catch (e) { /* ignore */ }
        bot.box.classList.remove("gpa-typing"); bot.box.classList.add("gpa-err"); bot.body.textContent = msg;
        return;
      }
      const reader = resp.body.getReader(), dec = new TextDecoder("utf-8");
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
          if (!chunk.startsWith("data:")) continue;
          let ev; try { ev = JSON.parse(chunk.slice(5)); } catch (e) { continue; }
          if (ev.type === "delta") { acc += ev.t; render(bot.body, acc, sources); scroll(); }
          else if (ev.type === "sources") { sources = ev.items || []; answered = true; render(bot.body, acc, sources); }
          else if (ev.type === "noanswer") { bot.body.textContent = ev.text; noans = ev; }
          else if (ev.type === "error") { bot.box.classList.add("gpa-err"); bot.body.textContent = ev.text; }
          else if (ev.type === "done") { doneEv = ev; }
        }
      }
      bot.box.classList.remove("gpa-typing");
      if (noans) {
        const links = (noans.suggest || []).map((s) => ({ title: s.title, url: s.url }));
        if (links.length) addLinks(bot.box, links, "شاید کمک کند:");
        if (safeHref(noans.support_url)) { const sup = el("a", "gpa-support", "ثبت تیکت پشتیبانی"); sup.href = noans.support_url; bot.box.appendChild(sup); }
      }
      if (answered) {
        addLinks(bot.box, sources);
        history.push({ role: "user", content: text }, { role: "assistant", content: acc });
        save();
      }
      if (doneEv && doneEv.id && doneEv.token) addFeedback(bot.box, doneEv.id, doneEv.token);
    } catch (e) {
      bot.box.classList.remove("gpa-typing"); bot.box.classList.add("gpa-err");
      if (!acc) bot.body.textContent = "ارتباط با سرور برقرار نشد؛ اینترنت را بررسی و دوباره امتحان کنید.";
    } finally { setBusy(false); input.focus(); scroll(); }
  }

  function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 110) + "px"; }

  function build() {
    panel = el("section", "gpa-panel"); panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "دستیار هوشمند"); panel.hidden = true;
    const head = el("header", "gpa-head");
    head.appendChild(el("strong", "", "دستیار هوشمند"));
    const tools = el("div", "gpa-tools");
    const reset = el("button", "gpa-ico", "↺"); reset.type = "button"; reset.title = "گفتگوی جدید"; reset.setAttribute("aria-label", "گفتگوی جدید");
    const close = el("button", "gpa-ico", "✕"); close.type = "button"; close.title = "بستن"; close.setAttribute("aria-label", "بستن");
    tools.append(reset, close); head.appendChild(tools);
    log = el("div", "gpa-log"); log.setAttribute("aria-live", "polite");
    const form = el("form", "gpa-form");
    input = el("textarea"); input.rows = 1; input.maxLength = cfg.max_message; input.placeholder = "سؤالتان را بنویسید…"; input.setAttribute("aria-label", "سؤال");
    sendBtn = el("button", "gpa-send", "ارسال"); sendBtn.type = "submit";
    form.append(input, sendBtn);
    const foot = el("div", "gpa-foot");
    foot.appendChild(document.createTextNode("پاسخ‌ها از «پایگاه دانش» گرفته می‌شود و ممکن است خطا داشته باشد. "));
    const kb = el("a", "", "پایگاه دانش"); kb.href = URLS.kb; foot.appendChild(kb);
    panel.append(head, log, form, foot);
    document.body.appendChild(panel);
    close.addEventListener("click", toggle);
    reset.addEventListener("click", () => { history = []; save(); log.textContent = ""; intro(); });
    form.addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });
    input.addEventListener("input", autosize);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input.value); } });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) toggle(); });
  }
  function intro() {
    addMsg("bot", cfg.welcome || "سلام! چطور می‌توانم کمک کنم؟");
    history.forEach((m) => addMsg(m.role === "user" ? "user" : "bot", m.content, []));
    if (!history.length) log.appendChild(suggestions(cfg.suggestions || []));
  }

  async function toggle() {
    if (!cfg) {
      fab.disabled = true;
      try {
        const r = await fetch(URLS.config + "?path=" + encodeURIComponent(location.pathname), { credentials: "same-origin" });
        cfg = await r.json();
      } catch (e) { cfg = null; }
      fab.disabled = false;
      if (!cfg || !cfg.enabled) { fab.remove(); return; }
      csrf = cfg.csrf; load(); build(); intro();
    }
    panel.hidden = !panel.hidden;
    fab.setAttribute("aria-expanded", String(!panel.hidden));
    fab.classList.toggle("gpa-open", !panel.hidden);
    dock();
    if (!panel.hidden) { input.focus(); scroll(); }
  }

  // ── جای دکمه: داخل منوی کنار صفحه یا نوار بالای صفحه‌های تمام‌صفحه، وگرنه شناور ──
  // جای شناور گوشه‌ی نقشه‌ها (راهنما و مقیاس) را می‌پوشاند؛ پس هر جا که جای ثابتی هست، آنجا می‌نشیند.
  const slot = (name) => document.querySelector('[data-gpa-slot="' + name + '"]');
  const narrow = matchMedia("(max-width:900px)");
  function place() {
    let target = null, mode = "";
    if (slot("studio")) { target = slot("studio"); mode = "compact"; }
    else if (!narrow.matches && slot("menu")) { target = slot("menu"); mode = "inline"; }
    else if (narrow.matches && slot("bar")) { target = slot("bar"); mode = "compact"; }
    fab.classList.toggle("gpa-inline", mode === "inline");
    fab.classList.toggle("gpa-compact", mode === "compact");
    if (target) { if (fab.parentNode !== target) target.appendChild(fab); }
    else if (fab.parentNode !== document.body) document.body.appendChild(fab);
  }

  // ── پنل کنار صفحه: روی صفحه‌ی عریض نقشه و منوها را نمی‌پوشاند، فقط کوچک‌ترشان می‌کند ──
  const wideScreen = matchMedia("(min-width:1100px)");
  const canDock = () => wideScreen.matches && !!document.querySelector(".ws, .studio");
  function dock() {
    if (!panel) return;
    const on = !panel.hidden && canDock();
    panel.classList.toggle("gpa-dock", on);
    document.body.classList.toggle("gpa-docked", on);
    window.dispatchEvent(new Event("resize")); // نقشه‌ها اندازه‌شان را دوباره بگیرند
  }
  wideScreen.addEventListener("change", dock);
  narrow.addEventListener("change", place);

  fab = el("button", "gpa-fab"); fab.type = "button"; fab.setAttribute("aria-label", "دستیار هوشمند"); fab.setAttribute("aria-expanded", "false");
  fab.appendChild(el("span", "gpa-fab-ico", "💬")); fab.appendChild(el("span", "gpa-fab-txt", "دستیار"));
  fab.addEventListener("click", toggle);
  place();
})();
