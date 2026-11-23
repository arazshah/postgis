"""Scoped JSON adapters for the Live workspace."""
import json

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from accounts.decorators import site_user_required
from analysis.models import Question, ToolRun
from databases.models import UserDatabase
from kernel import tenantdb
from maps import services
from maps.models import MapLayer, WebMap
from tools import sdk

from .views import _allowed, _workspace


def error(message):
    return JsonResponse({"error": {"code": "invalid_request", "message": str(message)}}, status=400)


def project_data(project):
    return {"id": project.pk, "title": project.title, "updated_at": project.updated_at,
            "url": reverse("live:studio", args=[project.database_id, project.pk])}


@site_user_required
@require_http_methods(["GET", "POST"])
def projects(request, pk):
    db = _workspace(request, pk, "editor" if request.method == "POST" else "viewer")
    if request.method == "POST":
        if db.status != UserDatabase.Status.ACTIVE:
            raise Http404
        try:
            project = services.create_map(db, request.user, request.POST.get("title", "").strip())
        except (services.MapError, tenantdb.TenantError) as exc:
            return error(exc)
        return JsonResponse({"project": project_data(project)}, status=201)
    return JsonResponse({"projects": [project_data(p) for p in WebMap.objects.filter(database=db)]})


@site_user_required
@require_GET
def source(request, pk, map_id, layer_id):
    db = _workspace(request, pk)
    layer = get_object_or_404(MapLayer, webmap__database=db, webmap_id=map_id, pk=layer_id)
    try:
        catalog = tenantdb.catalog(db)
        table = catalog.find(layer.schema, layer.table)
        fields = catalog.columns(table)
    except tenantdb.TenantError as exc:
        return error(exc)
    return JsonResponse({"source": {"schema": layer.schema, "table": layer.table,
                         "srid": layer.srid, "geometry": layer.geom_type,
                         "extent": layer.bbox, "fields": fields}})


@site_user_required
@require_GET
def history(request, pk):
    db = _workspace(request, pk, plugin="analysis")
    jobs = []
    if _allowed(request, db, "tools"):
        runs = ToolRun.objects.filter(database=db).select_related("job")[:100]
    else:
        runs = ()
    for run in runs:
        info = sdk.get(run.tool)
        if info is None or not _allowed(request, db, info.plugin):
            continue
        job = run.job
        jobs.append({"id": run.pk, "job": job.pk if job else None, "tool": run.tool,
                     "title": info.title, "summary": run.summary, "output": run.output_table,
                     "status": job.status if job else "unavailable", "progress": job.progress if job else 0,
                     "message": job.message if job else "", "created_at": run.created_at,
                     "url": reverse("live:tool_status", args=[pk, job.pk]) if job and db.can_edit else None})
    for question in Question.objects.filter(database=db, user=request.user).select_related("job").order_by("-created_at")[:100]:
        job = question.job
        jobs.append({"id": f"ask-{question.pk}", "title": "پرسش فارسی", "summary": question.text,
                     "output": question.output_table if question.result_kind == Question.Result.LAYER else "",
                     "status": job.status if job else "unavailable", "progress": job.progress if job else 0,
                     "message": job.message if job else "", "created_at": question.created_at})
    jobs.sort(key=lambda item: item["created_at"], reverse=True)
    return JsonResponse({"jobs": jobs[:100]})


@site_user_required
@require_http_methods(["POST"])
def publish_layer(request, pk):
    from publish.models import Service
    from publish.views import _publish_one

    db = _workspace(request, pk, "editor", "publish")
    if db.status != UserDatabase.Status.ACTIVE:
        raise Http404
    try:
        table = tenantdb.catalog(db).find(request.POST.get("schema", "public"), request.POST.get("table", ""))
        service, _ = Service.objects.get_or_create(database=db)
        status, message = _publish_one(db, service, table, request.POST.get("public") == "on")
    except tenantdb.TenantError as exc:
        return error(exc)
    return JsonResponse({"status": status, "message": message}, status=200 if status in ("ok", "exists") else 400)


