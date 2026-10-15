"""مدیریت REST API و فرم‌های میدانی یک پایگاه داده (مالک و ویرایشگرها)."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.decorators import site_user_required
from databases import team
from databases.explorer import Explorer, ExplorerError
from publish.models import Service

from . import engine
from .models import ApiTable, FieldForm


@site_user_required
@require_http_methods(["GET", "POST"])
def manage(request, pk):
    db = team.get_db(request, pk, "editor")
    if not db.is_live:
        messages.error(request, "پایگاه داده فعال نیست.")
        return redirect("databases:detail", pk=db.pk)
    service, _ = Service.objects.get_or_create(database=db)
    here = redirect("restapi:manage", pk=db.pk)
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "save_table":
            schema, _, table = (request.POST.get("table") or "").partition(".")
            try:
                meta = engine.describe(db, schema, table)
            except engine.RestError as exc:
                messages.error(request, str(exc))
                return here
            if request.POST.get("enabled") != "on":
                ApiTable.objects.filter(service=service, schema=schema, table=table).delete()
                messages.success(request, f"{table} از REST API برداشته شد.")
                return here
            writes = {k: request.POST.get(k) == "on" for k in ("can_insert", "can_update", "can_delete")}
            if (writes["can_update"] or writes["can_delete"]) and not meta["pk"]:
                messages.error(request, "برای ویرایش و حذف، جدول کلید اصلی تک‌ستونی لازم دارد (بخش «سلامت داده»).")
                return here
            ApiTable.objects.update_or_create(service=service, schema=schema, table=table, defaults={
                "public_read": request.POST.get("public_read") == "on", **writes})
            messages.success(request, f"تنظیم REST API جدول {table} ذخیره شد.")
            return here
        if action == "form_create":
            t = get_object_or_404(ApiTable, pk=request.POST.get("api_table"), service=service)
            fields = request.POST.getlist("fields")
            title = (request.POST.get("title") or "").strip()
            if not title or not fields:
                messages.error(request, "عنوان و دست‌کم یک ستون برای فرم لازم است.")
                return here
            if not t.can_insert:
                t.can_insert = True
                t.save(update_fields=["can_insert"])
            f = FieldForm.objects.create(api_table=t, title=title[:120], intro=request.POST.get("intro", "")[:2000],
                                         fields=fields[:40], access=request.POST.get("access") or "team")
            messages.success(request, f"فرم «{f.title}» ساخته شد.")
            return here
        f = FieldForm.objects.filter(pk=request.POST.get("form") or 0, api_table__service=service).first()
        if f and action == "form_toggle":
            f.is_open = not f.is_open
            f.save(update_fields=["is_open"])
        elif f and action == "form_delete":
            f.delete()
            messages.success(request, "فرم حذف شد؛ داده‌های ثبت‌شده در جدول می‌مانند.")
        return here
    try:
        tables = [t for t in Explorer(db).tables() if t.kind in ("r", "p")]
    except ExplorerError as exc:
        messages.error(request, str(exc))
        tables = []
    api = {(a.schema, a.table): a for a in service.api_tables.prefetch_related("forms")}
    rows = []
    for t in tables:
        if t.schema in ("routing",) and t.name in ("configuration", "pointsofinterest"):
            continue
        rows.append({"t": t, "api": api.get((t.schema, t.name))})
    form_cols = {}
    for a in api.values():
        try:
            m = engine.describe(db, a.schema, a.table)
            form_cols[a.pk] = [c["name"] for c in m["columns"] if c is not m["geom"] and c["name"] != m["pk"]]
        except engine.RestError:
            form_cols[a.pk] = []
    base = request.build_absolute_uri("/")[:-1]
    return render(request, "restapi/manage.html", {
        "db": db, "service": service, "rows": rows, "apis": list(api.values()), "form_cols": form_cols,
        "base": base, "sample": next(iter(api.values()), None), "forms": FieldForm.objects.filter(
            api_table__service=service).select_related("api_table"),
    })
