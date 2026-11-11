"""صفحه‌ی «تصویر ماهواره‌ای» هر پایگاه داده، رابط JSON مودال سفارش و هوک دروازه."""
from __future__ import annotations

import json
import re

from django.contrib import messages
from django.core.cache import cache
from django.http import Http404, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import site_user_required
from core.models import SiteSettings
from iranmap import basemap
from kernel import tenantdb, workspace
from kernel.tenantdb import TenantError
from satgate import protocol, spec

from . import client, monitor_service, router, services, zonal_service
from .models import SatAnalysis, SatMonitor, SatRequest

NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,100}$")


def _json(data: dict, status: int = 200) -> JsonResponse:
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def _body(request) -> dict:
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _err(exc: services.SatError, status: int = 400) -> JsonResponse:
    out = {"ok": False, "error": str(exc), "code": exc.code}
    if exc.extra:
        out["quote"] = exc.extra
    return _json(out, 503 if exc.code in ("gateway", "off") else status)


def _products() -> list[dict]:
    return [{"key": p.key, "title": p.title, "hint": p.hint, "needs_scene": p.needs_scene, "res": p.res_m,
             "bands": len(p.bands), "mission": p.mission} for p in spec.all_products()]


@site_user_required
def index(request, pk):
    db = workspace.get(request, pk, "viewer")
    reqs = list(SatRequest.objects.filter(database=db).select_related("raster")[:40])
    st = services.status(db)
    cfg = {
        "urls": {n: reverse(f"satellite:{n}", args=[db.pk]) for n in ("cards", "layers", "extent", "quote", "search", "order", "missions")},
        "an": {"cards": reverse("satellite:an_cards", args=[db.pk]), "layers": reverse("satellite:an_layers", args=[db.pk]),
               "quote": reverse("satellite:an_quote", args=[db.pk]), "mon": reverse("satellite:mon_create", args=[db.pk]), "order": reverse("satellite:an_order", args=[db.pk]),
               "series": reverse("satellite:an_series", args=[db.pk, 0]), "table": reverse("databases:explore_table", args=[db.pk, "public", "TABLE"])},
        "thumb": reverse("satellite:thumb", args=[db.pk, "COLL", "ITEM"]),
        "csrf": get_token(request), "products": _products(), "status": st,
        "iranStyle": request.build_absolute_uri("/basemap/style.json") if basemap.available() else "",
        "basemap": SiteSettings.get().map_tile_url,
        "rtlPlugin": request.build_absolute_uri(static("vendor/rtl-text/mapbox-gl-rtl-text.js")),
        "plansUrl": reverse("billing:plans"), "canEdit": db.can_edit,
    }
    return render(request, "satellite/index.html", {
        "db": db, "reqs": reqs, "st": st, "cfg": cfg, "configured": client.configured(),
        "analyses": (ans := _analyses(db)), "an_active": any(a.active for a in ans), "an_cr": (acr := zonal_service.credits(db)),
        "monitors": list(SatMonitor.objects.filter(database=db)), "mon_lim": monitor_service.limits(db),
        "an_cr_pct": _pct(acr["used"], acr["cap"]), "max_features": zonal_service.zl.MAX_FEATURES,
        "active": any(r.active for r in reqs), "base": request.build_absolute_uri("/")[:-1],
        "credit_pct": _pct(st["credits"]["used"], st["credits"]["cap"]), "space_pct": _pct(st["space"]["used"], st["space"]["cap"]),
    })


def _pct(used: float, cap: float) -> int:
    return min(round(used * 100 / cap), 100) if cap else 100


@site_user_required
@require_GET
def cards(request, pk):
    """فهرست کارت‌ها برای تازه‌سازی خودکار هنگام پردازش."""
    db = workspace.get(request, pk, "viewer")
    reqs = list(SatRequest.objects.filter(database=db).select_related("raster")[:40])
    resp = render(request, "satellite/_cards.html", {
        "db": db, "reqs": reqs, "base": request.build_absolute_uri("/")[:-1], "configured": client.configured()})
    resp["X-Sat-Active"] = "1" if any(r.active for r in reqs) else "0"
    return resp


@site_user_required
@require_GET
def layers(request, pk):
    """جدول‌های مکانی پایگاه داده برای انتخاب محدوده."""
    db = workspace.get(request, pk, "viewer")
    if not db.is_live:
        return _json({"items": []})
    try:
        items = [{"name": f"{t.schema}.{t.name}" if t.schema != "public" else t.name, "kind": t.geo_kind,
                  "rows": t.rows_estimate} for t in tenantdb.catalog(db).tables() if t.geometry]
    except TenantError:
        items = []
    return _json({"items": items})


