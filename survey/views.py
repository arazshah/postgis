"""برداشت میدانی: فهرست پروژه‌ها، استودیوی تمام‌صفحه، داده، همگام‌سازی، ورود و خروجی فایل و ابزار COGO."""
from __future__ import annotations

import json
import logging
import math
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.decorators import site_user_required
from core.models import SiteSettings
from databases import team
from databases.crypto import decrypt, encrypt
from databases.explorer import ExplorerError
from databases.models import UserDatabase
from iranmap import basemap
from publish import access
from publish.models import ApiKey
from publish.views import base_config

from . import cogo, crs, data, exports, importers, ntrip, presets, services, surface, sync
from .gnss import registry
from .models import GnssDriver, NtripProfile, NtripSession, SurveyProject

log = logging.getLogger(__name__)
FORMATS = {"csv", "geojson", "dxf", "report", "contours"}


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
        "points_cap": db.plan.survey_max_points, "presets": crs.preset_tiles(), "templates": presets.template_choices(),
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
        "ntrip": f"/dashboard/{db.pk}/survey/{p.pk}/ntrip/",
        "surface": f"/dashboard/{db.pk}/survey/{p.pk}/surface/", "sessions": f"/dashboard/{db.pk}/survey/{p.pk}/surface/sessions/",
    }
    conf = {**base_config(request), "srid": p.srid, "project": p.name, "counts": counts, "codes": codes,
            "drivers": drivers, "urls": urls, "canEdit": bool(db.can_edit), "pointsCap": db.plan.survey_max_points,
            "projectId": p.pk, "dbId": db.pk, "layers": [],
            "sampleNmea": static("survey/sample.nmea"), "ntripOn": bool(db.plan.gnss_external and db.can_edit)}
    # نقشه برداری خود سایت (هم‌مبدأ ⇒ قابل ذخیره برای آفلاین)؛ بدون آن به کاشی تصویری OSM برمی‌گردد
    conf["basemapKind"] = "iran" if conf.get("iranStyle") else "osm"
    conf["baseMaxZoom"] = basemap.maxzoom() if conf.get("iranStyle") else 0
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
        if fmt == "contours":
            _tris, lines, _st = _surface(db, p, request.GET)
            resp = HttpResponse(exports.contours_dxf(lines), content_type="application/dxf")
            resp["Content-Disposition"] = f'attachment; filename="contours-{p.slug}.dxf"'
            return resp
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
    except surface.SurfaceError as exc:
        messages.error(request, str(exc))
        return redirect("survey:studio", pk=db.pk, project_id=p.pk)
    resp["Content-Disposition"] = f'attachment; filename="survey-{p.slug}.{ext}"'
    return resp


# ----------------------------------------------------------------------------- تصحیحات NTRIP (RTK)
def _ntrip_db(request, pk):
    db = _db(request, pk, "editor")
    if not db.plan.gnss_external:
        raise Http404
    return db


def _profile_json(pr):
    return {"id": pr.pk, "name": pr.name, "host": pr.host, "port": pr.port, "mountpoint": pr.mountpoint,
            "username": pr.username, "tls": pr.tls, "send_gga": pr.send_gga, "has_password": bool(pr.password_enc)}


@site_user_required
@require_http_methods(["GET", "POST"])
def ntrip_profiles(request, pk, project_id):
    db = _ntrip_db(request, pk)
    p = _project(db, project_id)
    if request.method == "GET":
        return _json({"profiles": [_profile_json(x) for x in p.ntrip_profiles.all()]})
    b = _body(request)
    if b is None:
        return _json({"error": "bad_json", "message": "درخواست نامعتبر است."}, 400)
    if p.ntrip_profiles.count() >= 10 and not b.get("id"):
        return _json({"error": "limit", "message": "حداکثر ۱۰ اتصال برای هر پروژه."}, 400)
    pr = p.ntrip_profiles.filter(pk=b.get("id")).first() if b.get("id") else NtripProfile(project=p, created_by=request.user)
    if b.get("id") and pr is None:
        raise Http404
    if b.get("delete"):
        pr.delete()
        return _json({"ok": True})
    try:
        port = int(b.get("port") or 2101)
        host, mount = str(b.get("host", "")).strip(), str(b.get("mountpoint", "")).strip()
        user, pwd = str(b.get("username", "")), b.get("password")
        ntrip.validate_profile(host, port, mount, user, pwd if isinstance(pwd, str) else "")
        ntrip.resolve_public(host, port)
    except (ValueError, ntrip.NtripError) as exc:
        return _json({"error": "invalid", "message": str(exc) if isinstance(exc, ntrip.NtripError) else "درگاه نامعتبر است."}, 400)
    pr.name = (str(b.get("name") or host))[:80]
    pr.host, pr.port, pr.mountpoint, pr.username = host, port, mount, user
    pr.tls, pr.send_gga = bool(b.get("tls")), b.get("send_gga", True) is not False
    if isinstance(pwd, str) and pwd != "":  # خالی = بدون تغییر
        pr.password_enc = encrypt(pwd)
    pr.save()
    return _json({"profile": _profile_json(pr)})


