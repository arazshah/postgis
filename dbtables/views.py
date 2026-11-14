"""نماهای «جدول‌ها»: فهرست، نمای جدول، ساخت و ساختار جدول، ویرایش ردیف، خروجی."""
import csv
import json
import time

from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import site_user_required
from core.models import SiteSettings
from databases import services
from databases.explorer import EXPORT_LIMIT, MAP_LIMIT, Explorer, ExplorerError
from databases.models import EditBatch
from kernel import events, workspace
from kernel import tables as plugin_tables

from . import editor, tablealter, tablebuilder
from .editor import EDIT_TTL, EditError, Editor


@site_user_required
def explore(request, pk):
    db, ex = workspace.open_catalog(request, pk)
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    try:
        tables = ex.tables()
    except ExplorerError as exc:
        messages.error(request, str(exc))
        return redirect("databases:detail", pk=db.pk)
    biggest = max((t.size_bytes for t in tables), default=0) or 1
    for t in tables:
        t.mappable = any(not g["geography"] and g["srid"] for g in t.geometry)
        t.size_pct = round(t.size_bytes * 100 / biggest) if t.size_bytes else 0
    schemas = sorted({t.schema for t in tables})
    ctx = {"db": db, "tables": tables, "section": "tables", "spatial_count": sum(t.mappable for t in tables),
           "geo_count": sum(1 for t in tables if t.geometry), "view_count": sum(1 for t in tables if t.kind in "vmf"),
           "total_size": sum(t.size_bytes for t in tables), "schemas": schemas if len(schemas) > 1 else []}
    if db.can_edit and db.status == db.Status.ACTIVE:
        ctx["builder_cfg"] = _builder_config(request, db, ex)
    return render(request, "databases/explore.html", ctx)


@site_user_required
def tables_json(request, pk):
    """فهرست جدول‌ها برای جست‌وجوی سریع Ctrl+K (بارگذاری تنبل، فقط هنگام باز شدن پالت)."""
    db, ex = workspace.open_catalog(request, pk)
    if ex is None:
        return JsonResponse({"items": []})
    try:
        tables = ex.tables()
    except ExplorerError:
        return JsonResponse({"items": []})
    return JsonResponse({"items": [
        {"t": (f"{x.schema}." if x.schema != "public" else "") + x.name,
         "u": reverse("databases:explore_table", args=[db.pk, x.schema, x.name]),
         "g": "جدول" + (" مکانی" if x.geometry else ""), "k": "t"} for x in tables]})


def _builder_config(request, db, ex) -> dict:
    try:
        schemas = ex.writable_schemas() or ["public"]
    except ExplorerError:
        schemas = ["public"]
    return {**tablebuilder.client_config(), "schemas": schemas, "csrf": get_token(request),
            "urls": {"preview": reverse("databases:table_preview", args=[db.pk]),
                     "create": reverse("databases:table_new", args=[db.pk]),
                     "srid": reverse("databases:table_srid", args=[db.pk])}}


