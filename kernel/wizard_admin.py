"""صفحه‌های ویزارد ساخت پلاگین در پنل مدیریت (docs/adr/0008، مرحله‌ی ۳): معرفی ← داده ← صفحه‌ها (+ پیش‌نمایش).

مشخصات در `PluginDraft.wizard` می‌ماند و با هر ذخیره، صفحه‌های TOML (`PluginDraft.pages`) از روی آن دوباره ساخته می‌شود
(kernel.wizard)؛ پس بررسی، پیش‌نمایش و خروجی استودیوی قبلی روی خروجی ویزارد هم کار می‌کند. خطای ساخت صفحه ذخیره‌ی مشخصات را نمی‌بندد.
"""
from __future__ import annotations

import copy
import re

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import reverse

from . import pagekit, pkg, pkgtest, publish, stepup, studio, tables, wizard, wizard_code
from . import workspace as ws_mod
from .models import PluginDraft
from .plugins import registry

STEPS = ((1, "معرفی"), (2, "داده"), (3, "کد (اختیاری)"), (4, "صفحه‌ها"), (5, "دسترسی و قیمت"), (6, "بازبینی و انتشار"))
ICON_CHOICES = ("chart", "pulse", "gauge", "table", "pin", "layers", "satellite", "bell", "globe", "db", "clock", "bolt")
KIND_TILES = (("kpi", "شمارنده", "یک عدد درشت (تعداد، میانگین، بیشینه…)"), ("table", "جدول", "آخرین ردیف‌ها"),
              ("handler", "خروجی کد", "نمایش نتیجه‌ی یکی از کدهای مرحله‌ی «کد»"), ("import", "ورود فایل (کد)", "کاربر فایل می‌دهد، جدول تازه ساخته می‌شود"),
              ("export", "خروجی فایل (کد)", "دکمه‌ی دانلود با کد شما"),
              ("bars", "نمودار میله‌ای", "مقایسه‌ی گروه‌ها"), ("map", "نقشه", "نقطه‌ها روی نقشه"), ("text", "متن", "راهنما یا توضیح"),
              ("form", "فرم ثبت", "کاربر ردیف تازه ثبت می‌کند"), ("ingest", "دریافت از دستگاه", "دستگاه با توکن داده می‌فرستد"),
              ("sql", "SQL پیشرفته", "پرس‌وجوی فقط‌خواندنی دلخواه"))
COL_TYPES = (("text", "متن"), ("integer", "عدد صحیح"), ("bigint", "عدد صحیح بزرگ"), ("double", "عدد اعشاری"), ("boolean", "بله/خیر"),
             ("date", "تاریخ"), ("timestamptz", "زمان"), ("jsonb", "JSON"), ("point", "نقطه‌ی مکانی"))
AGG_CHOICES = (("count", "تعداد"), ("sum", "جمع"), ("avg", "میانگین"), ("min", "کمینه"), ("max", "بیشینه"))


def _allowed(request) -> bool:
    return request.user.has_perm("kernel.upload_pluginrelease")


def _url(draft, step: int) -> str:
    return reverse("admin:kernel_plugindraft_wizard", args=[draft.pk, step])


def _save(draft: PluginDraft, spec: dict, user) -> str:
    """مشخصات را ذخیره و صفحه‌ها را از رویش می‌سازد؛ متن خطای ساخت یا ''."""
    draft.wizard = spec
    draft.updated_by = user
    err = ""
    code = spec.get("code") or {}
    draft.code = {n: h.get("source", "") for n, h in code.items()}
    draft.tests = {n: h.get("test", "") for n, h in code.items()}
    draft.alerts = {n: h["every"] for n, h in code.items() if h.get("role") == "alert" and isinstance(h.get("every"), int)}
    try:
        wizard_code.validate_code(spec)
        draft.pages = wizard.compile_pages(draft.plugin_id, spec)
    except wizard.WizardError as exc:
        err = str(exc)
    draft.save()
    return err


def _int(v, default=0):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _columns_from_post(post) -> list[dict]:
    names, types = post.getlist("c_name"), post.getlist("c_type")
    cols = []
    for i, n in enumerate(names):
        n = n.strip()
        if not n:
            continue
        cols.append({"name": n, "type": types[i] if i < len(types) else "text", "required": post.get(f"c_req_{i}") == "1",
                     "auto_now": post.get(f"c_auto_{i}") == "1"})
    return cols


