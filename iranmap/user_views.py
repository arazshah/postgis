"""صفحه «داده آماده ایران» در مرورگر پایگاه داده."""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from accounts.decorators import site_user_required
from databases.explorer import ExplorerError
from databases.views import _explorer_db
from jobs.models import Job

from . import osm, ready
from .models import Area


@site_user_required
@require_http_methods(["GET", "POST"])
def ready_data(request, pk):
    db, ex = _explorer_db(request, pk)
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    error = None
    if request.method == "POST":
        area = Area.objects.filter(pk=request.POST.get("area") or 0).first()
        if area is None:
            error = "یک استان، شهرستان یا شهر را از فهرست انتخاب کنید."
        else:
            try:
                ready.request_import(db, request.user, area, request.POST.getlist("datasets"),
                                     request.POST.get("routing") == "on")
            except ready.ReadyError as exc:
                error = str(exc)
            else:
                messages.success(request, f"درخواست داده {area.label} در صف قرار گرفت؛ چند دقیقه بعد جدول‌ها "
                                          "در فهرست سمت راست دیده می‌شوند.")
                return redirect("iranmap:ready", pk=db.pk)
    try:
        tables = ex.tables()
    except ExplorerError as exc:
        messages.error(request, str(exc))
        tables = []
    recent = Job.objects.filter(database=db, kind=Job.Kind.OSM_IMPORT)[:8]
    return render(request, "iranmap/ready.html", {
        "db": db, "tables": tables, "section": "ready", "error": error, "datasets": osm.DATASETS,
        "source": osm.source_info(), "has_areas": Area.objects.exists(), "recent": recent,
        "active": any(j.active for j in recent), "attribution": osm.ATTRIBUTION,
        "routing_max": ready.ROUTING_MAX_DEG2, "pgrouting": ready.pgrouting_available(db),
    })


@site_user_required
@require_GET
def areas(request):
    q = (request.GET.get("q") or "").strip()
    qs = Area.objects.all()
    if q:
        qs = qs.filter(name__icontains=q) | Area.objects.filter(name_en__icontains=q)
    order = {"province": 0, "county": 1, "city": 2}
    rows = sorted(qs[:200], key=lambda a: (order[a.level], a.name))[:40]
    return JsonResponse({"results": [{"id": a.pk, "label": a.label, "level": a.level,
                                      "routing": ready.routing_allowed(a)} for a in rows]},
                        json_dumps_params={"ensure_ascii": False})
