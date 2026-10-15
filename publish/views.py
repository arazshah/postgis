"""صفحه «انتشار» هر پایگاه داده: انتشار جدول‌های مکانی، عمومی/خصوصی، کلیدهای API و نمونه کد."""
import json
import re

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

from . import access, engine
from .models import ApiKey, Layer, Service

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
STYLE_DEFAULT = {"mode": "single", "color": "#0F5C59", "opacity": 0.75, "size": 6, "outline": "#FFFFFF",
                 "field": "", "classes": 5, "palette": "YlOrRd", "breaks": [], "categories": [], "popup": [],
                 "basemap": "iran", "label": "", "label_color": "#1B2B2F", "label_size": 12}
BASEMAPS = ("iran", "osm", "none")
PALETTES = {
    "YlOrRd": ["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#bd0026", "#800026", "#4d0019"],
    "Blues": ["#eff3ff", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#08519c", "#08306b", "#041d43"],
    "Greens": ["#edf8e9", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d", "#238b45", "#006d2c", "#00441b", "#00290f"],
    "Viridis": ["#440154", "#472d7b", "#3b528b", "#2c728e", "#21918c", "#28ae80", "#5ec962", "#addc30", "#fde725"],
    "RdYlGn": ["#d73027", "#f46d43", "#fdae61", "#fee08b", "#ffffbf", "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850"],
    "Teal": ["#e6f2ef", "#c2e0d8", "#9dcdc1", "#78baa9", "#53a792", "#2e947a", "#0f7e66", "#0f5c59", "#073b3a"],
}
CATEGORY_COLORS = ["#0F5C59", "#E0A526", "#B42318", "#2B6CB0", "#7A4FB5", "#1A7F4B", "#D9480F", "#5C7080",
                   "#C2185B", "#0097A7", "#8D6E63", "#9E9D24"]


HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _style(layer) -> dict:
    from iranmap import basemap

    style = {**STYLE_DEFAULT, **(layer.style or {})}
    if style["basemap"] == "iran" and not basemap.available():
        style["basemap"] = "osm"
    return style


def map_config(request, layer, embed=False) -> dict:
    from core.models import SiteSettings
    from iranmap import basemap

    db = layer.service.database
    tiles = request.build_absolute_uri(f"/tiles/{layer.slug}/") + "{z}/{x}/{y}.mvt"
    conf = SiteSettings.get()
    style = _style(layer)
    return {
        "tiles": tiles, "sourceLayer": layer.collection_id, "geomType": (layer.geom_type or "").upper(),
        "bbox": layer.bbox, "style": style, "palettes": PALETTES,
        "basemap": conf.map_tile_url,
        "basemapAttribution": conf.map_tile_attribution or "© OpenStreetMap",
        "iranStyle": request.build_absolute_uri("/basemap/style.json") if basemap.available() else "",
        # پوشه است، نه فایل؛ static() با manifest برای آن خطا می‌دهد
        "glyphs": request.build_absolute_uri(settings.STATIC_URL + "basemap/fonts/") + "{fontstack}/{range}.pbf",
        "rtlPlugin": request.build_absolute_uri(static("vendor/rtl-text/mapbox-gl-rtl-text.js")),
        "title": layer.display_title, "description": layer.description, "embed": embed,
        "badge": db.plan.map_badge, "home": request.build_absolute_uri("/"),
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
        style = {k: data[k] for k in STYLE_DEFAULT if k in data}
        style["mode"] = style.get("mode") if style.get("mode") in ("single", "graduated", "categorized") else "single"
        style["palette"] = style.get("palette") if style.get("palette") in PALETTES else "YlOrRd"
        style["basemap"] = style.get("basemap") if style.get("basemap") in BASEMAPS else "osm"
        for k, lo, hi in (("opacity", 0.05, 1), ("size", 1, 40), ("classes", 2, 9)):
            try:
                style[k] = max(lo, min(hi, float(style.get(k, STYLE_DEFAULT[k]))))
            except (TypeError, ValueError):
                style[k] = STYLE_DEFAULT[k]
        style["classes"] = int(style["classes"])
        try:
            style["label_size"] = int(max(8, min(24, float(style.get("label_size", 12)))))
        except (TypeError, ValueError):
            style["label_size"] = 12
        for k in ("color", "outline", "label_color"):
            if not HEX_RE.match(str(style.get(k, ""))):
                style[k] = STYLE_DEFAULT[k]
        try:
            style["breaks"] = [float(b) for b in style.get("breaks", [])][:8]
        except (TypeError, ValueError):
            style["breaks"] = []
        style["categories"] = [{"value": str(c.get("value", ""))[:200], "color": c["color"]}
                               for c in style.get("categories", [])[:12]
                               if isinstance(c, dict) and HEX_RE.match(str(c.get("color", "")))]
        try:
            names = {n for n, _ in engine.field_names(layer)}
        except engine.EngineError as exc:
            messages.error(request, str(exc))
            return redirect("publish:map_builder", pk=db.pk, layer_id=layer.pk)
        style["popup"] = [c for c in style.get("popup", []) if c in names][:12]
        if style.get("field") not in names:
            style["field"], style["mode"] = "", "single"
        if style.get("label") not in names:
            style["label"] = ""
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