def _indexes_from_post(post) -> list[list[str]]:
    out = []
    for part in (post.get("indexes") or "").split(";"):
        cols = [c.strip() for c in part.split(",") if c.strip()]
        if cols:
            out.append(cols)
    return out


def _block_from_post(post) -> dict:
    kind = post.get("kind", "")
    if kind not in wizard.KINDS:
        raise wizard.WizardError("نوع بلوک را انتخاب کنید.")
    b: dict = {"kind": kind, "title": post.get("title", "").strip()[:80], "table": post.get("table", "")}
    if post.get("width") in ("full", "half", "third"):
        b["width"] = post["width"]
    if kind == "kpi":
        b.update(agg=post.get("agg", "count"), column=post.get("column", ""), distinct=post.get("distinct", ""), unit=post.get("unit", "").strip()[:30])
    elif kind == "table":
        b.update(columns=post.getlist("columns"), order_by=post.get("order_by", ""), limit=_int(post.get("limit"), 20), desc=post.get("asc") != "1")
    elif kind == "bars":
        b.update(label=post.get("label", ""), agg=post.get("agg", "count"), column=post.get("column", ""))
    elif kind == "map":
        b.update(point=post.get("point", ""), lat=post.get("lat", ""), lon=post.get("lon", ""), props=post.getlist("props"),
                 latest_by=post.get("latest_by", ""), time_col=post.get("time_col", ""))
    elif kind == "text":
        b["text"] = post.get("text", "").strip()[:2000]
    elif kind in wizard.ACTIONS:
        b.update(fields=post.getlist("fields"), max_rows=_int(post.get("max_rows"), 100), rate=_int(post.get("rate"), 60))
        if kind == "ingest" and post.get("ingest_handler"):
            b["handler"] = post["ingest_handler"]
    elif kind == "handler":
        b.update(handler=post.get("handler", ""), display=post.get("display", "table"), unit=post.get("unit", "").strip()[:30])
    elif kind == "import":
        b.update(handler=post.get("import_handler", ""), extensions=post.get("extensions", ""))
    elif kind == "export":
        b.update(handler=post.get("export_handler", ""), format=post.get("format", "csv"))
    elif kind == "sql":
        b.update(display=post.get("display", "table"), sql=post.get("sql", ""))
    if kind in ("kpi", "table", "bars", "map") and post.get("since_col"):
        b.update(since_col=post["since_col"], since_minutes=post.get("since_minutes", ""))
    return b


def view(request, pk=None, step=1):
    if not _allowed(request):
        raise PermissionDenied
    draft = get_object_or_404(PluginDraft, pk=pk) if pk else None
    step = step if step in (1, 2, 3, 4, 5, 6) else 1
    if draft is None:
        step = 1
    spec = copy.deepcopy(draft.wizard) if draft and draft.wizard else {"intro": {}, "tables": [], "pages": []}
    preview_html = ""
    if request.method == "POST":
        resp, preview_html = _post(request, draft, spec, step)
        if resp is not None:
            return resp
        draft = PluginDraft.objects.filter(pk=draft.pk).first() if draft else None
    tmap = wizard.table_map(spec)
    errors = []
    if draft:
        try:
            wizard.compile_pages(draft.plugin_id, spec)
        except wizard.WizardError as exc:
            errors.append(str(exc))
    pages = []
    for p in spec.get("pages") or []:
        pages.append({**p, "blocks": [{**b, "i": i, "kind_label": next((k[1] for k in KIND_TILES if k[0] == b["kind"]), b["kind"])}
                                       for i, b in enumerate(p.get("blocks") or [])]})
    ctx = {
        **_site(request), "title": "ساخت پلاگین", "draft": draft, "spec": spec, "step": step, "steps": STEPS, "errors": errors,
        "pages": pages, "tables_": [{**t, "cols": t["columns"]} for t in spec.get("tables") or []], "tmap": tmap,
        "icons": ICON_CHOICES, "kind_tiles": KIND_TILES, "col_types": COL_TYPES, "aggs": AGG_CHOICES, "preview_html": preview_html,
        "prefix": f"{draft.plugin_id}_" if draft else "", "studio_url": reverse("admin:kernel_plugindraft_studio", args=[draft.pk]) if draft else "",
        "col_json": {n: [{"name": c["name"], "type": c["type"]} for c in t["columns"]] for n, t in tmap.items()},
        "has_map": "map" in preview_html or 'data-pk-map' in preview_html,
        "access": spec.get("access") or {}, "limit_keys": publish.LIMIT_KEYS, "access_targets": (spec.get("access") or {}).get("targets", []),
        "durations": ((30, "۳۰ روز"), (90, "۹۰ روز"), (180, "۱۸۰ روز"), (365, "۳۶۵ روز")),
    }
    if step == 3 and draft:
        ctx.update(_code_ctx(spec))
    if step == 4:
        ctx["handlers"] = {r: [n for n, h in (spec.get("code") or {}).items() if h.get("role") == r] for r in wizard_code.ROLES}
        ctx["export_formats"] = wizard.EXPORT_FORMATS
    if step == 6 and draft:
        ctx.update(_review(draft, spec))
    return TemplateResponse(request, "admin/kernel/wizard.html", ctx)


