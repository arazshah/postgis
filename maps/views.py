"""نقشه‌های چندلایه: فهرست، طراحی، «نمایش با هم» بدون ذخیره، صفحه عمومی، embed و کاشی هر لایه."""
from __future__ import annotations

import json
import logging
from urllib.parse import quote

from django.contrib import messages
from django.core.cache import cache
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import site_user_required
from databases import team
from databases.explorer import ExplorerError
from databases.models import UserDatabase
from publish import access, engine, styles
from publish.styles import CATEGORY_COLORS
from publish.views import base_config

from . import qgis_export, services
from .models import MapLayer, MapSlide, WebMap
from .services import MapError

log = logging.getLogger(__name__)
TILE_TTL = 60
MAX_SLIDES = 30


def _json(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def _db(request, pk, need="editor") -> UserDatabase:
    return team.get_db(request, pk, need)


def _live(request, db) -> bool:
    if not db.is_live:
        messages.error(request, "نقشه‌ها فقط برای پایگاه داده فعال در دسترس است.")
        return False
    return True


def _map(db, map_id) -> WebMap:
    return get_object_or_404(WebMap.objects.select_related("database__plan", "database__server"), pk=map_id,
                             database=db)


def _basemap(kind: str) -> str:
    from iranmap import basemap

    if kind == "iran" and not basemap.available():
        return "osm"
    return kind if kind in styles.BASEMAPS else "osm"


def _layer_conf(request, layer: MapLayer, tiles: str, key: str, fields=False) -> dict:
    conf = {"key": key, "id": layer.pk, "title": layer.display_title, "table": layer.collection_id,
            "tiles": request.build_absolute_uri(tiles) + "{z}/{x}/{y}.mvt", "sourceLayer": layer.collection_id,
            "geomType": (layer.geom_type or "").upper(), "style": services.layer_style(layer),
            "visible": layer.visible, "bbox": layer.bbox}
    if fields:
        try:
            conf["fields"] = services.all_fields(layer)
        except (engine.EngineError, ExplorerError):
            conf["fields"], conf["missing"] = [], True
    return conf


def _tiles_path(webmap: WebMap, layer: MapLayer) -> str:
    return f"/maps/{webmap.slug}/t/{layer.pk}/"


def map_config(request, webmap: WebMap, embed=False, fields=False) -> dict:
    layers = list(webmap.layers.all())
    return {
        **base_config(request),
        "title": webmap.title, "description": webmap.description, "embed": embed, "slug": webmap.slug,
        "basemapKind": _basemap(webmap.basemap), "view": webmap.view or {},
        "badge": webmap.database.plan.map_badge,
        "layers": [_layer_conf(request, x, _tiles_path(webmap, x), f"ml{x.pk}", fields) for x in layers],
        "slides": [{"title": x.title, "body": x.body, "view": x.view, "layers": [f"ml{i}" for i in x.layers]}
                   for x in webmap.slides.all()],
    }


# ---------------------------------------------------------------------- فهرست و ساخت
@site_user_required
def index(request, pk):
    db = _db(request, pk, "viewer")
    if not _live(request, db):
        return redirect("databases:detail", pk=db.pk)
    try:
        tables = services.spatial_tables(db)
    except ExplorerError as exc:
        messages.error(request, str(exc))
        tables = []
    maps = list(WebMap.objects.filter(database=db).prefetch_related("layers"))
    return render(request, "maps/index.html", {
        "db": db, "maps": maps, "tables": tables, "cap": db.plan.maps, "layer_cap": db.plan.map_layers,
        "base": request.build_absolute_uri("/")[:-1],
    })


@site_user_required
@require_POST
def create(request, pk):
    db = _db(request, pk)
    if not _live(request, db):
        return redirect("databases:detail", pk=db.pk)
    keys = request.POST.getlist("t")
    try:
        webmap = services.create_map(db, request.user, request.POST.get("title", "").strip(), keys,
                                     request.POST.get("description", "").strip())
    except (MapError, ExplorerError) as exc:
        messages.error(request, str(exc))
        back = request.POST.get("back")
        if back == "quick" and keys:
            return redirect(reverse("maps:quick", args=[db.pk]) + "?" + "&".join(f"t={k}" for k in keys))
        return redirect("maps:index", pk=db.pk)
    messages.success(request, f"نقشه «{webmap.title}» ساخته شد.")
    return redirect("maps:composer", pk=db.pk, map_id=webmap.pk)


@site_user_required
@require_POST
def add_table(request, pk):
    """از مرورگر جدول: افزودن جدول به یک نقشه موجود یا نقشه تازه."""
    db = _db(request, pk)
    schema, table = request.POST.get("schema", ""), request.POST.get("table", "")
    target = request.POST.get("map", "new")
    back = redirect(reverse("databases:explore_table", args=[db.pk, schema, table]) + "?tab=map") if table \
        else redirect("maps:index", pk=db.pk)
    if not _live(request, db):
        return back
    try:
        if target == "new":
            webmap = services.create_map(db, request.user, f"نقشه {table}", [f"{schema}.{table}"])
        else:
            try:
                webmap = _map(db, int(target))
            except ValueError as exc:
                raise Http404 from exc
            services.add_layer(webmap, schema, table)
    except (MapError, ExplorerError) as exc:
        messages.error(request, str(exc))
        return back
    messages.success(request, f"جدول «{table}» به نقشه «{webmap.title}» اضافه شد.")
    return redirect("maps:composer", pk=db.pk, map_id=webmap.pk)


@site_user_required
@require_POST
def delete(request, pk, map_id):
    db = _db(request, pk)
    webmap = _map(db, map_id)
    webmap.delete()
    messages.success(request, f"نقشه «{webmap.title}» حذف شد؛ لینک و کد جاسازی آن دیگر کار نمی‌کند.")
    return redirect("maps:index", pk=db.pk)


@site_user_required
@require_POST
def duplicate(request, pk, map_id):
    db = _db(request, pk)
    try:
        copy = services.duplicate(_map(db, map_id), request.user)
    except MapError as exc:
        messages.error(request, str(exc))
        return redirect("maps:index", pk=db.pk)
    messages.success(request, f"نقشه «{copy.title}» ساخته شد.")
    return redirect("maps:composer", pk=db.pk, map_id=copy.pk)


# ---------------------------------------------------------------------- طراحی نقشه
def _clean_view(view):
    if not isinstance(view, dict):
        return {}
    try:
        lon, lat = (float(v) for v in view.get("center", [])[:2])
        zoom = float(view.get("zoom"))
    except (TypeError, ValueError):
        return {}
    if not (-180 <= lon <= 180 and -85 <= lat <= 85 and 0 <= zoom <= 22):
        return {}
    return {"center": [round(lon, 6), round(lat, 6)], "zoom": round(zoom, 2)}


def _save(webmap: WebMap, data: dict):
    webmap.title = (str(data.get("title") or "").strip() or webmap.title)[:120]
    webmap.description = str(data.get("description") or "")[:1000]
    webmap.is_public = bool(data.get("is_public"))
    webmap.basemap = data.get("basemap") if data.get("basemap") in styles.BASEMAPS else "osm"
    webmap.view = _clean_view(data.get("view"))
    layers = {x.pk: x for x in webmap.layers.all()}
    order = []
    for item in data.get("layers") or []:
        if not isinstance(item, dict):
            continue
        try:
            layer = layers.get(int(item.get("id")))
        except (TypeError, ValueError):
            continue
        if layer is None or layer in order:
            continue
        order.append(layer)
        layer.title = str(item.get("title") or "")[:120]
        layer.visible = bool(item.get("visible", True))
        try:
            names = {n for n, _ in services.all_fields(layer)}
        except (engine.EngineError, ExplorerError):
            continue  # جدول در دسترس نیست؛ سبک قبلی می‌ماند
        style = styles.clean(item.get("style"), names)
        style.pop("basemap", None)
        layer.style = style
    rest = [x for x in layers.values() if x not in order]
    for i, layer in enumerate(order + rest):
        layer.position = i
        layer.save()
    if isinstance(data.get("slides"), list):
        _save_slides(webmap, data["slides"], set(layers))
    webmap.save()


def _save_slides(webmap: WebMap, items: list, layer_ids: set[int]):
    """اسلایدهای ارائه همه با هم جایگزین می‌شوند؛ نمای نامعتبر یعنی همان نمای شروع نقشه."""
    slides = []
    for item in items[:MAX_SLIDES]:
        if not isinstance(item, dict):
            continue
        view = _clean_view(item.get("view"))
        try:
            bearing = float((item.get("view") or {}).get("bearing", 0))
        except (TypeError, ValueError, AttributeError):
            bearing = 0
        if view and -180 <= bearing <= 360 and bearing:
            view["bearing"] = round(bearing, 1)
        ids = []
        for v in item.get("layers") or []:
            try:
                v = int(str(v).removeprefix("ml"))
            except ValueError:
                continue
            if v in layer_ids and v not in ids:
                ids.append(v)
        slides.append(MapSlide(webmap=webmap, position=len(slides), title=str(item.get("title") or "")[:120],
                               body=str(item.get("body") or "")[:2000], view=view, layers=ids))
    webmap.slides.all().delete()
    MapSlide.objects.bulk_create(slides)


@site_user_required
def composer(request, pk, map_id):
    db = _db(request, pk)
    webmap = _map(db, map_id)
    if request.method == "POST":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return _json({"error": "داده نامعتبر است."}, 400)
        if not isinstance(data, dict):
            return _json({"error": "داده نامعتبر است."}, 400)
        _save(webmap, data)
        return _json({"ok": True, "message": "نقشه ذخیره شد."})
    try:
        tables = services.spatial_tables(db)
    except ExplorerError as exc:
        messages.error(request, str(exc))
        tables = []
    from iranmap import basemap

    public_url = request.build_absolute_uri(reverse("maps:map", args=[webmap.slug]))
    return render(request, "maps/composer.html", {
        "db": db, "webmap": webmap, "tables": tables, "palettes": styles.PALETTES,
        "iran_basemap": basemap.available(), "config": map_config(request, webmap, fields=True),
        "public_url": public_url, "embed_url": request.build_absolute_uri(reverse("maps:embed", args=[webmap.slug])),
        "layer_cap": db.plan.map_layers,
    })


@site_user_required
@require_POST
def layer_add(request, pk, map_id):
    db = _db(request, pk)
    webmap = _map(db, map_id)
    schema, table = services.parse_key(request.POST.get("t", ""))
    try:
        layer = services.add_layer(webmap, schema, table)
    except (MapError, ExplorerError) as exc:
        return _json({"error": str(exc)}, 400)
    return _json({"layer": _layer_conf(request, layer, _tiles_path(webmap, layer), f"ml{layer.pk}", fields=True)})


@site_user_required
@require_POST
def layer_remove(request, pk, map_id, layer_id):
    db = _db(request, pk)
    webmap = _map(db, map_id)
    get_object_or_404(MapLayer, pk=layer_id, webmap=webmap).delete()
    return _json({"ok": True})


@site_user_required
@require_POST
def layer_extent(request, pk, map_id, layer_id):
    """محدوده لایه را از داده‌های فعلی جدول دوباره حساب و ذخیره می‌کند (داده بعد از افزودن لایه عوض شده است)."""
    db = _db(request, pk)
    layer = get_object_or_404(MapLayer.objects.select_related("webmap__database"), pk=layer_id,
                              webmap=_map(db, map_id))
    try:
        bbox = engine.extent(layer)
    except (engine.EngineError, ExplorerError) as exc:
        return _json({"error": str(exc)}, 400)
    if bbox != layer.bbox:
        layer.bbox = bbox
        layer.save(update_fields=["bbox", "updated_at"])  # تغییر زمان به‌روزرسانی، کش کاشی را هم تازه می‌کند
    return _json({"bbox": bbox, "empty": not bbox})


@site_user_required
@require_GET
def layer_stats(request, pk, map_id, layer_id):
    db = _db(request, pk)
    layer = get_object_or_404(MapLayer.objects.select_related("webmap__database"), pk=layer_id,
                              webmap=_map(db, map_id))
    mode = request.GET.get("mode", "graduated")
    try:
        stats = engine.field_stats(layer, request.GET.get("field", ""), mode, int(request.GET.get("classes", 5)))
    except (engine.EngineError, ExplorerError, ValueError) as exc:
        return _json({"error": str(exc)}, 400)
    if mode == "categorized":
        stats["colors"] = CATEGORY_COLORS[:len(stats["values"])]
    return _json(stats)


@site_user_required
def qgis_project(request, pk, map_id):
    """دانلود پروژه QGIS: اتصال بدون رمز؛ QGIS بار اول رمز پایگاه داده را می‌پرسد."""
    db = _db(request, pk)
    webmap = _map(db, map_id)
    data = qgis_export.build(webmap, qgis_export.desktop_connection(db))
    resp = HttpResponse(data, content_type="application/x-qgis-project")
    resp["Content-Disposition"] = f'attachment; filename="{webmap.slug}.qgs"'
    return resp


@site_user_required
@require_POST
def publish_ows(request, pk, map_id):
    """همین نقشه به‌صورت WMS/WFS با QGIS Server (یک پروژه از سهمیه WMS/WFS پلن)."""
    from publish import ows, qgis

    db = _db(request, pk)
    webmap = _map(db, map_id)
    if not webmap.layers.exists():
        messages.error(request, "نقشه هنوز لایه‌ای ندارد.")
        return redirect("maps:composer", pk=db.pk, map_id=webmap.pk)
    try:
        project = ows.create_project(db, qgis_export.for_publishing(webmap), f"{webmap.slug}.qgs",
                                     title=webmap.title, is_public=webmap.is_public)
    except (qgis.ProjectError, ows.OwsError) as exc:
        messages.error(request, str(exc))
        return redirect("maps:composer", pk=db.pk, map_id=webmap.pk)
    messages.success(request, f"نقشه «{webmap.title}» به‌صورت WMS/WFS منتشر شد. اگر بعداً نقشه را تغییر دادید، "
                              "دوباره منتشر کنید؛ این پروژه خودبه‌خود عوض نمی‌شود.")
    return redirect("publish:ows_detail", pk=db.pk, project_id=project.pk)


# ---------------------------------------------------------------------- «نمایش با هم» بدون ذخیره
@site_user_required
def quick(request, pk):
    db = _db(request, pk, "viewer")
    if not _live(request, db):
        return redirect("databases:detail", pk=db.pk)
    keys = request.GET.getlist("t")
    try:
        layers = services.quick_layers(db, keys)
    except ExplorerError as exc:
        messages.error(request, str(exc))
        return redirect("databases:explore", pk=db.pk)
    if not layers:
        messages.error(request, "دست‌کم یک جدول مکانی انتخاب کنید.")
        return redirect("databases:explore", pk=db.pk)
    conf_layers = []
    for i, layer in enumerate(layers):
        path = f"/dashboard/{db.pk}/maps/preview/{quote(layer.schema, safe='')}/{quote(layer.table, safe='')}/"
        conf_layers.append(_layer_conf(request, layer, path, f"q{i}"))
    from iranmap import basemap

    config = {**base_config(request), "title": "نمایش با هم", "basemapKind": "iran" if basemap.available() else "osm",
              "layers": conf_layers, "legendTitle": "لایه‌ها"}
    return render(request, "maps/quick.html", {
        "db": db, "layers": layers, "config": config, "keys": [f"{x.schema}.{x.table}" for x in layers],
        "too_many": len(set(keys)) > services.QUICK_MAX,
    })


@site_user_required
@require_GET
def preview_tile(request, pk, schema, table, z, x, y):
    db = _db(request, pk, "viewer")
    if not db.is_live:
        raise Http404
    ck = f"mapprev:{db.pk}:{schema}.{table}"
    info = cache.get(ck)
    if info is None:
        try:
            info = services.find_table(db, schema, table)
        except (MapError, ExplorerError) as exc:
            return _json({"error": str(exc)}, 404)
        cache.set(ck, info, 120)
    layer = MapLayer(webmap=WebMap(database=db), schema=schema, table=table, geom_column=info["geom_column"],
                     srid=info["srid"])
    return _tile_response(layer, z, x, y, public=False)


# ---------------------------------------------------------------------- صفحه عمومی و کاشی‌ها
def _tile_response(layer, z, x, y, public: bool, cache_key: str | None = None):
    if not (z <= 24 and x < 2 ** z and y < 2 ** z):
        return _json({"code": "InvalidParameterValue", "description": "مختصات کاشی نامعتبر است."}, 400)
    data = cache.get(cache_key) if cache_key else None
    if data is None:
        try:
            data = engine.tile(layer, z, x, y)
        except engine.EngineError as exc:
            status = 404 if "پیدا نشد" in str(exc) else 500
            return _json({"code": "TileError", "description": str(exc)}, status)
        except Exception as exc:  # noqa: BLE001  (مثلاً اتصال به سرور پایگاه داده)
            log.exception("map tile failed")
            return _json({"code": "Unavailable", "description": f"ساخت کاشی ممکن نشد: {exc}"}, 503)
        if cache_key:
            cache.set(cache_key, data, TILE_TTL)
    resp = HttpResponse(data, content_type="application/vnd.mapbox-vector-tile")
    resp["Cache-Control"] = f"public, max-age={TILE_TTL}" if public else "private, max-age=0, no-store"
    if public:
        resp["Access-Control-Allow-Origin"] = "*"
    return resp


@require_GET
def tile(request, slug, layer_id, z, x, y):
    layer = MapLayer.objects.select_related("webmap__database__plan", "webmap__database__server").filter(
        pk=layer_id, webmap__slug=slug).first()
    if layer is None:
        return _json({"code": "NotFound", "description": "لایه پیدا نشد."}, 404)
    webmap, db = layer.webmap, layer.webmap.database
    try:
        access.check_database(db)
        # تیم و اعضای کلاسی که نقشه با آن به اشتراک گذاشته شده: نقشه خصوصی را می‌بینند و شمرده نمی‌شوند
        owner = access.is_owner(request, db) or class_member(request, webmap)
        if not (webmap.is_public or owner):
            if access.raw_key(request) == "":
                raise access.Denied(401, "Unauthorized", "این نقشه خصوصی است.")
            if access.key_for(request, db) is None:
                raise access.Denied(403, "Forbidden", "کلید API نامعتبر است.")
        if not owner:
            access.count(db)
    except access.Denied as exc:
        return _json({"code": exc.code, "description": exc.message}, exc.status)
    ck = f"maptile2:{layer.pk}:{int(layer.updated_at.timestamp())}:{z}/{x}/{y}"
    return _tile_response(layer, z, x, y, public=webmap.is_public, cache_key=ck)


def class_member(request, webmap: WebMap) -> bool:
    """دانشجو یا استاد کلاسی که این نقشه با آن به اشتراک گذاشته شده (کلاس فعال)."""
    from django.db.models import Q

    from classroom.models import ClassMap, Classroom

    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return False
    return ClassMap.objects.filter(webmap=webmap, classroom__status=Classroom.Status.ACTIVE).filter(
        Q(classroom__enrollments__student=user) | Q(classroom__teacher=user)).exists()


def _public_map(request, slug) -> WebMap:
    webmap = get_object_or_404(WebMap.objects.select_related("database__plan"), slug=slug)
    db = webmap.database
    if db.status not in UserDatabase.LIVE_STATUSES:
        raise Http404
    if not webmap.is_public and not access.is_owner(request, db) and not class_member(request, webmap):
        raise Http404
    return webmap


def _page(request, slug, template, embed=False, **extra):
    webmap = _public_map(request, slug)
    config = map_config(request, webmap, embed)
    resp = render(request, template, {
        "webmap": webmap, "embed": embed, "config": config,
        "public_url": request.build_absolute_uri(reverse("maps:map", args=[webmap.slug])),
        "n_layers": len(config["layers"]), "n_slides": len(config["slides"]), **extra,
    })
    # نقشه پایه OSM بدون Referer کاشی نمی‌دهد؛ فقط دامنه فرستاده می‌شود
    resp["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp


def public_map(request, slug, embed=False):
    return _page(request, slug, "maps/map.html", embed)


def present(request, slug):
    """حالت ارائه: اسلایدها یکی‌یکی با جابه‌جایی نرم نقشه."""
    return _page(request, slug, "maps/present.html")


def print_map(request, slug):
    """قالب چاپ A4 (چاپ/PDF مرورگر و خروجی PNG)."""
    import jdatetime

    today = jdatetime.date.today().strftime("%Y/%m/%d")
    return _page(request, slug, "maps/print.html", today=today)


def compare(request, slug):
    """مقایسه دو لایه با پرده کشویی."""
    return _page(request, slug, "maps/compare.html")


@xframe_options_exempt
def embed_map(request, slug):
    return public_map(request, slug, embed=True)