@site_user_required
@require_GET
def extent(request, pk):
    """محدوده‌ی WGS84 یک جدول مکانی (برای «محدوده را از این لایه بگیر»)."""
    from psycopg import sql

    db = workspace.get(request, pk, "viewer")
    name = request.GET.get("t", "")
    schema, _, table = name.rpartition(".")
    try:
        ex = tenantdb.catalog(db)
        t = ex.find(schema or "public", table)
        g = t.geometry[0]
        srid = g.get("srid") or 0
        if not srid:
            raise services.SatError("سیستم مختصات این جدول مشخص نیست.", "srid")
        col = sql.Identifier(g["column"])
        box = sql.SQL("ST_Extent({}::geometry)").format(col)
        with ex.connect() as conn:
            conn.execute("SET statement_timeout = 15000")
            row = conn.execute(sql.SQL(
                "SELECT ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b) FROM (SELECT ST_Transform(ST_SetSRID({box}, {srid}), 4326) b "
                "FROM {s}.{t}) x").format(box=box, srid=sql.Literal(srid), s=sql.Identifier(t.schema),
                                          t=sql.Identifier(t.name))).fetchone()
    except services.SatError as exc:
        return _err(exc)
    except (TenantError, IndexError):
        return _json({"ok": False, "error": "جدول مکانی پیدا نشد یا به آن دسترسی ندارید."}, 404)
    except Exception:  # noqa: BLE001 هر خطای SQL (جدول خالی، SRID نادرست)
        return _json({"ok": False, "error": "محدوده‌ی این جدول خوانده نشد؛ جدول خالی یا مختصات آن نامعتبر است."}, 422)
    if not row or row[0] is None:
        return _json({"ok": False, "error": "این جدول عارضه‌ای ندارد."}, 422)
    return _json({"ok": True, "bbox": [round(float(v), 5) for v in row]})


@site_user_required
@require_GET
def missions(request, pk):
    """ماهواره‌هایی که الان می‌شود از آن‌ها تصویر گرفت (دروازه وضعیتشان را می‌سنجد)."""
    workspace.get(request, pk, "viewer")
    return _json({"ok": True, "missions": services.missions(force=request.GET.get("refresh") == "1" and request.user.is_staff)})


def _analyses(db):
    return list(SatAnalysis.objects.filter(database=db, monitor__isnull=True)[:30])


@site_user_required
@require_GET
def an_cards(request, pk):
    db = workspace.get(request, pk, "viewer")
    items = _analyses(db)
    resp = render(request, "satellite/_analysis_cards.html", {"db": db, "items": items})
    resp["X-Sat-Active"] = "1" if any(a.active for a in items) else "0"
    return resp


@site_user_required
@require_GET
def an_layers(request, pk):
    """لایه‌های چندضلعی، ستون‌های شناسه و رسترهای آماده‌ی همین پایگاه داده برای فرم تحلیل."""
    from enterprise.models import Raster

    db = workspace.get(request, pk, "viewer")
    try:
        layers = zonal_service.polygon_layers(db) if db.is_live else []
    except TenantError:
        layers = []
    rasters = [{"id": r.pk, "title": r.title, "bands": r.bands, "dtype": r.dtype}
               for r in Raster.objects.filter(database=db, status=Raster.Status.READY)]
    return _json({"ok": True, "layers": layers, "rasters": rasters, "indices": [
        {"key": k, "title": v[2], "hint": v[3]} for k, v in spec.INDICES.items()],
        "credits": zonal_service.credits(db), "local": router.status() if request.user.is_staff else {}})


@site_user_required
@require_POST
def an_quote(request, pk):
    db = workspace.get(request, pk, "viewer")
    try:
        return _json({"ok": True, "quote": zonal_service.quote(db, _body(request))})
    except services.SatError as exc:
        return _err(exc)


@site_user_required
@require_POST
def an_order(request, pk):
    db = workspace.get(request, pk, "editor")
    try:
        an = zonal_service.order(db, request.user, _body(request))
    except services.SatError as exc:
        return _err(exc, 409 if exc.code in ("busy", "credits", "area", "exists") else 400)
    return _json({"ok": True, "id": an.pk})


@site_user_required
@require_GET
def an_series(request, pk, an_id):
    """سری زمانی برای نمودار: از جدول نتیجه‌ی خود کاربر خوانده می‌شود، نه از پایگاه داده‌ی پنل."""
    db = workspace.get(request, pk, "viewer")
    an = get_object_or_404(SatAnalysis, pk=an_id, database=db, status=SatAnalysis.Status.READY)
    try:
        return _json({"ok": True, **zonal_service.series(an, request.GET.get("feature", "")[:80])})
    except (TenantError, Exception):  # noqa: BLE001  جدول حذف شده یا اتصال
        return _json({"ok": False, "error": "جدول نتیجه خوانده نشد؛ شاید حذف یا تغییر نام داده شده است."}, 404)


@site_user_required
@require_POST
def mon_create(request, pk):
    db = workspace.get(request, pk, "editor")
    try:
        m = monitor_service.create(db, request.user, _body(request))
    except services.SatError as exc:
        return _err(exc, 409 if exc.code in ("limit", "exists", "area") else 400)
    return _json({"ok": True, "id": m.pk})