def _code_ctx(spec) -> dict:
    code = spec.get("code") or {}
    items = []
    for n, h in code.items():
        err = ""
        try:
            wizard_code.check_source(h.get("source", ""), n)
        except wizard.WizardError as exc:
            err = str(exc)
        items.append({"name": n, "role": h["role"], "role_label": wizard_code.ROLE_LABEL[h["role"]], "source": h.get("source", ""),
                      "test": h.get("test", ""), "every": h.get("every"), "tables": h.get("tables") or [], "error": err})
    tpl = [{"key": k, "role": t["role"], "role_label": wizard_code.ROLE_LABEL[t["role"]], "title": t["title"], "hint": t["hint"], "needs": t["needs"], "nums": t.get("nums", [])}
           for k, t in wizard_code.TEMPLATES.items()]
    return {"handlers_list": items, "templates": tpl, "runner_ready": _runner_ready(), "col_labels": {k: v[0] for k, v in wizard_code.COLS.items()},
            "num_labels": {k: v[0] for k, v in wizard_code.NUMS.items()}, "role_labels": wizard_code.ROLE_LABEL}


def _review(draft, spec) -> dict:
    """داده‌ی مرحله‌ی بازبینی: بررسی کامل بسته، دسترسی، نسخه‌ی بعدی و وضعیت پلاگین فعلی."""
    steps = studio.check(draft) if draft.pages else [{"stage": "صفحه‌ها", "ok": False, "detail": "هنوز صفحه‌ی کاملی نیست."}]
    access_err = ""
    try:
        publish.normalize_access(spec.get("access") or {})
    except publish.PublishError as exc:
        access_err = str(exc)
    return {"check_steps": steps, "check_ok": studio.ok(steps), "access_err": access_err,
            "next_version": publish.next_version(draft.plugin_id, draft.version), "second_approval": pkg.second_approval_required(),
            "installed": draft.plugin_id in registry.plugins, "has_code": bool(draft.code), "runner_ok": _runner_ready(),
            "can_publish": studio.ok(steps) and not access_err and (not draft.code or _runner_ready())}


def _site(request):
    from django.contrib import admin

    return admin.site.each_context(request)


def _post(request, draft, spec, step):
    """(پاسخ ریدایرکت یا None، html پیش‌نمایش). خطا = پیام و بازگشت به همان مرحله."""
    op = request.POST.get("op", "")
    try:
        if step == 1:
            return _step1(request, draft, spec), ""
        if draft is None:
            raise PermissionDenied
        if step == 2:
            return _step2(request, draft, spec, op), ""
        if step == 3:
            return _step_code(request, draft, spec, op)
        if step == 4:
            return _step3(request, draft, spec, op)
        if step == 5:
            return _step4(request, draft, spec), ""
        return _step5(request, draft, spec), ""
    except (wizard.WizardError, publish.PublishError) as exc:
        messages.error(request, str(exc))
        return (redirect(_url(draft, step)) if draft else redirect(reverse("admin:kernel_plugindraft_wizard_new"))), ""


