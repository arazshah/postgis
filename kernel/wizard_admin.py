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

from . import pagekit, stepup, studio, tables, wizard
from . import workspace as ws_mod
from .models import PluginDraft
from .plugins import registry

STEPS = ((1, "معرفی"), (2, "داده"), (3, "صفحه‌ها"))
ICON_CHOICES = ("chart", "pulse", "gauge", "table", "pin", "layers", "satellite", "bell", "globe", "db", "clock", "bolt")
KIND_TILES = (("kpi", "شمارنده", "یک عدد درشت (تعداد، میانگین، بیشینه…)"), ("table", "جدول", "آخرین ردیف‌ها"),
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
    try:
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
    elif kind == "sql":
        b.update(display=post.get("display", "table"), sql=post.get("sql", ""))
    if kind in ("kpi", "table", "bars", "map") and post.get("since_col"):
        b.update(since_col=post["since_col"], since_minutes=post.get("since_minutes", ""))
    return b


def view(request, pk=None, step=1):
    if not _allowed(request):
        raise PermissionDenied
    draft = get_object_or_404(PluginDraft, pk=pk) if pk else None
    step = step if step in (1, 2, 3) else 1
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
    }
    return TemplateResponse(request, "admin/kernel/wizard.html", ctx)


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
        return _step3(request, draft, spec, op)
    except wizard.WizardError as exc:
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
    return redirect(_url(draft, 3)), preview


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
        ctx = studio.preview_page(draft, key, ws, {})
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"پیش‌نمایش ممکن نشد: {str(exc)[:200]}")
        return ""
    ws_mod.log_event("plugin_studio", f"پیش‌نمایش ویزارد {draft.plugin_id}/{key} روی پایگاه داده {ws.pk}", user=request.user, database=ws)
    return render_to_string("kernel/_page_body.html", {**ctx, "SITE": {}}, request=request)
