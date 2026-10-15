"""صفحه «انتشار» هر پایگاه داده: انتشار جدول‌های مکانی، عمومی/خصوصی، کلیدهای API و نمونه کد."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import site_user_required
from databases.explorer import Explorer, ExplorerError
from databases.models import UserDatabase

from . import access, engine
from .models import ApiKey, Layer, Service

SESSION_KEY = "publish_new_key_{}"


def _db(request, pk) -> UserDatabase:
    return get_object_or_404(UserDatabase.objects.select_related("server", "plan")
                             .exclude(status=UserDatabase.Status.DELETED), pk=pk, owner=request.user)


@site_user_required
def manage(request, pk):
    db = _db(request, pk)
    if not db.is_live:
        messages.error(request, "انتشار فقط برای پایگاه داده فعال در دسترس است.")
        return redirect("databases:detail", pk=db.pk)
    service = Service.objects.filter(database=db).first()
    layers = {(x.schema, x.table): x for x in (service.layers.all() if service else [])}
    try:
        tables = Explorer(db).tables()
    except ExplorerError as exc:
        messages.error(request, str(exc))
        tables = []
    rows = []
    for t in tables:
        geoms = [g for g in t.geometry if not g["geography"]]
        if not geoms:
            continue
        rows.append({"t": t, "geom": geoms[0], "layer": layers.get((t.schema, t.name))})
    published = [r["layer"] for r in rows if r["layer"]]
    for layer in published:
        try:
            layer.meta = engine.describe(layer)
        except engine.EngineError:
            layer.meta = {"columns": [], "pk": ""}
    return render(request, "publish/manage.html", {
        "db": db, "service": service, "rows": rows, "published": published,
        "keys": db.api_keys.all(), "new_key": request.session.pop(SESSION_KEY.format(db.pk), None),
        "used": access.usage_today(db), "cap": db.plan.publish_daily_requests, "max_layers": db.plan.publish_layers,
        "base": request.build_absolute_uri("/")[:-1], "section": "publish",
    })


@site_user_required
@require_POST
def publish_table(request, pk):
    db = _db(request, pk)
    schema, table = request.POST.get("schema", ""), request.POST.get("table", "")
    try:
        t = Explorer(db).find(schema, table)
    except ExplorerError as exc:
        messages.error(request, str(exc))
        return redirect("publish:manage", pk=db.pk)
    geoms = [g for g in t.geometry if not g["geography"]]
    service, _ = Service.objects.get_or_create(database=db)
    if not geoms:
        messages.error(request, "این جدول ستون هندسه (geometry) ندارد.")
    elif not geoms[0]["srid"]:
        messages.error(request, "سیستم مختصات ستون هندسه مشخص نیست (SRID 0). از «سلامت داده» آن را تعیین کنید.")
    elif service.layers.count() >= db.plan.publish_layers:
        messages.error(request, f"پلن شما حداکثر {db.plan.publish_layers} لایه منتشرشده دارد. "
                                "یک لایه را لغو انتشار کنید یا پلن را ارتقا دهید.")
    else:
        layer, created = Layer.objects.get_or_create(
            service=service, schema=t.schema, table=t.name,
            defaults={"geom_column": geoms[0]["column"], "srid": geoms[0]["srid"], "geom_type": geoms[0]["type"],
                      "is_public": request.POST.get("public") == "on"})
        try:
            layer.pk_column = engine.describe(layer)["pk"]
            layer.bbox = engine.extent(layer)
            layer.save(update_fields=["pk_column", "bbox"])
        except engine.EngineError:
            pass
        messages.success(request, f"لایه {t.name} منتشر شد." if created else "این لایه قبلاً منتشر شده است.")
    return redirect("publish:manage", pk=db.pk)


@site_user_required
@require_POST
def update_layer(request, pk, layer_id):
    db = _db(request, pk)
    layer = get_object_or_404(Layer, pk=layer_id, service__database=db)
    action = request.POST.get("action")
    if action == "unpublish":
        layer.delete()
        messages.success(request, f"انتشار {layer.table} لغو شد؛ آدرس‌های آن دیگر کار نمی‌کنند.")
        return redirect("publish:manage", pk=db.pk)
    layer.title = request.POST.get("title", "")[:120]
    layer.is_public = request.POST.get("public") == "on"
    cols = request.POST.getlist("columns")
    try:
        meta = engine.describe(layer)
        names = [n for n, _ in meta["columns"] if n != layer.geom_column]
        layer.columns = [] if set(cols) >= set(names) else [c for c in cols if c in names]
        layer.pk_column = meta["pk"]
        layer.bbox = engine.extent(layer)
    except engine.EngineError as exc:
        messages.error(request, str(exc))
    layer.save()
    messages.success(request, f"تنظیمات {layer.table} ذخیره شد.")
    return redirect("publish:manage", pk=db.pk)


@site_user_required
@require_POST
def create_key(request, pk):
    db = _db(request, pk)
    if db.api_keys.filter(revoked_at__isnull=True).count() >= 10:
        messages.error(request, "حداکثر ۱۰ کلید فعال؛ یک کلید قدیمی را باطل کنید.")
        return redirect("publish:manage", pk=db.pk)
    _key, raw = ApiKey.issue(db, request.user, request.POST.get("name") or "کلید")
    request.session[SESSION_KEY.format(db.pk)] = raw
    return redirect("publish:manage", pk=db.pk)


@site_user_required
@require_POST
def revoke_key(request, pk, key_id):
    db = _db(request, pk)
    key = get_object_or_404(ApiKey, pk=key_id, database=db)
    key.revoke()
    messages.success(request, f"کلید «{key.name}» باطل شد.")
    return redirect("publish:manage", pk=db.pk)