def _step1(request, draft, spec):
    post = request.POST
    name = post.get("name", "").strip()
    if not name or len(name) > 120:
        raise wizard.WizardError("نام پلاگین را بنویسید (حداکثر ۱۲۰ نویسه).")
    icon = post.get("icon", "chart")
    intro = {"summary": post.get("summary", "").strip()[:240], "icon": icon if icon in ICON_CHOICES else "chart"}
    if draft is None:
        pid = post.get("plugin_id", "").strip()
        if not wizard.ID_RE.fullmatch(pid):
            raise wizard.WizardError("شناسه‌ی پلاگین: حروف کوچک لاتین، رقم و _ (۲ تا ۴۱ نویسه، با حرف شروع شود).")
        if PluginDraft.objects.filter(plugin_id=pid).exists() or pid in registry.plugins:
            raise wizard.WizardError("این شناسه از قبل پیش‌نویس یا پلاگین است؛ شناسه‌ی دیگری بدهید.")
        draft = PluginDraft(plugin_id=pid, name=name, version="1.0.0", kind="custom", requires="databases", readme=post.get("description", "").strip())
        spec = {"intro": intro, "tables": [], "pages": []}
    else:
        draft.name, draft.readme = name, post.get("description", "").strip()
        spec["intro"] = intro
    _save(draft, spec, request.user)
    messages.success(request, "معرفی ذخیره شد.")
    return redirect(_url(draft, 2))


def _step2(request, draft, spec, op):
    post = request.POST
    if op == "addtable":
        suffix = post.get("suffix", "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", suffix):
            raise wizard.WizardError("نام جدول: حروف کوچک لاتین، رقم و _ (با حرف شروع شود).")
        t = {"name": f"{draft.plugin_id}_{suffix}", "columns": _columns_from_post(post)}
        idx = _indexes_from_post(post)
        if idx:
            t["indexes"] = idx
        new = {**spec, "tables": [*spec.get("tables", []), t]}
        wizard.validate_tables(draft.plugin_id, new["tables"])
        err = _save(draft, new, request.user)
        messages.success(request, f"جدول «{t['name']}» افزوده شد." + (f" ({err})" if err else ""))
    elif op.startswith("deltable:"):
        name = op.split(":", 1)[1]
        spec["tables"] = [t for t in spec.get("tables", []) if t["name"] != name]
        removed = 0
        for p in spec.get("pages", []):
            keep = [b for b in p.get("blocks", []) if b.get("table") != name]
            removed += len(p.get("blocks", [])) - len(keep)
            p["blocks"] = keep
        _save(draft, spec, request.user)
        messages.warning(request, f"جدول «{name}» برداشته شد" + (f" و {removed} بلوک وابسته‌اش پاک شد." if removed else "."))
    elif op == "next":
        if not spec.get("tables"):
            raise wizard.WizardError("دست‌کم یک جدول بسازید (یا بدون داده فقط بلوک متن/SQL پیشرفته را در مرحله‌ی بعد بیفزایید).")
        return redirect(_url(draft, 3))
    return redirect(_url(draft, 2))


ROLE_RUN = {"block": "block", "alert": "block", "importer": "import", "exporter": "export", "ingest": "ingest"}


def _runner_ready() -> bool:
    from .runner import client

    return client.mode() in ("local", "remote")


def _test_results(name: str, h: dict) -> list[dict]:
    """آزمون‌های یک handler در runner (همان آزمون بسته)؛ [{case, ok, message}]. TestSpecError اگر ساختار آزمون نامعتبر یا runner خاموش است."""
    from types import SimpleNamespace

    cases = pkgtest.parse(h.get("test", ""), name)
    role = ROLE_RUN.get(h.get("role", "block"), "block")
    spec = SimpleNamespace(format="txt", max_rows=1000, table="", fields=()) if role == "export" else None
    if role == "ingest":
        role = "block"  # ساختار ردیف‌ها را بلوک نمی‌داند؛ شمار ردیف‌ها سنجیده می‌شود
    out = []
    for c in cases:
        msg = pkgtest.run_case(name, h.get("source", ""), role, spec, c)
        out.append({"case": c.name, "ok": not msg, "message": msg})
    return out


def _results_html(title: str, rows: list[dict]) -> str:
    from django.utils.html import format_html, format_html_join

    items = format_html_join("", "<li><b style=\"color:{}\">{}</b> {} <span class=\"wz-muted\">{}</span></li>",
                             (("var(--teal)" if r["ok"] else "#b42318", "✓" if r["ok"] else "✗", r["case"], r["message"]) for r in rows))
    return str(format_html("<h3>{}</h3><ul class=\"wz-list\">{}</ul>", title, items))