@site_user_required
@require_POST
def mon_action(request, pk, mon_id, action):
    db = workspace.get(request, pk, "editor")
    m = get_object_or_404(SatMonitor, pk=mon_id, database=db)
    if action == "toggle":
        m.enabled = not m.enabled
        m.save(update_fields=["enabled"])
        messages.success(request, "پایش فعال شد." if m.enabled else "پایش متوقف شد.")
    elif action == "run":
        if not m.runs.filter(status__in=[SatAnalysis.Status.PROCESSING, SatAnalysis.Status.DOWNLOADING]).exists():
            monitor_service.start_run(m)
            messages.success(request, "بررسی تازه شروع شد؛ نتیجه در همین کارت و (در صورت افت) در اعلان‌ها می‌آید.")
        else:
            messages.error(request, "یک بررسی همین حالا در جریان است.")
    elif action == "delete":
        m.delete()
        messages.success(request, "پایش حذف شد؛ جدول نتیجه در پایگاه داده‌ی شما می‌ماند.")
    else:
        raise Http404
    return redirect(reverse("satellite:index", args=[db.pk]) + "#analysis")


@site_user_required
@require_POST
def an_delete(request, pk, an_id):
    db = workspace.get(request, pk, "editor")
    an = get_object_or_404(SatAnalysis, pk=an_id, database=db)
    if an.active:
        messages.error(request, "تا پایان محاسبه نمی‌شود این تحلیل را حذف کرد.")
    else:
        an.delete()
        messages.success(request, "تحلیل از فهرست حذف شد؛ جدول نتیجه در پایگاه داده‌ی شما می‌ماند و از «جدول‌ها» پاک می‌شود.")
    return redirect(reverse("satellite:index", args=[db.pk]) + "#analysis")


@site_user_required
@require_POST
def quote(request, pk):
    db = workspace.get(request, pk, "viewer")
    data = _body(request)
    try:
        return _json({"ok": True, "quote": services.quote(db, data.get("bbox"), data.get("product"), data.get("mission"))})
    except services.SatError as exc:
        return _err(exc)


@site_user_required
@require_POST
def search(request, pk):
    db = workspace.get(request, pk, "editor")
    try:
        return _json({"ok": True, "scenes": services.search(db, request.user, _body(request))})
    except services.SatError as exc:
        return _err(exc, 429 if exc.code == "rate" else 400)


@site_user_required
@require_POST
def order(request, pk):
    db = workspace.get(request, pk, "editor")
    try:
        req = services.order(db, request.user, _body(request))
    except services.SatError as exc:
        return _err(exc, 409 if exc.code in ("busy", "credits", "space", "area") else 400)
    return _json({"ok": True, "id": req.pk})


@site_user_required
@require_GET
def thumb(request, pk, collection, item):
    """پیش‌نمایش تصویر از طریق دروازه (مرورگر کاربر در ایران به منبع اصلی دسترسی ندارد)."""
    workspace.get(request, pk, "viewer")
    if collection not in (spec.COLLECTION_S2, spec.COLLECTION_LANDSAT) or not NAME_RE.match(item):
        raise Http404
    key = f"satthumb:{item}"
    data = cache.get(key)
    if data is None:
        try:
            data = client.thumb(collection, item)
        except client.GatewayError:
            raise Http404 from None
        cache.set(key, data, 86400)
    resp = HttpResponse(data, content_type="image/jpeg")
    resp["Cache-Control"] = "private, max-age=86400"
    return resp


@site_user_required
@require_POST
def toggle_public(request, pk, req):
    """عمومی یا خصوصی کردن تصویر: عمومی بدون کلید API در QGIS باز می‌شود."""
    db = workspace.get(request, pk, "editor")
    r = get_object_or_404(SatRequest.objects.select_related("raster"), pk=req, database=db)
    if not r.raster_id:
        raise Http404
    r.raster.is_public = not r.raster.is_public
    r.raster.save(update_fields=["is_public"])
    messages.success(request, "تصویر عمومی شد؛ هر کسی با نشانی آن را می‌بیند." if r.raster.is_public
                     else "تصویر دوباره خصوصی شد؛ فقط با ورود یا کلید API دیده می‌شود.")
    return redirect("satellite:index", pk=db.pk)


@site_user_required
@require_POST
def delete(request, pk, req):
    db = workspace.get(request, pk, "editor")
    r = get_object_or_404(SatRequest, pk=req, database=db)
    if r.active:
        messages.error(request, "تا پایان پردازش نمی‌شود این درخواست را حذف کرد.")
    else:
        services.delete_request(r)
        messages.success(request, "تصویر حذف شد و فضای آن آزاد شد.")
    return redirect("satellite:index", pk=db.pk)


@csrf_exempt
@require_POST
def hook(request):
    """هوک دروازه: «کار آماده شد/ناموفق شد». با امضای HMAC؛ بدون امضای درست هیچ اثری ندارد."""
    chk = protocol.check(client.config()[1], "POST", request.get_full_path(), request.body,
                         request.headers.get(protocol.H_TIME), request.headers.get(protocol.H_SIG),
                         request.headers.get(protocol.H_KID))
    if not chk.ok:
        return _json({"error": client.reject_message({"reason": chk.reason, "skew_s": chk.skew_s}), "reason": chk.reason,
                      "skew_s": chk.skew_s}, 401)
    try:
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    if not isinstance(payload, dict):
        return HttpResponse(status=400)
    return HttpResponse(status=204 if services.on_remote(payload) else 404)
