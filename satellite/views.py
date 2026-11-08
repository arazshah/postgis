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
from databases import team
from databases.explorer import Explorer, ExplorerError
from iranmap import basemap
from satgate import protocol, spec

from . import client, services
from .models import SatRequest

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
             "bands": len(p.bands)} for p in spec.PRODUCTS.values()]


@site_user_required
def index(request, pk):
    db = team.get_db(request, pk, "viewer")
    reqs = list(SatRequest.objects.filter(database=db).select_related("raster")[:40])
    st = services.status(db)
    cfg = {
        "urls": {n: reverse(f"satellite:{n}", args=[db.pk]) for n in ("cards", "layers", "extent", "quote", "search", "order")},
        "thumb": reverse("satellite:thumb", args=[db.pk, "sentinel-2-l2a", "ITEM"]),
        "csrf": get_token(request), "products": _products(), "status": st,
        "iranStyle": request.build_absolute_uri("/basemap/style.json") if basemap.available() else "",
        "basemap": SiteSettings.get().map_tile_url,
        "rtlPlugin": request.build_absolute_uri(static("vendor/rtl-text/mapbox-gl-rtl-text.js")),
        "plansUrl": reverse("billing:plans"), "canEdit": db.can_edit,
    }
    return render(request, "satellite/index.html", {
        "db": db, "reqs": reqs, "st": st, "cfg": cfg, "configured": client.configured(),
        "active": any(r.active for r in reqs), "base": request.build_absolute_uri("/")[:-1],
        "credit_pct": _pct(st["credits"]["used"], st["credits"]["cap"]), "space_pct": _pct(st["space"]["used"], st["space"]["cap"]),
    })


def _pct(used: float, cap: float) -> int:
    return min(round(used * 100 / cap), 100) if cap else 100


@site_user_required
@require_GET
def cards(request, pk):
    """فهرست کارت‌ها برای تازه‌سازی خودکار هنگام پردازش."""
    db = team.get_db(request, pk, "viewer")
    reqs = list(SatRequest.objects.filter(database=db).select_related("raster")[:40])
    resp = render(request, "satellite/_cards.html", {
        "db": db, "reqs": reqs, "base": request.build_absolute_uri("/")[:-1], "configured": client.configured()})
    resp["X-Sat-Active"] = "1" if any(r.active for r in reqs) else "0"
    return resp


@site_user_required
@require_GET
def layers(request, pk):
    """جدول‌های مکانی پایگاه داده برای انتخاب محدوده."""
    db = team.get_db(request, pk, "viewer")
    if not db.is_live:
        return _json({"items": []})
    try:
        items = [{"name": f"{t.schema}.{t.name}" if t.schema != "public" else t.name, "kind": t.geo_kind,
                  "rows": t.rows_estimate} for t in Explorer(db).tables() if t.geometry]
    except ExplorerError:
        items = []
    return _json({"items": items})


@site_user_required
@require_GET
def extent(request, pk):
    """محدوده‌ی WGS84 یک جدول مکانی (برای «محدوده را از این لایه بگیر»)."""
    from psycopg import sql

    db = team.get_db(request, pk, "viewer")
    name = request.GET.get("t", "")
    schema, _, table = name.rpartition(".")
    try:
        ex = Explorer(db)
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
    except (ExplorerError, IndexError):
        return _json({"ok": False, "error": "جدول مکانی پیدا نشد یا به آن دسترسی ندارید."}, 404)
    except Exception:  # noqa: BLE001 هر خطای SQL (جدول خالی، SRID نادرست)
        return _json({"ok": False, "error": "محدوده‌ی این جدول خوانده نشد؛ جدول خالی یا مختصات آن نامعتبر است."}, 422)
    if not row or row[0] is None:
        return _json({"ok": False, "error": "این جدول عارضه‌ای ندارد."}, 422)
    return _json({"ok": True, "bbox": [round(float(v), 5) for v in row]})


@site_user_required
@require_POST
def quote(request, pk):
    db = team.get_db(request, pk, "viewer")
    data = _body(request)
    try:
        return _json({"ok": True, "quote": services.quote(db, data.get("bbox"), data.get("product"))})
    except services.SatError as exc:
        return _err(exc)


@site_user_required
@require_POST
def search(request, pk):
    db = team.get_db(request, pk, "editor")
    try:
        return _json({"ok": True, "scenes": services.search(db, request.user, _body(request))})
    except services.SatError as exc:
        return _err(exc, 429 if exc.code == "rate" else 400)


@site_user_required
@require_POST
def order(request, pk):
    db = team.get_db(request, pk, "editor")
    try:
        req = services.order(db, request.user, _body(request))
    except services.SatError as exc:
        return _err(exc, 409 if exc.code in ("busy", "credits", "space", "area") else 400)
    return _json({"ok": True, "id": req.pk})


@site_user_required
@require_GET
def thumb(request, pk, collection, item):
    """پیش‌نمایش تصویر از طریق دروازه (مرورگر کاربر در ایران به منبع اصلی دسترسی ندارد)."""
    team.get_db(request, pk, "viewer")
    if collection != spec.COLLECTION_S2 or not NAME_RE.match(item):
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
def delete(request, pk, req):
    db = team.get_db(request, pk, "editor")
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
    ok = protocol.verify(client.config()[1], "POST", request.get_full_path(), request.body,
                         request.headers.get(protocol.H_TIME), request.headers.get(protocol.H_SIG))
    if not ok:
        return HttpResponse(status=401)
    try:
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    if not isinstance(payload, dict):
        return HttpResponse(status=400)
    return HttpResponse(status=204 if services.on_remote(payload) else 404)