def _trial(request, draft, name: str, h: dict) -> str:
    """اجرای آزمایشی یک handler با ورودی و فایل نمونه (اختیاری روی یک پایگاه داده‌ی نمونه)؛ چیزی نوشته نمی‌شود."""
    import json

    from django.utils.html import format_html

    from . import pluginio
    from .runner import client

    post = request.POST
    try:
        params = json.loads(post.get("params") or "{}")
        if not isinstance(params, dict):
            raise ValueError
    except ValueError:
        raise wizard.WizardError("ورودی باید یک شیء JSON باشد، مثل {\"n\": 3}.") from None
    data = None
    up = request.FILES.get("file")
    if up is not None:
        if up.size > client.sandbox.MAX_FILE:
            raise wizard.WizardError("حجم فایل نمونه بیش از ۳ مگابایت است.")
        data = up.read()
    pk = post.get("preview_db", "").strip()
    ws = ws_mod.peek(int(pk)) if pk.isdigit() else None
    if pk and (ws is None or not getattr(ws, "is_live", False)):
        raise wizard.WizardError("پایگاه داده‌ی فعال با این شناسه نیست.")
    role = ROLE_RUN.get(h.get("role", "block"), "block")
    logs: list[str] = []
    sql_fn = (lambda q, a: pagekit.read_select(ws, q, a)) if ws is not None else None  # noqa: E731
    try:
        out = client.run_files({f"code/{name}.py": h["source"]}, name, params, sql_fn, getattr(ws, "pk", 0) or 0, file=data,
                               io=role != "block", on_log=logs.append, allow_no_ws=True, plugin="studio")
        if role == "import":
            t = pluginio.normalize_import("trial_table", out)
            verdict = f"ورود معتبر است: {len(t.rows):,} ردیف، {len(t.columns)} ستون" + ("، با ستون مکانی" if t.geometry else "")
        elif role == "export":
            fname, body, ctype = pluginio.normalize_export(out, "txt")
            verdict = f"خروجی معتبر است: {fname} ({len(body):,} بایت)"
        elif role == "ingest":
            verdict = f"{len(out.get('rows', [])):,} ردیف تبدیل شد." if isinstance(out, dict) and isinstance(out.get("rows"), list) else "خروجی باید {rows: [...]} باشد."
        else:
            verdict = "اجرا موفق بود."
    except client.RunnerError as exc:
        return str(format_html("<h3>اجرای آزمایشی «{}» ناموفق بود</h3><p class=\"wz-err\">{}</p>", name, str(exc)))
    except pluginio.PluginIOError as exc:
        return str(format_html("<h3>خروجی «{}» معتبر نیست</h3><p class=\"wz-err\">{}</p>", name, str(exc)))
    shown = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    shown = shown if len(shown) <= 6000 else shown[:6000] + "\n… (کوتاه‌شده)"
    ws_mod.log_event("plugin_studio", f"اجرای آزمایشی ویزارد {draft.plugin_id}/{name}", user=request.user, database=ws)
    return str(format_html("<h3>اجرای آزمایشی «{}»</h3><p>{}</p><pre dir=\"ltr\" style=\"max-height:320px;overflow:auto\">{}</pre><p class=\"wz-muted\">{}</p>",
                           name, verdict, shown, "\n".join(logs)))