@site_user_required
@require_http_methods(["GET", "POST"])
def import_flow(request, pk, job_id=None):
    from dbimport import views as imports
    _workspace(request, pk, "editor", "dbimport")
    request.live_import_flow = True
    response = imports.import_start(request, pk) if job_id is None else imports.import_review(request, pk, job_id)
    if response.status_code in (301, 302, 303):
        from django.urls import resolve
        match = resolve(response["Location"])
        if match.view_name == "databases:import_review":
            return JsonResponse({"next": reverse("live:workflow_import_review", kwargs=match.kwargs)})
        if match.view_name == "databases:import":
            return JsonResponse({"next": reverse("live:workflow_import", kwargs={"pk": pk})})
        return error("ادامه ورود داده ممکن نیست؛ وضعیت پایگاه و مجوز را بررسی کنید.")
    if response.status_code == 200:
        payload = json.loads(response.content)
        if payload.get("catalogChanged"):
            try:
                payload["tables"] = services.spatial_tables(_workspace(request, pk, "editor", "dbimport"))
            except tenantdb.TenantError:
                payload["catalogChanged"] = False
        return JsonResponse(payload)
    return response


@site_user_required
@require_http_methods(["GET", "POST"])
def geoai(request, pk):
    from django.template.loader import render_to_string

    from analysis import ask

    db = _workspace(request, pk, "editor", "analysis")
    if request.method == "POST":
        try:
            ask.request(db, request.user, request.POST.get("question", ""),
                        request.POST.getlist("layers"), request.POST.get("output", ""),
                        share_values=request.POST.get("share_values") == "on")
        except (ask.AskError, tenantdb.TenantError) as exc:
            return error(exc)
        return JsonResponse({"message": "پرسش در صف قرار گرفت.", "jobsChanged": True})
    try:
        tables = [table for table in tenantdb.catalog(db).tables() if table.geometry]
    except tenantdb.TenantError as exc:
        return error(exc)
    html = render_to_string("live/workflows/geoai.html", {"tables": tables}, request=request)
    return JsonResponse({"html": html})


@site_user_required
@require_http_methods(["GET", "POST"])
def rest_flow(request, pk):
    from restapi.manage import manage

    _workspace(request, pk, "editor", "restapi")
    request.live_rest_flow = True
    response = manage(request, pk)
    if response.status_code == 302:
        return JsonResponse({"next": reverse("live:workflow_rest", args=[pk])})
    return response


@site_user_required
@require_http_methods(["GET", "POST"])
def ows_flow(request, pk):
    from django.template.loader import render_to_string

    from publish import ows, qgis
    from publish.models import OwsProject
    from publish.ows_views import upload_project

    db = _workspace(request, pk, "editor", "publish")
    if request.method == "POST":
        try:
            project = upload_project(db, request.FILES.get("file"), request.POST)
        except (qgis.ProjectError, ows.OwsError) as exc:
            return error(exc)
        message = f"پروژه «{project.title}» منتشر شد."
    else:
        message = ""
    projects = OwsProject.objects.filter(service__database=db)
    html = render_to_string("live/workflows/ows.html", {"projects": projects, "notice": message}, request=request)
    return JsonResponse({"html": html})


@site_user_required
@require_http_methods(["GET", "POST"])
def survey_flow(request, pk):
    from django.template.loader import render_to_string

    from survey import presets, services
    from survey.views import _on

    _on()
    db = _workspace(request, pk, "editor" if request.method == "POST" else "viewer", "survey")
    notice = ""
    if request.method == "POST":
        try:
            project = services.create_project(db, request.user, request.POST.get("name", ""),
                                              request.POST.get("srid"), request.POST.get("template", "blank"))
        except services.SurveyError as exc:
            return error(exc)
        notice = f"پروژهٔ «{project.name}» ساخته شد."
    html = render_to_string("live/workflows/survey.html", {
        "projects": services.active_projects(db), "notice": notice,
        "can_create": db.can_edit and db.status == UserDatabase.Status.ACTIVE,
        "templates": presets.template_choices(),
    }, request=request)
    return JsonResponse({"html": html})