@site_user_required
@require_POST
def ntrip_sourcetable(request, pk, project_id):
    db = _ntrip_db(request, pk)
    p = _project(db, project_id)
    b = _body(request)
    if b is None:
        return _json({"error": "bad_json", "message": "درخواست نامعتبر است."}, 400)
    pr = p.ntrip_profiles.filter(pk=b.get("id")).first() if b.get("id") else None
    try:
        # مقدارهای فرم بر ذخیره‌شده می‌چربند؛ گذرواژه خالی یعنی همان گذرواژه ذخیره‌شده
        host = str(b.get("host") or (pr.host if pr else "")).strip()
        port = int(b.get("port") or (pr.port if pr else 2101))
        tls = bool(b["tls"]) if "tls" in b else bool(pr and pr.tls)
        user = str(b["username"]) if "username" in b else (pr.username if pr else "")
        same = bool(pr and pr.host == host and pr.port == port)  # گذرواژه ذخیره‌شده هرگز به میزبان دیگر نمی‌رود
        pwd = str(b.get("password") or "") or (decrypt(pr.password_enc) if same else "")
        rows = ntrip.fetch_sourcetable(host, port, tls, user, pwd)
    except (ValueError, ntrip.NtripError) as exc:
        return _json({"error": "ntrip", "message": str(exc) if isinstance(exc, ntrip.NtripError) else "درگاه نامعتبر است."}, 502)
    return _json({"mountpoints": rows})


@site_user_required
@require_POST
def ntrip_start(request, pk, project_id):
    db = _ntrip_db(request, pk)
    p = _project(db, project_id)
    b = _body(request)
    pr = p.ntrip_profiles.filter(pk=(b or {}).get("id")).first()
    if pr is None:
        raise Http404
    gga = str((b or {}).get("gga", ""))[:120]
    NtripSession.objects.filter(user=request.user, closed=False).update(closed=True)  # یک نشست فعال برای هر کاربر
    sess = NtripSession.objects.create(id=uuid.uuid4(), profile=pr, user=request.user,
                                       gga=gga if ntrip.GGA_RE.match(gga) else "")
    return _json({"session": str(sess.id), "stream": f"{request.path.rsplit('start/', 1)[0]}stream/{sess.id}/"})


@site_user_required
@require_GET
def ntrip_stream(request, pk, project_id, session):
    db = _ntrip_db(request, pk)
    _project(db, project_id)
    sess = get_object_or_404(NtripSession.objects.select_related("profile"), pk=session, user=request.user,
                             closed=False, profile__project_id=project_id)
    try:
        relay = ntrip.open_relay(sess, sess.profile, decrypt(sess.profile.password_enc))
    except ntrip.NtripError as exc:
        NtripSession.objects.filter(pk=sess.pk).update(closed=True)
        return _json({"error": "ntrip", "message": str(exc)}, 503 if "ظرفیت" in str(exc) else 502)
    resp = StreamingHttpResponse(relay, content_type="application/octet-stream")
    resp["Cache-Control"] = "no-store"
    resp["X-Accel-Buffering"] = "no"
    return resp