def _step_code(request, draft, spec, op):
    post = request.POST
    code = spec.setdefault("code", {})
    html = ""
    if op == "addhandler":
        name = post.get("name", "").strip()
        if not wizard_code.NAME_RE.fullmatch(name) or name in code:
            raise wizard.WizardError("نام handler نامعتبر یا تکراری است (حروف کوچک لاتین، رقم و _؛ ۲ تا ۳۱ نویسه).")
        if len(code) >= wizard_code.MAX_HANDLERS:
            raise wizard.WizardError(f"حداکثر {wizard_code.MAX_HANDLERS} handler.")
        params = {k: post.get(k, "") for k in (*wizard_code.COLS, *wizard_code.NUMS, "table")}
        code[name] = wizard_code.build(spec, post.get("template", ""), params)
        _save(draft, spec, request.user)
        messages.success(request, f"handler «{name}» ساخته شد؛ کد را بخوانید، آزمون و اجرای آزمایشی بزنید.")
    elif op.startswith("savehandler:"):
        name = op.split(":", 1)[1]
        h = code.get(name)
        if h is None:
            raise wizard.WizardError("handler پیدا نشد.")
        src, test = post.get("source", ""), post.get("test", "")
        wizard_code.check_source(src, name)
        try:
            pkgtest.parse(test, name)
        except pkgtest.TestSpecError as exc:
            raise wizard.WizardError(f"آزمون: {exc}") from exc
        h.update(source=src, test=test)
        if h["role"] == "alert":
            every = _int(post.get("every"), h.get("every") or 60)
            if not 5 <= every <= 1440:
                raise wizard.WizardError("فاصله‌ی هشدار بین ۵ و ۱۴۴۰ دقیقه باشد.")
            h["every"] = every
        err = _save(draft, spec, request.user)
        messages.success(request, "ذخیره شد." + (f" توجه: {err}" if err else ""))
    elif op.startswith("delhandler:"):
        name = op.split(":", 1)[1]
        code.pop(name, None)
        for p in spec.get("pages", []):
            p["blocks"] = [b for b in p.get("blocks", []) if b.get("handler") != name or b["kind"] == "ingest"]
            for b in p["blocks"]:
                if b["kind"] == "ingest" and b.get("handler") == name:
                    b.pop("handler")
        _save(draft, spec, request.user)
        messages.warning(request, f"handler «{name}» و بلوک‌های وابسته‌اش برداشته شد.")
    elif op.startswith(("trial:", "tests:")):
        if not stepup.ok(request):
            messages.warning(request, "برای اجرا تأیید تازه‌ی ورود دومرحله لازم است.")
            return redirect(stepup.url(request)), ""
        if not _runner_ready():
            raise wizard.WizardError("اجرای کد در این استقرار خاموش است. از «پلاگین‌ها ← پیشرفته ← کلیدهای ناشر و اجرای کد» حالت «راه‌دور» را روشن کنید.")
        name = op.split(":", 1)[1]
        h = code.get(name)
        if h is None:
            raise wizard.WizardError("handler پیدا نشد.")
        if op.startswith("trial:"):
            html = _trial(request, draft, name, h)
        else:
            try:
                html = _results_html(f"آزمون‌های «{name}»", _test_results(name, h))
            except (pkgtest.TestSpecError, wizard.WizardError) as exc:
                raise wizard.WizardError(f"آزمون: {exc}") from exc
            except Exception as exc:  # noqa: BLE001 - خطای runner
                raise wizard.WizardError(f"آزمون اجرا نشد: {str(exc)[:200]}") from exc
        return None, html
    return redirect(_url(draft, 3)), html


def _step3(request, draft, spec, op):
    post = request.POST
    preview = ""
    if op == "addpage":
        title = post.get("title", "").strip()
        if not title or len(title) > 80:
            raise wizard.WizardError("عنوان صفحه را بنویسید (حداکثر ۸۰ نویسه).")
        if len(spec.get("pages", [])) >= wizard.MAX_PAGES:
            raise wizard.WizardError(f"حداکثر {wizard.MAX_PAGES} صفحه.")
        icon = post.get("icon", "chart")
        spec.setdefault("pages", []).append({
            "key": wizard.next_page_key(spec), "title": title, "subtitle": post.get("subtitle", "").strip()[:240],
            "icon": icon if icon in ICON_CHOICES else "chart", "group": post.get("group", "data") if post.get("group") in pagekit.GROUPS else "data",
            "need": post.get("need", "viewer") if post.get("need") in pagekit.NEEDS else "viewer",
            "refresh": _int(post.get("refresh"), 0), "blocks": []})
        _save(draft, spec, request.user)
        messages.success(request, "صفحه افزوده شد؛ حالا بلوک بیفزایید.")
    elif op.startswith("delpage:"):
        key = op.split(":", 1)[1]
        spec["pages"] = [p for p in spec.get("pages", []) if p["key"] != key]
        _save(draft, spec, request.user)
    elif op.startswith("addblock:"):
        key = op.split(":", 1)[1]
        page = next((p for p in spec.get("pages", []) if p["key"] == key), None)
        if page is None:
            raise wizard.WizardError("صفحه پیدا نشد.")
        if len(page.get("blocks", [])) >= wizard.MAX_BLOCKS:
            raise wizard.WizardError(f"حداکثر {wizard.MAX_BLOCKS} بلوک در هر صفحه.")
        b = _block_from_post(post)
        wizard.check_block(spec, b)
        page.setdefault("blocks", []).append(b)
        err = _save(draft, spec, request.user)
        messages.success(request, "بلوک افزوده شد." + (f" توجه: {err}" if err else ""))
    elif op.startswith("delblock:"):
        _op, key, idx = op.split(":", 2)
        page = next((p for p in spec.get("pages", []) if p["key"] == key), None)
        if page is not None and 0 <= _int(idx, -1) < len(page.get("blocks", [])):
            page["blocks"].pop(_int(idx))
            _save(draft, spec, request.user)
    elif op.startswith("preview:"):
        key = op.split(":", 1)[1]
        preview = _preview(request, draft, spec, key)
        return None, preview
    return redirect(_url(draft, 4)), preview


