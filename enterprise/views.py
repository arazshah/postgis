"""صفحه «امکانات سازمانی» هر پایگاه داده، کاشی و نمایشگر رستر."""
from django.contrib import messages
from django.core.cache import cache
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_http_methods

from accounts.decorators import site_user_required
from core.models import SiteSettings
from databases import team
from databases.models import UserDatabase
from databases.views import SESSION_PW_KEY
from iranmap import basemap
from jobs.models import Job
from publish import access

from . import services, tiles
from .models import GeoServerInstance, Raster


@site_user_required
@require_http_methods(["GET", "POST"])
def page(request, pk):
    db = team.get_db(request, pk, "owner")
    here = redirect("enterprise:page", pk=db.pk)
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "geoserver":
                services.request_geoserver(db, request.user)
                messages.success(request, "درخواست GeoServer اختصاصی ثبت شد؛ ساخت و پیکربندی چند دقیقه طول می‌کشد.")
            elif action == "raster_upload":
                f = request.FILES.get("file")
                if not f:
                    raise services.EnterpriseError("فایلی انتخاب نشده است.")
                services.request_raster(db, request.user, f, request.POST.get("title", ""))
                messages.success(request, "رستر بارگذاری شد و در حال تبدیل به COG است.")
            elif action in ("raster_save", "raster_delete"):
                r = get_object_or_404(Raster, pk=request.POST.get("raster"), database=db)
                if action == "raster_delete":
                    services.delete_raster(r)
                    messages.success(request, "رستر حذف شد.")
                else:
                    cm = request.POST.get("colormap")
                    r.colormap = cm if cm in dict(Raster.COLORMAPS) else r.colormap
                    r.rgb = request.POST.get("rgb") == "on" and r.bands >= 3
                    r.is_public = request.POST.get("public") == "on"
                    r.save(update_fields=["colormap", "rgb", "is_public"])
                    messages.success(request, "تنظیم رستر ذخیره شد.")
            elif action == "clone":
                backup = db.jobs.filter(pk=request.POST.get("backup") or 0, kind=Job.Kind.BACKUP).first()
                clone, pw = services.request_clone(db, request.user, backup, request.POST.get("label", ""))
                request.session[SESSION_PW_KEY.format(clone.pk)] = pw
                messages.success(request, "پایگاه داده آزمایشی ساخته شد و داده در حال کپی است.")
                return redirect("databases:detail", pk=clone.pk)
        except services.EnterpriseError as exc:
            messages.error(request, str(exc))
        return here
    gs = GeoServerInstance.objects.filter(database=db).first()
    rasters = db.rasters.all()
    backups = db.jobs.filter(kind=Job.Kind.BACKUP, status=Job.Status.DONE)[:30]
    return render(request, "enterprise/page.html", {
        "db": db, "gs": gs, "rasters": rasters, "backups": backups, "used": services.raster_used(db),
        "raster_cap": db.plan.raster_mb * 1024 * 1024, "colormaps": Raster.COLORMAPS,
        "base": request.build_absolute_uri("/")[:-1],
        "busy": any(r.status == Raster.Status.PROCESSING for r in rasters) or (
            gs and gs.status in (GeoServerInstance.Status.REQUESTED, GeoServerInstance.Status.PROVISIONING)),
    })


def _raster(request, slug, count: bool = True) -> Raster:
    r = Raster.objects.select_related("database__plan").filter(slug=slug, status=Raster.Status.READY).first()
    if r is None:
        raise Http404
    db = r.database
    if db.status not in UserDatabase.LIVE_STATUSES:
        raise Http404
    member = team.level(request.user, db) > 0
    if not (r.is_public or member or access.key_for(request, db)):
        raise Http404
    if count and not member:
        access.count(db)
    return r


def raster_tile(request, slug, z, x, y):
    try:
        r = _raster(request, slug)
    except access.Denied as exc:
        return JsonResponse({"description": exc.message}, status=exc.status, json_dumps_params={"ensure_ascii": False})
    if z > 24 or x >= 2 ** z or y >= 2 ** z:
        return HttpResponse(status=400)
    ck = f"rtile:{r.pk}:{r.colormap}:{r.rgb}:{z}/{x}/{y}"
    data = cache.get(ck)
    if data is None:
        try:
            data = tiles.render(r, z, x, y) or b""
        except tiles.TileError:
            return HttpResponse(status=503)
        cache.set(ck, data, 3600)
    if not data:
        return HttpResponse(status=204)
    resp = HttpResponse(data, content_type="image/png")
    resp["Cache-Control"] = f"{'public' if r.is_public else 'private'}, max-age=3600"
    resp["Access-Control-Allow-Origin"] = "*"
    return resp


def raster_tilejson(request, slug):
    r = _raster(request, slug, count=False)
    key = request.GET.get("key")
    url = request.build_absolute_uri(f"/raster/{r.slug}/") + "{z}/{x}/{y}.png" + (f"?key={key}" if key else "")
    resp = JsonResponse({"tilejson": "3.0.0", "name": r.title, "tiles": [url], "bounds": r.bounds, "minzoom": 0,
                         "maxzoom": 22, "attribution": "postgis.ir"}, json_dumps_params={"ensure_ascii": False})
    resp["Access-Control-Allow-Origin"] = "*"
    return resp


@xframe_options_exempt
def raster_view(request, slug):
    r = _raster(request, slug, count=False)
    cfg = {"tiles": request.build_absolute_uri(f"/raster/{r.slug}/") + "{z}/{x}/{y}.png", "bounds": r.bounds,
           "iranStyle": request.build_absolute_uri("/basemap/style.json") if basemap.available() else "",
           "basemap": SiteSettings.get().map_tile_url,
           "rtlPlugin": request.build_absolute_uri(static("vendor/rtl-text/mapbox-gl-rtl-text.js"))}
    return render(request, "enterprise/raster_view.html", {"r": r, "cfg": cfg})