def _builder_json(view):
    def wrapper(request, pk):
        try:
            return view(request, pk)
        except (tablebuilder.BuildError, EditError, ExplorerError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    wrapper.__name__ = view.__name__
    return site_user_required(wrapper)


def _builder_guard(request, pk):
    db, ex = workspace.open_catalog(request, pk, "editor")
    if ex is None:
        raise ExplorerError("مرورگر فقط برای پایگاه داده فعال در دسترس است.")
    if db.status != db.Status.ACTIVE:
        raise ExplorerError("پایگاه داده فقط‌خواندنی یا غیرفعال است؛ ساخت جدول ممکن نیست.")
    return db, ex


@_builder_json
@require_POST
def table_preview(request, pk):
    _builder_guard(request, pk)
    plan = tablebuilder.build(_body(request).get("spec"))
    return JsonResponse({"ok": True, "sql": plan.script()})


@_builder_json
@require_POST
def table_new(request, pk):
    db, ex = _builder_guard(request, pk)
    if db.size_bytes >= db.quota_bytes:
        raise ExplorerError("سهمیه‌ی حجم پایگاه داده پر شده است؛ پلن را ارتقا دهید یا داده‌های اضافه را حذف کنید.")
    plan = tablebuilder.build(_body(request).get("spec"))
    spec = plan.spec
    if spec["schema"] not in ex.writable_schemas():
        raise ExplorerError("اجازه ساخت جدول در این schema را ندارید.")
    ex.create_table(plan)
    qualified = f"{spec['schema']}.{spec['name']}"
    services.logevent("table_create", f"جدول {qualified} ساخته شد ({len(spec['columns'])} ستون)",
                      user=request.user, database=db)
    return JsonResponse({"ok": True, "url": reverse("databases:explore_table",
                                                    args=[db.pk, spec["schema"], spec["name"]])})


@_builder_json
def table_srid(request, pk):
    _, ex = _builder_guard(request, pk)
    return JsonResponse({"ok": True, "items": ex.search_srid(request.GET.get("q", ""))})


@site_user_required
def explore_table(request, pk, schema, table):
    db, ex = workspace.open_catalog(request, pk)
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    try:
        tables = ex.tables()
        t = next((x for x in tables if x.schema == schema and x.name == table), None)
        if t is None:
            raise ExplorerError("جدول پیدا نشد.")
        tab = request.GET.get("tab", "data")
        ctx = {"db": db, "tables": tables, "t": t, "tab": tab, "section": "tables",
               "plugin_owners": plugin_tables.owners(db, t.schema, t.name)}
        editing = db.can_edit and db.status == db.Status.ACTIVE
        if editing:
            ctx["edit_cfg"] = _edit_config(request, db, ex, t)
        if tab == "columns":
            ctx["columns"] = ex.columns(t)
            ctx["indexes"] = ex.indexes(t)
            if editing and t.kind in editor.EDITABLE_KINDS:
                ctx["structure_cfg"] = _structure_config(request, db, t, ctx["columns"], ctx["indexes"])
        elif tab == "map":
            mappable = [x for x in tables if any(not g["geography"] and g["srid"] for g in x.geometry)]
            ctx["mappable"] = t in mappable
            if ctx["mappable"]:
                from analytics import services as analytics
                from analytics.models import Event

                analytics.record(request, Event.MAP_VIEWED)
            ctx["compare"] = len(mappable) > 1
            ctx["maps"] = []
            for part in events.collect(events.TABLE_MAP_TARGETS, ws=db, editable=db.can_edit):
                if isinstance(part, dict):
                    ctx.update(part)
        else:
            try:
                page = int(request.GET.get("page", "1"))
            except ValueError:
                page = 1
            ctx["data"] = ex.rows(t, page, with_keys=bool(editing and ctx["edit_cfg"]["capable"]))
            ctx["data"]["pairs"] = list(zip(ctx["data"]["rows"], ctx["data"]["keys"] or [None] * len(ctx["data"]["rows"]), strict=True))
    except ExplorerError as exc:
        messages.error(request, str(exc))
        return redirect("databases:explore", pk=db.pk)
    return render(request, "databases/explore_table.html", ctx)


@site_user_required
@require_POST
def explore_drop(request, pk, schema, table):
    db, ex = workspace.open_catalog(request, pk, "editor")
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    if db.status != db.Status.ACTIVE:
        messages.error(request, "پایگاه داده فقط‌خواندنی یا غیرفعال است.")
        return redirect("databases:explore", pk=db.pk)
    try:
        t = ex.find(schema, table)
        if request.POST.get("confirm", "").strip() != t.name:
            messages.error(request, "برای حذف، نام جدول را دقیقاً وارد کنید.")
            return redirect("databases:explore_table", pk=db.pk, schema=schema, table=table)
        ex.drop_table(t)
    except ExplorerError as exc:
        messages.error(request, str(exc))
        return redirect("databases:explore", pk=db.pk)
    # لایه‌ها و APIهای منتشرشده از این جدول دیگر معنا ندارند؛ پلاگین‌های صاحبشان پاک‌سازی می‌کنند (kernel.events)
    gone = sum(n for n in events.collect(events.TABLE_DROPPED, ws=db, schema=schema, table=table) if n is not True)
    messages.success(request, f"جدول {table} حذف شد." + (" انتشار آن هم برداشته شد." if gone else ""))
    return redirect("databases:explore", pk=db.pk)


@site_user_required
def explore_geojson(request, pk, schema, table):
    db, ex = workspace.open_catalog(request, pk)
    if ex is None:
        raise Http404
    try:
        t = ex.find(schema, table)
        download = request.GET.get("download") == "1"
        keys = request.GET.get("keys") == "1" and db.can_edit
        data = ex.geojson(t, request.GET.get("column"), limit=EXPORT_LIMIT if download else MAP_LIMIT, with_keys=keys)
    except ExplorerError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    resp = HttpResponse(data, content_type="application/geo+json")
    if download:
        resp["Content-Disposition"] = f'attachment; filename="{schema}.{table}.geojson"'
    return resp


@site_user_required
def explore_csv(request, pk, schema, table):
    db, ex = workspace.open_catalog(request, pk)
    if ex is None:
        raise Http404
    try:
        t = ex.find(schema, table)
    except ExplorerError as exc:
        raise Http404 from exc

    class Echo:
        def write(self, value):
            return value

    writer = csv.writer(Echo())

    def stream():
        yield "﻿"  # BOM برای باز شدن درست فارسی در Excel
        for row in ex.export_rows(t):
            yield writer.writerow(row)

    resp = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{schema}.{table}.csv"'
    return resp


# ---------------------------------------------------------------------- خروجی چندقالبی
@site_user_required
def explore_export(request, pk, schema, table, fmt):
    from django.http import FileResponse

    from databases import gdal

    db, ex = workspace.open_catalog(request, pk)
    if ex is None or fmt not in gdal.EXPORT_FORMATS:
        raise Http404
    try:
        t = ex.find(schema, table)
    except ExplorerError as exc:
        raise Http404 from exc
    workdir = gdal.new_workdir()
    try:
        geom = t.geometry[0]["column"] if t.geometry else None
        path = gdal.export_table(db, t.schema, t.name, fmt, workdir, geom_col=geom)
        fh = path.open("rb")  # فایل باز می‌ماند؛ پوشه موقت همین حالا پاک می‌شود
    except gdal.GdalError as exc:
        messages.error(request, f"ساخت خروجی ممکن نشد: {exc}")
        return redirect("databases:explore_table", pk=db.pk, schema=schema, table=table)
    finally:
        import shutil

        shutil.rmtree(workdir, ignore_errors=True)
    return FileResponse(fh, as_attachment=True, filename=path.name)


# ---------------------------------------------------------------------- تغییر ساختار جدول (ستون، ایندکس، SRID)
def _table_usage(db, t) -> dict:
    """لایه‌ها و APIهای منتشرشده یا نقشه‌هایی که از این جدول استفاده می‌کنند (برای هشدار قبل از تغییر ساختار)؛ هر پلاگین سهم خودش را می‌گوید."""
    out: dict = {}
    for part in events.collect(events.TABLE_USAGE, ws=db, schema=t.schema, table=t.name):
        if isinstance(part, dict):
            out.update(part)
    return out


def _structure_config(request, db, t, cols, indexes) -> dict:
    cfg = tablebuilder.client_config()
    geo = next(iter(t.geometry), None)
    return {
        "csrf": get_token(request), "url": reverse("databases:table_structure", args=[db.pk, t.schema, t.name]),
        "table": t.name, "schema": t.schema, "types": cfg["types"], "geometry_types": cfg["geometry_types"],
        "columns": [{"name": c["name"], "type": c["type"], "base": c["base"], "pk": c["pk"], "spatial": c["spatial"],
                     "not_null": c["not_null"], "default": c["default"], "identity": c["identity"],
                     "generated": c["generated"]} for c in cols],
        "indexes": [{"name": i["name"], "columns": i["columns"], "unique": i["unique"]} for i in indexes],
        "geometry": geo, "usage": _table_usage(db, t),
    }


@site_user_required
@require_POST
def table_structure(request, pk, schema, table):
    try:
        db, ex = workspace.open_catalog(request, pk, "editor")
        if ex is None:
            raise ExplorerError("مرورگر فقط برای پایگاه داده فعال در دسترس است.")
        if db.status != db.Status.ACTIVE:
            raise ExplorerError("پایگاه داده فقط‌خواندنی یا غیرفعال است؛ تغییر ساختار ممکن نیست.")
        t = ex.find(schema, table)
        if t.kind not in editor.EDITABLE_KINDS:
            raise ExplorerError("ساختار نما یا جدول خارجی از این‌جا تغییر نمی‌کند.")
        data = _body(request)
        plan = tablealter.build(t, ex.columns(t), ex.indexes(t), data.get("op"), data.get("params") or {})
        usage = _table_usage(db, t)
        if data.get("dry_run"):
            return JsonResponse({"ok": True, "sql": plan.script(), "summary": plan.summary, "danger": plan.danger,
                                 "usage": usage})
        if plan.danger and str(data.get("confirm", "")).strip() != plan.danger:
            raise ExplorerError(f"برای تأیید، «{plan.danger}» را دقیقاً بنویسید.")
        ex.alter_table(plan)
    except (tablebuilder.BuildError, EditError, ExplorerError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    if plan.touches_columns:
        EditBatch.objects.filter(database=db, schema=t.schema, table=t.name).delete()  # بازگردانی‌ها دیگر معنا ندارند
    final = plan.renamed_table or t.name
    if plan.renamed_table:
        events.emit(events.TABLE_RENAMED, ws=db, schema=t.schema, table=t.name, new=final)
    services.logevent("table_alter", f"{t.qualified}: {plan.summary}", user=request.user, database=db)
    return JsonResponse({"ok": True, "url": reverse("databases:explore_table", args=[db.pk, t.schema, final]) + "?tab=columns"})


# ---------------------------------------------------------------------- ویرایش جدول (حالت ویرایش)
def _edit_key(db) -> str:
    return f"gp_edit_until_{db.pk}"


def _edit_active(request, db) -> bool:
    return request.session.get(_edit_key(db), 0) > time.time()


def _edit_config(request, db, ex, t) -> dict:
    """تنظیمات و فراداده‌ی ویرایش که جاوااسکریپت صفحه لازم دارد."""
    cols = ex.columns(t)
    cap = editor.edit_capability(t, cols)
    writable = editor.editable_columns(cols)
    args = [db.pk, t.schema, t.name]
    last = (EditBatch.objects.filter(database=db, schema=t.schema, table=t.name, undone_at__isnull=True).first()
            if cap["ok"] else None)
    return {
        "capable": cap["ok"], "reason": cap["reason"], "active": cap["ok"] and _edit_active(request, db),
        "csrf": get_token(request), "ttl": EDIT_TTL, "key": f"gp-edit-{db.pk}-{t.schema}.{t.name}", "table": t.qualified,
        "pk": [c["name"] for c in cols if c["pk"]],
        "columns": [{"name": c["name"], "type": c["type"], "base": c["base"], "not_null": c["not_null"],
                     "default": c["default"], "pk": c["pk"], "spatial": c["spatial"],
                     "writable": c["name"] in writable, "identity": c["identity"], "generated": c["generated"]}
                    for c in cols],
        "geometry": t.geometry,
        "tiles": SiteSettings.get().map_tile_url, "attr": SiteSettings.get().map_tile_attribution,
        "vendor": {"leaflet_js": static("vendor/leaflet/leaflet.js"), "leaflet_css": static("vendor/leaflet/leaflet.css"),
                   "pm_js": static("vendor/leaflet-geoman/leaflet-geoman.min.js"),
                   "pm_css": static("vendor/leaflet-geoman/leaflet-geoman.css")},
        "urls": {k: reverse(f"databases:explore_edit_{k}", args=args) for k in ("mode", "row", "apply", "undo")},
        "geojson": reverse("databases:explore_geojson", args=args) + "?keys=1",
        "last": ({"id": last.pk, "inserted": last.inserted, "updated": last.updated, "deleted": last.deleted,
                  "at": timezone.localtime(last.created_at).strftime("%H:%M")} if last else None),
    }


def _body(request) -> dict:
    if len(request.body) > 8 * 1024 * 1024:
        raise EditError("حجم تغییرها بیش از حد است.")
    try:
        data = json.loads(request.body or b"{}")
    except ValueError as exc:
        raise EditError("درخواست نامعتبر است.") from exc
    if not isinstance(data, dict):
        raise EditError("درخواست نامعتبر است.")
    return data


def _edit_guard(request, pk, schema, table, need_mode: bool = True):
    """دسترسی ویرایشگر، پایگاه داده‌ی فعال، جدول قابل‌ویرایش و (در صورت نیاز) روشن‌بودن حالت ویرایش."""
    db = workspace.get(request, pk, "editor")
    if not db.is_live or db.status != db.Status.ACTIVE:
        raise EditError("پایگاه داده فعال نیست یا فقط‌خواندنی است؛ ویرایش ممکن نیست.")
    ex = Explorer(db)
    t = ex.find(schema, table)
    if need_mode and not _edit_active(request, db):
        raise EditError("حالت ویرایش خاموش یا منقضی شده است. دوباره آن را روشن کنید.")
    return db, ex, t


def _edit_json(view):
    def wrapper(request, pk, schema, table):
        try:
            return view(request, pk, schema, table)
        except EditError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        except ExplorerError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    wrapper.__name__ = view.__name__
    return site_user_required(wrapper)


@_edit_json
@require_POST
def explore_edit_mode(request, pk, schema, table):
    on = bool(_body(request).get("on"))
    db, ex, t = _edit_guard(request, pk, schema, table, need_mode=False)
    if on:
        cap = editor.edit_capability(t, ex.columns(t))
        if not cap["ok"]:
            raise EditError(cap["reason"])
        request.session[_edit_key(db)] = time.time() + EDIT_TTL
        services.logevent("edit_mode_on", f"حالت ویرایش روشن شد: {t.qualified}", user=request.user, database=db)
    else:
        request.session.pop(_edit_key(db), None)
    return JsonResponse({"ok": True, "on": on, "ttl": EDIT_TTL})


@_edit_json
def explore_edit_row(request, pk, schema, table):
    db, ex, t = _edit_guard(request, pk, schema, table)
    try:
        key = json.loads(request.GET.get("pk", ""))
    except ValueError as exc:
        raise EditError("کلید سطر نامعتبر است.") from exc
    return JsonResponse({"ok": True, **Editor(ex).row(t, key)})


@_edit_json
@require_POST
def explore_edit_apply(request, pk, schema, table):
    data = _body(request)
    db, ex, t = _edit_guard(request, pk, schema, table)
    dry = bool(data.get("dry_run"))
    out = Editor(ex).apply(t, data.get("changes"), dry_run=dry, repair=bool(data.get("repair")))
    request.session[_edit_key(db)] = time.time() + EDIT_TTL  # کار فعال، مهلت را تمدید می‌کند
    resp = {"ok": out["ok"], "results": out["results"], "counts": out["counts"], "dry_run": dry}
    if out["ok"] and not dry:
        c = out["counts"]
        batch = EditBatch.objects.create(database=db, user=request.user, schema=t.schema, table=t.name,
                                         inserted=c["insert"], updated=c["update"], deleted=c["delete"],
                                         undo=out["undo"])
        for old in EditBatch.objects.filter(database=db).order_by("-created_at", "-pk")[editor.KEEP_BATCHES:]:
            old.delete()
        services.logevent("table_edit", f"{t.qualified}: {c['insert']} افزودن، {c['update']} ویرایش، {c['delete']} حذف",
                          user=request.user, database=db)
        resp["batch"] = batch.pk
    elif not out["ok"]:
        resp["error"] = "چند تغییر اعمال نشد؛ هیچ‌چیز ذخیره نشد. خطاها را بررسی کنید."
    return JsonResponse(resp)


@_edit_json
@require_POST
def explore_edit_undo(request, pk, schema, table):
    data = _body(request)
    db, ex, t = _edit_guard(request, pk, schema, table)
    batch = EditBatch.objects.filter(database=db, schema=t.schema, table=t.name, undone_at__isnull=True).first()
    if batch is None or batch.pk != data.get("batch"):
        raise EditError("ذخیره‌ی تازه‌تری وجود دارد یا چیزی برای بازگرداندن نیست؛ صفحه را تازه کنید.")
    out = Editor(ex).apply(t, batch.undo, internal=True)
    if not out["ok"]:
        return JsonResponse({"ok": False, "results": out["results"],
                             "error": "بازگردانی ممکن نشد؛ بعد از آن ذخیره، ردیف‌ها دوباره تغییر کرده‌اند. چیزی برگردانده نشد."},
                            status=409)
    batch.undone_at = timezone.now()
    batch.save(update_fields=["undone_at"])
    services.logevent("table_edit_undo", f"ذخیره‌ی {batch.created_at:%H:%M} برگردانده شد: {t.qualified}",
                      user=request.user, database=db)
    return JsonResponse({"ok": True})
