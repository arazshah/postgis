"""صفحه «انتشار» هر پایگاه داده: انتشار جدول‌های مکانی، عمومی/خصوصی، کلیدهای API و نمونه کد."""
import json

from django.conf import settings
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_POST

from accounts.decorators import site_user_required
from databases.explorer import Explorer, ExplorerError
from databases.models import UserDatabase

from . import access, engine, styles
from .models import ApiKey, Layer, Service
from .styles import CATEGORY_COLORS, PALETTES, STYLE_DEFAULT

SESSION_KEY = "publish_new_key_{}"


def _db(request, pk, need: str = "editor") -> UserDatabase:
    """انتشار: مالک و ویرایشگرهای تیم؛ کلیدهای API فقط مالک."""
    from databases import team

    return team.get_db(request, pk, need)


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
        "base": request.build_absolute_uri("/")[:-1], "section": "publish", "iran_basemap": _iran_basemap(),
    })


def _iran_basemap() -> bool:
    from iranmap import basemap

    return basemap.available()


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
    db = _db(request, pk, "owner")
    if db.api_keys.filter(revoked_at__isnull=True).count() >= 10:
        messages.error(request, "حداکثر ۱۰ کلید فعال؛ یک کلید قدیمی را باطل کنید.")
        return redirect("publish:manage", pk=db.pk)
    _key, raw = ApiKey.issue(db, request.user, request.POST.get("name") or "کلید",
                             can_write=request.POST.get("can_write") == "on")
    request.session[SESSION_KEY.format(db.pk)] = raw
    return redirect("publish:manage", pk=db.pk)


@site_user_required
@require_POST
def revoke_key(request, pk, key_id):
    db = _db(request, pk, "owner")
    key = get_object_or_404(ApiKey, pk=key_id, database=db)
    key.revoke()
    messages.success(request, f"کلید «{key.name}» باطل شد.")
    return redirect("publish:manage", pk=db.pk)


# ---------------------------------------------------------------------- طراحی و نمایش نقشه

def _style(layer) -> dict:
    from iranmap import basemap

    style = {**STYLE_DEFAULT, **(layer.style or {})}
    if style["basemap"] == "iran" and not basemap.available():
        style["basemap"] = "osm"
    return style


def base_config(request) -> dict:
    """تنظیمات مشترک همه نقشه‌های MapLibre سایت: نقشه پایه، قلم برچسب‌ها و افزونه راست‌به‌چپ."""
    from core.models import SiteSettings
    from iranmap import basemap

    conf = SiteSettings.get()
    return {
        "palettes": PALETTES,
        "basemap": conf.map_tile_url,
        "basemapAttribution": conf.map_tile_attribution or "© OpenStreetMap",
        "iranStyle": request.build_absolute_uri("/basemap/style.json") if basemap.available() else "",
        # پوشه است، نه فایل؛ static() با manifest برای آن خطا می‌دهد
        "glyphs": request.build_absolute_uri(settings.STATIC_URL + "basemap/fonts/") + "{fontstack}/{range}.pbf",
        "rtlPlugin": request.build_absolute_uri(static("vendor/rtl-text/mapbox-gl-rtl-text.js")),
        "home": request.build_absolute_uri("/"),
    }


def map_config(request, layer, embed=False) -> dict:
    db = layer.service.database
    tiles = request.build_absolute_uri(f"/tiles/{layer.slug}/") + "{z}/{x}/{y}.mvt"
    return {
        **base_config(request),
        "tiles": tiles, "sourceLayer": layer.collection_id, "geomType": (layer.geom_type or "").upper(),
        "bbox": layer.bbox, "style": _style(layer),
        "title": layer.display_title, "description": layer.description, "embed": embed,
        "badge": db.plan.map_badge,
    }


@site_user_required
def map_builder(request, pk, layer_id):
    db = _db(request, pk)
    layer = get_object_or_404(Layer.objects.select_related("service__database__plan"), pk=layer_id,
                              service__database=db)
    if request.method == "POST":
        try:
            data = json.loads(request.POST.get("style", "{}"))
        except ValueError:
            data = {}
        try:
            names = {n for n, _ in engine.field_names(layer)}
        except engine.EngineError as exc:
            messages.error(request, str(exc))
            return redirect("publish:map_builder", pk=db.pk, layer_id=layer.pk)
        style = styles.clean(data, names)
        layer.style = style
        layer.title = request.POST.get("title", layer.title)[:120]
        layer.description = request.POST.get("description", layer.description)[:1000]
        layer.save()
        messages.success(request, "سبک نقشه ذخیره شد.")
        return redirect("publish:map_builder", pk=db.pk, layer_id=layer.pk)
    try:
        fields = engine.field_names(layer)
    except engine.EngineError as exc:
        messages.error(request, str(exc))
        fields = []
    from iranmap import basemap

    return render(request, "publish/builder.html", {
        "db": db, "layer": layer, "fields": fields, "palettes": PALETTES, "iran_basemap": basemap.available(),
        "config": map_config(request, layer),
        "public_url": request.build_absolute_uri(f"/m/{layer.slug}/"),
        "embed_url": request.build_absolute_uri(f"/m/{layer.slug}/embed/"),
    })


@site_user_required
def map_stats(request, pk, layer_id):
    db = _db(request, pk)
    layer = get_object_or_404(Layer, pk=layer_id, service__database=db)
    mode = request.GET.get("mode", "graduated")
    try:
        stats = engine.field_stats(layer, request.GET.get("field", ""), mode, int(request.GET.get("classes", 5)))
    except (engine.EngineError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400, json_dumps_params={"ensure_ascii": False})
    if mode == "categorized":
        stats["colors"] = CATEGORY_COLORS[:len(stats["values"])]
    return JsonResponse(stats, json_dumps_params={"ensure_ascii": False})


def _public_layer(request, slug) -> Layer:
    layer = get_object_or_404(Layer.objects.select_related("service__database__plan"), slug=slug)
    db = layer.service.database
    if db.status not in UserDatabase.LIVE_STATUSES:
        raise Http404
    if not layer.is_public and not access.is_owner(request, db):
        raise Http404
    return layer


def public_map(request, slug, embed=False):
    layer = _public_layer(request, slug)
    resp = render(request, "publish/map.html", {
        "layer": layer, "embed": embed, "config": map_config(request, layer, embed),
        "public_url": request.build_absolute_uri(f"/m/{layer.slug}/"),
    })
    # نقشه پایه OSM بدون Referer کاشی نمی‌دهد؛ فقط دامنه فرستاده می‌شود
    resp["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp


@xframe_options_exempt
def embed_map(request, slug):
    return public_map(request, slug, embed=True)