@site_user_required
@require_POST
def ntrip_gga(request, pk, project_id, session):
    """ضربان و موقعیت تازه: GGA فقط برای کستر شبکه‌ای (VRS) لازم است؛ بدون آن هم باید ضربان رسید."""
    db = _ntrip_db(request, pk)
    _project(db, project_id)
    sess = get_object_or_404(NtripSession, pk=session, user=request.user, closed=False, profile__project_id=project_id)
    b = _body(request) or {}
    gga = str(b.get("gga", ""))[:120]
    upd = {"last_seen": timezone.now()}
    if ntrip.GGA_RE.match(gga):
        upd.update(gga=gga, gga_seq=sess.gga_seq + 1)
    NtripSession.objects.filter(pk=sess.pk).update(**upd)
    return _json({"ok": True})


@site_user_required
@require_POST
def ntrip_stop(request, pk, project_id, session):
    db = _ntrip_db(request, pk)
    _project(db, project_id)
    NtripSession.objects.filter(pk=session, user=request.user).update(closed=True)
    return _json({"ok": True})


# ----------------------------------------------------------------------------- سطح و منحنی میزان
def _num(params, key, default=None, lo=None):
    v = params.get(key)
    if v in (None, ""):
        return default
    try:
        x = float(v)
    except (TypeError, ValueError) as exc:
        raise surface.SurfaceError(f"مقدار «{key}» عدد نیست.") from exc
    if not math.isfinite(x) or (lo is not None and x < lo):
        raise surface.SurfaceError(f"مقدار «{key}» معتبر نیست.")
    return x


def _session_id(v):
    if not v:
        return None
    try:
        return str(uuid.UUID(str(v)))
    except ValueError as exc:
        raise surface.SurfaceError("شناسه نشست نامعتبر است.") from exc


def _surface(db, p, params):
    """مثلث‌بندی، منحنی‌ها و آمار؛ params می‌تواند QueryDict یا dict باشد."""
    field = params.get("field") or "h_ortho"
    new_session, old_session = _session_id(params.get("session")), _session_id(params.get("compare"))
    tris, n = data.tin(db, p, field, new_session)
    max_edge = _num(params, "max_edge", None, lo=0)
    tris = surface.filter_long_edges(tris, max_edge)
    if not tris:
        raise surface.SurfaceError("با این حداکثر طول لبه هیچ مثلثی نمانده است؛ عدد را بزرگ‌تر کنید.")
    st = surface.stats(tris)
    st["points"] = n
    interval = _num(params, "interval", None, lo=0) or surface.auto_interval(st["z_min"], st["z_max"])
    st["interval"] = interval
    every = int(_num(params, "index_every", 5, lo=0) or 0)
    lines = surface.contours(tris, interval, base=_num(params, "base", 0.0) or 0.0, index_every=every)
    if old_session:
        old, _n = data.tin(db, p, field, old_session)
        st["between"] = surface.volume_between(tris, surface.filter_long_edges(old, max_edge), _num(params, "cell", None, lo=0))
    ref = _num(params, "ref")
    if ref is not None:
        st["volume"] = surface.volume(tris, ref)
        st["ref"] = ref
    return tris, lines, st


@site_user_required
@require_POST
def project_surface(request, pk, project_id):
    db = _db(request, pk)
    p = _project(db, project_id)
    b = _body(request)
    if b is None:
        return _json({"error": "invalid", "message": "درخواست نامعتبر است."}, 400)
    try:
        _tris, lines, st = _surface(db, p, b)
        out = {"stats": st, "contours": data.contours_wgs84(db, p, lines)}
        if b.get("save"):
            if not db.can_edit:
                return _json({"error": "forbidden", "message": "ذخیره در پایگاه داده برای ویرایشگر و مالک است."}, 403)
            out["saved"] = data.save_contours(db, p, lines)
            out["table"] = f"{p.slug}.contours"
    except surface.SurfaceError as exc:
        return _json({"error": "surface", "message": str(exc)}, 400)
    except ExplorerError as exc:
        return _json({"error": "unavailable", "message": str(exc)}, 503)
    return _json(out)


@site_user_required
@require_GET
def surface_sessions(request, pk, project_id):
    db = _db(request, pk)
    p = _project(db, project_id)
    try:
        return _json({"sessions": data.sessions(db, p)})
    except ExplorerError as exc:
        return _json({"error": "unavailable", "message": str(exc)}, 503)