@site_user_required
@require_http_methods(["GET", "POST"])
def satellite_flow(request, pk):
    from django.template.loader import render_to_string

    from satellite import services

    db = _workspace(request, pk, "editor", "satellite")
    coordinates = ("west", "south", "east", "north")
    context = {"coordinates": coordinates}
    if request.method == "POST":
        try:
            bbox = [float(request.POST.get(key, "")) for key in coordinates]
        except ValueError:
            return error("مختصات محدوده را بررسی کنید.")
        data = {"bbox": bbox, "product": "true_color", "start": request.POST.get("start"),
                "end": request.POST.get("end"), "scene": request.POST.get("scene"),
                "source": request.POST.get("source")}
        try:
            if request.POST.get("action") == "order":
                order = services.order(db, request.user, data)
                return JsonResponse({"message": f"درخواست تصویر شمارهٔ {order.pk} ثبت شد."})
            scenes = services.search(db, request.user, data)
            quote = services.quote(db, bbox, data["product"])
            context.update(scenes=scenes, bbox=bbox, searched=True, quote=quote)
        except services.SatError as exc:
            return error(exc)
    html = render_to_string("live/workflows/satellite.html", context, request=request)
    return JsonResponse({"html": html})


@site_user_required
@require_http_methods(["GET", "POST"])
def plugins_flow(request, pk):
    from django.template.loader import render_to_string

    from billing import services as billing
    from core.models import SiteSettings

    db = _workspace(request, pk)
    catalog = billing.market_catalog(request.user)["items"]
    notice = ""
    invoice = None
    if request.method == "POST":
        addon_id = request.POST.get("addon")
        addon = next((item["addon"] for item in catalog if item.get("addon")
                      and str(item["addon"].pk) == addon_id), None)
        if addon is None:
            raise Http404
        try:
            action = request.POST.get("action")
            if action == "trial":
                billing.start_trial(request.user, addon, db)
                notice = "دورهٔ آزمایشی فعال شد."
            elif action == "invoice":
                invoice = billing.create_addon_invoice(request.user, addon, db)
            else:
                return error("عملیات افزونه معتبر نیست.")
        except billing.BillingError as exc:
            return error(exc)
    items = [{**item, "available": _allowed(request, db, item["id"])} for item in catalog]
    conf = SiteSettings.get()
    context = {"items": items, "notice": notice, "invoice": invoice,
               "can_buy": conf.pay_enabled and billing.methods_available(conf),
               "owns_workspace": db.owner_id == request.user.pk}
    html = render_to_string("live/workflows/plugins.html", context, request=request)
    return JsonResponse({"html": html})


@site_user_required
@require_http_methods(["GET", "POST"])
def survey_surface(request, pk, project_id):
    from django.template.loader import render_to_string

    from survey import data, surface
    from survey.views import _on, _project, _surface

    _on()
    db = _workspace(request, pk, plugin="survey")
    project = _project(db, project_id)
    context = {"project": project, "can_save": db.can_edit and db.status == UserDatabase.Status.ACTIVE}
    if request.method == "POST":
        save = request.POST.get("save") == "on"
        if save and not context["can_save"]:
            raise Http404
        try:
            _, lines, stats = _surface(db, project, request.POST)
            context["stats"] = stats
            if save:
                data.save_contours(db, project, lines)
                context["notice"] = "منحنی‌های تراز در پایگاه ذخیره شدند."
        except (surface.SurfaceError, tenantdb.TenantError) as exc:
            return error(exc)
    html = render_to_string("live/workflows/survey_surface.html", context, request=request)
    return JsonResponse({"html": html})