def _access_from_post(post) -> dict:
    mode = post.get("mode", "")
    a: dict = {"mode": mode}
    if mode == "public_paid":
        a.update(price_toman=post.get("price_toman", ""), duration_days=post.get("duration_days", "30"), scope=post.get("scope", "workspace"),
                 trial_days=post.get("trial_days", "0") or "0",
                 limits={k: _int(post.get(k)) for k in publish.LIMIT_KEYS if post.get(k, "").strip().isdigit()})
    elif mode == "private":
        kinds, subjects, days = post.getlist("t_kind"), post.getlist("t_subject"), post.getlist("t_days")
        a["targets"] = [{"kind": k, "subject": subjects[i] if i < len(subjects) else "", "days": days[i] if i < len(days) else ""}
                        for i, k in enumerate(kinds) if (subjects[i] if i < len(subjects) else "").strip()]
    return a


def _step4(request, draft, spec):
    access = publish.normalize_access(_access_from_post(request.POST))
    bad = publish.check_targets(access)
    if bad:
        raise publish.PublishError("هدف‌های پیدا‌نشده: " + "، ".join(bad))
    spec["access"] = {**access, **({"limits": access.get("limits", {})} if access["mode"] == "public_paid" else {})}
    _save(draft, spec, request.user)
    messages.success(request, "دسترسی و قیمت ذخیره شد.")
    return redirect(_url(draft, 6))


def _step5(request, draft, spec):
    if request.POST.get("op") != "publish":
        return redirect(_url(draft, 6))
    if not stepup.ok(request):
        return redirect(stepup.url(request))
    out = publish.publish(draft, request.user, spec.get("access") or {})
    (messages.success if out["active"] else messages.warning)(request, f"{out['message']} (نسخه‌ی {out['release'].version})")
    ws_mod.log_event("plugin_publish", f"{draft.plugin_id} {out['release'].version}: {out['message']}", user=request.user)
    return redirect(_url(draft, 6))


def _preview(request, draft, spec, key) -> str:
    """پیش‌نمایش یک صفحه روی پایگاه داده‌ی نمونه (فقط‌خواندنی). «ساخت جدول‌ها» فقط با تیک صریح و تأیید تازه."""
    if not stepup.ok(request):
        messages.warning(request, "برای پیش‌نمایش تأیید تازه‌ی ورود دومرحله لازم است.")
        return ""
    pk = request.POST.get("preview_db", "").strip()
    ws = ws_mod.peek(int(pk)) if pk.isdigit() else None
    if ws is None or not getattr(ws, "is_live", False):
        messages.error(request, "پایگاه داده‌ی فعال با این شناسه نیست.")
        return ""
    try:
        wizard.compile_pages(draft.plugin_id, spec)
        page = next(p for p in studio.parse_pages(draft) if p.key == key)
    except (wizard.WizardError, StopIteration, pagekit.SpecError) as exc:
        messages.error(request, f"پیش‌نمایش ممکن نشد: {exc}" if not isinstance(exc, StopIteration) else "صفحه پیدا نشد.")
        return ""
    if request.POST.get("create_tables") == "1" and page.tables:
        try:
            n = tables.ensure(ws, draft.plugin_id, page.tables)
        except tables.TableError as exc:
            messages.error(request, str(exc))
            return ""
        if n:
            messages.success(request, f"{n} جدول در پایگاه نمونه ساخته شد.")
    try:
        with studio.temp_handlers(draft):
            ctx = studio.preview_page(draft, key, ws, {})
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"پیش‌نمایش ممکن نشد: {str(exc)[:200]}")
        return ""
    ws_mod.log_event("plugin_studio", f"پیش‌نمایش ویزارد {draft.plugin_id}/{key} روی پایگاه داده {ws.pk}", user=request.user, database=ws)
    return render_to_string("kernel/_page_body.html", {**ctx, "SITE": {}}, request=request)
