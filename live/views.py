from dataclasses import asdict

from django.conf import settings
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.decorators import site_user_required
from analysis.models import ToolRun
from databases.models import UserDatabase
from kernel import entitlements, tenantdb, workspace
from maps import services as maps
from maps.models import WebMap
from maps.views import map_config
from tools import sdk
from tools.api import enqueue

from .sso import main_url


def tool_metadata(tool):
    return {"key": tool.key, "title": tool.title, "category": tool.category,
            "description": tool.description, "icon": tool.icon,
            "params": [asdict(param) for param in tool.params]}


def _navigation():
    return {"main_dashboard": main_url() if settings.LIVE_SSO_ENABLED else reverse("databases:dashboard"),
            "live_sso": settings.LIVE_SSO_ENABLED}


def _allowed(request, db, plugin):
    return entitlements.allowed(plugin, user=request.user, ws=db)


def _workspace(request, pk, need="viewer", plugin="maps"):
    db = workspace.get(request, pk, need)
    if not db.is_live or not all(_allowed(request, db, p) for p in ("live", plugin)):
        raise Http404
    return db


@site_user_required
@require_GET
def index(request):
    owned = request.user.databases.exclude(status=UserDatabase.Status.DELETED)
    dbs = {db.pk: db for db in [*owned, *workspace.shared_with(request.user)]}
    return render(request, "live/index.html", {**_navigation(), "databases": [db for db in dbs.values()
                   if db.is_live and _allowed(request, db, "live") and _allowed(request, db, "maps")]})


@site_user_required
@require_http_methods(["GET", "POST"])
def projects(request, pk):
    db = _workspace(request, pk)
    if request.method == "POST":
        db = _workspace(request, pk, "editor")
        if db.status != UserDatabase.Status.ACTIVE:
            raise Http404
        try:
            project = maps.create_map(db, request.user, request.POST.get("title", "").strip())
        except (maps.MapError, tenantdb.TenantError) as exc:
            messages.error(request, str(exc))
        else:
            return redirect("live:studio", pk=pk, map_id=project.pk)
    return render(request, "live/index.html", {**_navigation(), "db": db, "projects": WebMap.objects.filter(database=db)})


@site_user_required
@require_GET
def studio(request, pk, map_id):
    db = _workspace(request, pk)
    project = get_object_or_404(WebMap, database=db, pk=map_id)
    editable = db.can_edit and db.status == UserDatabase.Status.ACTIVE
    try:
        tables = maps.spatial_tables(db)
    except tenantdb.TenantError:
        tables = []
        messages.error(request, "کاتالوگ داده در دسترس نیست.")
    tools = []
    if editable and _allowed(request, db, "tools") and _allowed(request, db, "analysis"):
        tools = [tool_metadata(t) for t in sdk.all_tools()
                 if _allowed(request, db, t.plugin)]
    links = {"workflow_import": reverse("live:workflow_import", args=[pk]),
             "publish_api": reverse("live:api_publish", args=[pk]),
             "history": reverse("live:api_history", args=[pk]),
             "projects": reverse("live:api_projects", args=[pk]),
             "source": reverse("live:api_source", args=[pk, map_id, 0])}
    for key, plugin, route in (
        ("import", "dbimport", "databases:import"), ("data", "dbtables", "databases:explore"),
        ("ai", "analysis", "analysis:page"), ("satellite", "satellite", "satellite:index"),
        ("publish", "publish", "publish:manage"), ("ows", "publish", "publish:ows"),
        ("rest", "restapi", "restapi:manage"), ("survey", "survey", "survey:index"),
    ):
        if _allowed(request, db, plugin):
            links[key] = reverse(route, args=[pk])
    links["workflow_plugins"] = reverse("live:workflow_plugins", args=[pk])
    if editable and "satellite" in links:
        links["workflow_satellite"] = reverse("live:workflow_satellite", args=[pk])
    if "survey" in links:
        links["workflow_survey"] = reverse("live:workflow_survey", args=[pk])
    if editable and "ows" in links:
        links["workflow_ows"] = reverse("live:workflow_ows", args=[pk])
    if editable and "rest" in links:
        links["workflow_rest"] = reverse("live:workflow_rest", args=[pk])
    if editable and "ai" in links:
        links["workflow_ai"] = reverse("live:workflow_ai", args=[pk])
    if editable:
        links.update(save=reverse("maps:composer", args=[pk, map_id]),
                     add=reverse("maps:layer_add", args=[pk, map_id]),
                     remove=reverse("maps:layer_remove", args=[pk, map_id, 0]),
                     qgis=reverse("maps:qgis", args=[pk, map_id]))
    cfg = map_config(request, project)
    saved_layers = {saved.pk: saved for saved in project.layers.all()}
    for layer in cfg["layers"]:
        saved = saved_layers.get(layer["id"])
        if saved:
            layer.update(schema=saved.schema, table_name=saved.table)
    return render(request, "live/studio.html", {**_navigation(), "db": db, "project": project, "editable": editable,
                  "config": cfg, "tables": tables, "tools": tools, "links": links})


@site_user_required
@require_GET
def table(request, pk):
    db = _workspace(request, pk, plugin="dbtables")
    try:
        catalog = tenantdb.catalog(db)
        t = next((t for t in catalog.tables() if t.schema == request.GET.get("schema")
                  and t.name == request.GET.get("table")), None)
        if t is None:
            raise Http404
        page = max(1, min(10000, int(request.GET.get("page", 1))))
        can_edit = db.can_edit and db.status == UserDatabase.Status.ACTIVE
        data = catalog.rows(t, page=page, with_keys=can_edit)
        if can_edit:
            from dbtables.views import _edit_config

            try:
                data["edit"] = _edit_config(request, db, catalog, t)
            except tenantdb.TenantError:
                data["edit"] = {"capable": False}
        return JsonResponse(data)
    except (ValueError, tenantdb.TenantError):
        return JsonResponse({"error": "خواندن جدول ممکن نشد."}, status=400)


@site_user_required
@require_POST
def tool(request, pk):
    db = _workspace(request, pk, "editor", "tools")
    info = sdk.get(request.POST.get("key", ""))
    if info is None or not _allowed(request, db, info.plugin) or not _allowed(request, db, "analysis"):
        raise Http404
    try:
        job = enqueue(db, request.user, info.key, request.POST)
    except (sdk.ToolError, tenantdb.TenantError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"job": job.pk, "status": job.status,
                         "url": reverse("live:tool_status", args=[pk, job.pk])})


@site_user_required
@require_GET
def tool_status(request, pk, job_id):
    db = _workspace(request, pk, "editor", "tools")
    run = get_object_or_404(ToolRun.objects.select_related("job"), database=db, job_id=job_id)
    info = sdk.get(run.tool)
    if info is None or not _allowed(request, db, info.plugin) or not _allowed(request, db, "analysis"):
        raise Http404
    return JsonResponse({"status": run.job.status, "progress": run.job.progress,
                         "output": run.output_table, "message": run.job.message})
