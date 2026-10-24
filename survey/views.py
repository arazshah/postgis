"""برداشت میدانی: فهرست پروژه‌ها، استودیوی تمام‌صفحه، داده، همگام‌سازی، ورود و خروجی فایل و ابزار COGO."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.decorators import site_user_required
from core.models import SiteSettings
from databases import team
from databases.explorer import ExplorerError
from databases.models import UserDatabase
from publish import access
from publish.models import ApiKey
from publish.views import base_config

from . import cogo, crs, data, exports, importers, presets, services, sync
from .gnss import registry
from .models import GnssDriver, SurveyProject

log = logging.getLogger(__name__)
FORMATS = {"csv", "geojson", "dxf", "report"}


def _json(payload, status=200):
    return JsonResponse(payload, status=status, json_dumps_params={"ensure_ascii": False})


def _label(user) -> str:
    return str(getattr(user, "phone", None) or user.get_username() or user.pk)


def _on():
    if not SiteSettings.get().survey_enabled:
        raise Http404


def _db(request, pk, need="viewer") -> UserDatabase:
    _on()
    return team.get_db(request, pk, need)


def _project(db, project_id) -> SurveyProject:
    return get_object_or_404(SurveyProject, pk=project_id, database=db, archived_at__isnull=True)


def _live(request, db) -> bool:
    if not db.is_live:
        messages.error(request, "برداشت میدانی فقط برای پایگاه داده فعال در دسترس است.")
        return False
    return True


@site_user_required
@require_GET
def index(request, pk):
    db = _db(request, pk)
    if not _live(request, db):
        return redirect("databases:detail", pk=db.pk)
    projects = list(services.active_projects(db))
    return render(request, "survey/index.html", {
        "db": db, "projects": projects, "cap": db.plan.survey_projects, "left": services.quota_left(db),
        "points_cap": db.plan.survey_max_points, "presets": crs.PRESETS, "templates": presets.template_choices(),
        "gnss_external": db.plan.gnss_external,
    })


@site_user_required
@require_POST
def create(request, pk):
    db = _db(request, pk, "editor")
    if not _live(request, db):
        return redirect("databases:detail", pk=db.pk)
    try:
        p = services.create_project(db, request.user, request.POST.get("name", ""), request.POST.get("srid"),
                                    request.POST.get("template", "blank"))
    except services.SurveyError as exc:
        messages.error(request, str(exc))
        return redirect("survey:index", pk=db.pk)
    messages.success(request, "پروژه ساخته شد.")
    return redirect("survey:studio", pk=db.pk, project_id=p.pk)


@site_user_required
@require_POST
def archive(request, pk, project_id):
    db = _db(request, pk, "owner")
    services.archive_project(_project(db, project_id))
    messages.success(request, "پروژه بایگانی شد؛ جدول‌های آن در پایگاه داده شما می‌مانند.")
    return redirect("survey:index", pk=db.pk)


@site_user_required
@require_GET
def studio(request, pk, project_id):
    db = _db(request, pk)
    if not _live(request, db):
        return redirect("databases:detail", pk=db.pk)
    p = _project(db, project_id)
    try:
        counts, codes = data.counts(db, p), data.codes(db, p)
    except ExplorerError as exc:
        messages.error(request, str(exc))
        return redirect("survey:index", pk=db.pk)
    if not GnssDriver.objects.exists():
        registry.sync()
    drivers = [{"id": d.driver_id, "name": d.manifest.get("name", d.driver_id), "transport": d.manifest["transport"],
                "capabilities": d.manifest.get("capabilities", []), "serial": d.manifest.get("serial") or {},
                "external": d.manifest["transport"] != ["geolocation"]}
               for d in GnssDriver.objects.filter(enabled=True, level="builtin")
               if db.plan.gnss_external or d.manifest["transport"] == ["geolocation"]]
    urls = {
        "data": f"/dashboard/{db.pk}/survey/{p.pk}/data/", "sync": f"/dashboard/{db.pk}/survey/{p.pk}/sync/",
        "import": f"/dashboard/{db.pk}/survey/{p.pk}/import/", "cogo": f"/dashboard/{db.pk}/survey/{p.pk}/cogo/",
        "export": f"/dashboard/{db.pk}/survey/{p.pk}/export/", "list": f"/dashboard/{db.pk}/survey/",
    }
    conf = {**base_config(request), "srid": p.srid, "project": p.name, "counts": counts, "codes": codes,
            "drivers": drivers, "urls": urls, "canEdit": bool(db.can_edit), "pointsCap": db.plan.survey_max_points,
            "projectId": p.pk, "dbId": db.pk, "basemapKind": "osm", "layers": []}
    return render(request, "survey/studio.html", {"db": db, "project": p, "conf": conf, "formats": sorted(FORMATS)})


@require_GET
def service_worker(request, pk):
    """Service Worker با دامنه‌ی بخش برداشت همین پایگاه داده؛ از مسیر static ارائه نمی‌شود چون دامنه‌اش کوچک‌تر می‌شد."""
    _on()
    path = Path(settings.BASE_DIR) / "static" / "js" / "survey" / "sw.js"
    resp = HttpResponse(path.read_text(encoding="utf-8"), content_type="application/javascript; charset=utf-8")
    resp["Service-Worker-Allowed"] = f"/dashboard/{int(pk)}/survey/"
    resp["Cache-Control"] = "no-cache"
    return resp


@site_user_required
@require_GET
def project_data(request, pk, project_id):
    db = _db(request, pk)
    p = _project(db, project_id)
    try:
        return _json({"counts": data.counts(db, p), **data.collections(db, p)})
    except ExplorerError as exc:
        return _json({"error": str(exc)}, 503)


def _body(request):
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _apply(db, p, items, label):
    try:
        return _json({"results": sync.apply(db, p, items, label)})
    except sync.ItemError as exc:
        return _json({"error": exc.code, "message": str(exc)}, 413 if exc.code == "too_many" else 400)


@site_user_required
@require_POST
def project_sync(request, pk, project_id):
    db = _db(request, pk, "editor")
    if db.status != UserDatabase.Status.ACTIVE:
        return _json({"error": "readonly", "message": "پایگاه داده فقط‌خواندنی است."}, 403)
    body = _body(request)
    if body is None:
        return _json({"error": "invalid", "message": "بدنه JSON معتبر نیست."}, 400)
    return _apply(db, _project(db, project_id), body.get("items"), _label(request.user))


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def api_sync(request, slug):
    """همگام‌سازی با کلید API دارای اجازه نوشتن؛ برای برنامه‌های میدانی و ابزارهای بیرونی."""
    if request.method == "OPTIONS":
        resp = HttpResponse(status=204)
    else:
        resp = _api_sync(request, slug)
    resp["Access-Control-Allow-Origin"] = "*"
    resp["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-API-Key"
    resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


def _api_sync(request, slug):
    if not SiteSettings.get().survey_enabled:
        return _json({"error": "not_found"}, 404)
    raw = access.raw_key(request)
    key = ApiKey.objects.select_related("database__plan", "database__server").filter(
        key_hash=ApiKey.digest(raw), revoked_at__isnull=True).first() if raw.startswith(ApiKey.PREFIX) else None
    if key is None:
        return _json({"error": "unauthorized", "message": "کلید API بفرستید."}, 401)
    if not key.can_write:
        return _json({"error": "forbidden", "message": "این کلید فقط اجازه خواندن دارد."}, 403)
    db = key.database
    if db.status != UserDatabase.Status.ACTIVE:
        return _json({"error": "readonly", "message": "پایگاه داده فقط‌خواندنی است."}, 403)
    p = SurveyProject.objects.filter(database=db, slug=slug, archived_at__isnull=True).first()
    if p is None:
        return _json({"error": "not_found", "message": "پروژه پیدا نشد."}, 404)
    body = _body(request)
    if body is None:
        return _json({"error": "invalid", "message": "بدنه JSON معتبر نیست."}, 400)
    return _apply(db, p, body.get("items"), key.name)


@site_user_required
@require_POST
def project_import(request, pk, project_id):
    db = _db(request, pk, "editor")
    p = _project(db, project_id)
    f = request.FILES.get("file")
    if not f:
        return _json({"error": "invalid", "message": "فایلی انتخاب نشده است."}, 400)
    try:
        raw = f.read(importers.MAX_BYTES + 1)
        if f.name.lower().endswith((".geojson", ".json")):
            items, errors = importers.parse_geojson(raw)
        else:
            items, errors = importers.parse_points(raw, request.POST.get("order", "pen"),
                                                   request.POST.get("crs", "project"), p.srid)
    except importers.ImportError_ as exc:
        return _json({"error": "invalid", "message": str(exc)}, 400)
    results = []
    for i in range(0, len(items), sync.MAX_ITEMS):
        try:
            results += sync.apply(db, p, items[i:i + sync.MAX_ITEMS], _label(request.user))
        except sync.ItemError as exc:
            return _json({"error": exc.code, "message": str(exc)}, 400)
    ok = sum(r["status"] == "ok" for r in results)
    failed = [r for r in results if r["status"] == "error"]
    msg = {r.get("code") for r in failed}
    return _json({"imported": ok, "skipped": len(errors), "failed": len(failed), "errors": errors[:20],
                  "quota": "quota" in msg})


@site_user_required
@require_POST
def project_cogo(request, pk, project_id):
    db = _db(request, pk)
    _project(db, project_id)
    body = _body(request)
    if body is None:
        return _json({"error": "invalid"}, 400)
    try:
        op = body.get("op")
        pt = lambda k: tuple(float(v) for v in body[k])  # noqa: E731
        if op == "inverse":
            out = cogo.inverse(pt("from"), pt("to"))
        elif op == "forward":
            out = {"point": cogo.forward(pt("from"), float(body["azimuth"]), float(body["distance"]))}
        elif op == "area":
            out = cogo.area_perimeter([tuple(float(v) for v in c) for c in body["ring"]])
        elif op == "bearings":
            r = cogo.intersect_bearings(pt("p1"), float(body["az1"]), pt("p2"), float(body["az2"]))
            out = {"point": r}
        elif op == "distances":
            out = {"points": cogo.intersect_distances(pt("p1"), float(body["r1"]), pt("p2"), float(body["r2"]))}
        elif op == "traverse":
            r = cogo.traverse(pt("start"), float(body["azimuth"]), [(float(a), float(d)) for a, d in body["legs"]],
                              pt("close") if body.get("close") else None)
            if r.get("precision") == float("inf"):
                r["precision"] = None
            out = r
        else:
            return _json({"error": "invalid", "message": "عملیات ناشناخته"}, 400)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        return _json({"error": "invalid", "message": f"ورودی نامعتبر: {exc}"}, 400)
    return _json(out)


@site_user_required
@require_GET
def export(request, pk, project_id, fmt):
    db = _db(request, pk)
    p = _project(db, project_id)
    if fmt not in FORMATS:
        raise Http404
    try:
        cols = data.collections(db, p)
        if fmt == "csv":
            resp = HttpResponse(exports.points_csv(cols["points"], p), content_type="text/csv; charset=utf-8")
            ext = "csv"
        elif fmt == "geojson":
            resp = HttpResponse(exports.geojson(cols), content_type="application/geo+json")
            ext = "geojson"
        elif fmt == "dxf":
            resp = HttpResponse(exports.dxf_file(cols, p, data.projected_lines(db, p)), content_type="application/dxf")
            ext = "dxf"
        else:
            return render(request, "survey/report.html", {"db": db, "project": p,
                                                         "table": exports.report_html(cols, p, db.db_name)})
    except ExplorerError as exc:
        messages.error(request, str(exc))
        return redirect("survey:studio", pk=db.pk, project_id=p.pk)
    resp["Content-Disposition"] = f'attachment; filename="survey-{p.slug}.{ext}"'
    return resp
