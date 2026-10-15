"""صفحه‌های «WMS/WFS با QGIS Server» در داشبورد هر پایگاه داده."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import site_user_required

from . import ows, qgis
from .models import OwsProject, Service
from .views import _db

ALLOWED_EXT = (".qgs", ".qgz")


def _project(db, project_id) -> OwsProject:
    return get_object_or_404(OwsProject.objects.select_related("service__database__server"), pk=project_id,
                             service__database=db)


@site_user_required
def index(request, pk):
    db = _db(request, pk)
    if not db.is_live:
        messages.error(request, "انتشار فقط برای پایگاه داده فعال در دسترس است.")
        return redirect("databases:detail", pk=db.pk)
    if request.method == "POST":
        f = request.FILES.get("file")
        if not f or not f.name.lower().endswith(ALLOWED_EXT):
            messages.error(request, "فایل پروژه QGIS با پسوند .qgz یا .qgs انتخاب کنید.")
        elif f.size > qgis.MAX_PROJECT_BYTES:
            messages.error(request, "حجم پروژه بیشتر از ۲۰ مگابایت است.")
        else:
            try:
                p = ows.create_project(db, f.read(), f.name, title=request.POST.get("title", ""),
                                       is_public=request.POST.get("public") == "on")
            except (qgis.ProjectError, ows.OwsError) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"پروژه «{p.title}» منتشر شد.")
                return redirect("publish:ows_detail", pk=db.pk, project_id=p.pk)
        return redirect("publish:ows", pk=db.pk)
    service = Service.objects.filter(database=db).first()
    projects = list(service.ows_projects.all()) if service else []
    linked = {(p.source_schema, p.source_name) for p in projects if p.source == OwsProject.Source.DATABASE}
    saved = [s for s in ows.saved_projects(db) if (s["schema"], s["name"]) not in linked]
    return render(request, "publish/ows_index.html", {
        "db": db, "projects": projects, "saved": saved, "limit": db.plan.ows_projects,
        "base": request.build_absolute_uri("/")[:-1], "section": "publish",
    })


@site_user_required
@require_POST
def import_saved(request, pk):
    db = _db(request, pk)
    schema, name = request.POST.get("schema", ""), request.POST.get("name", "")
    try:
        data = ows.read_saved(db, schema, name)
        p = ows.create_project(db, data, name + ".qgz", title=name, source=OwsProject.Source.DATABASE,
                               schema=schema, is_public=request.POST.get("public") == "on")
        p.source_name = name
        p.save(update_fields=["source_name"])
    except (qgis.ProjectError, ows.OwsError) as exc:
        messages.error(request, str(exc))
        return redirect("publish:ows", pk=db.pk)
    except Exception as exc:  # noqa: BLE001  اتصال به پایگاه داده
        messages.error(request, f"خواندن پروژه از پایگاه داده ممکن نشد: {exc}")
        return redirect("publish:ows", pk=db.pk)
    messages.success(request, f"پروژه «{p.title}» از پایگاه داده منتشر شد.")
    return redirect("publish:ows_detail", pk=db.pk, project_id=p.pk)


@site_user_required
def detail(request, pk, project_id):
    db = _db(request, pk)
    project = _project(db, project_id)
    if request.method == "POST":
        try:
            ows.update_settings(project, title=request.POST.get("title", ""),
                                is_public=request.POST.get("public") == "on", wfs=request.POST.get("wfs") == "on")
            messages.success(request, "تنظیمات ذخیره شد.")
        except (qgis.ProjectError, ows.OwsError) as exc:
            messages.error(request, str(exc))
        return redirect("publish:ows_detail", pk=db.pk, project_id=project.pk)
    url = ows.public_url(project).replace(ows.settings.SITE_URL.rstrip("/"), request.build_absolute_uri("/")[:-1])
    return render(request, "publish/ows_detail.html", {
        "db": db, "p": project, "url": url, "root": qgis.ROOT_NAME,
        "vector_layers": [x for x in project.layers if x["kind"] == "vector"],
        "preview": {"url": url, "root": qgis.ROOT_NAME, "bbox": project.bbox},
        "section": "publish",
    })


@site_user_required
@require_POST
def refresh(request, pk, project_id):
    db = _db(request, pk)
    project = _project(db, project_id)
    try:
        if project.source == OwsProject.Source.DATABASE:
            ows.refresh_from_database(project)
            messages.success(request, "پروژه از نسخه ذخیره‌شده در پایگاه داده به‌روز شد.")
        else:
            f = request.FILES.get("file")
            if not f or not f.name.lower().endswith(ALLOWED_EXT):
                messages.error(request, "فایل .qgz یا .qgs جدید را انتخاب کنید.")
            else:
                ows._apply(project, f.read(), f.name)
                project.source_name = f.name[:255]
                project.save(update_fields=["source_name"])
                messages.success(request, "پروژه با فایل جدید جایگزین شد؛ آدرس‌ها همان قبلی است.")
    except (qgis.ProjectError, ows.OwsError) as exc:
        messages.error(request, str(exc))
    return redirect("publish:ows_detail", pk=db.pk, project_id=project.pk)


@site_user_required
@require_POST
def delete(request, pk, project_id):
    db = _db(request, pk)
    project = _project(db, project_id)
    ows.remove_file(project)
    project.delete()
    messages.success(request, f"پروژه «{project.title}» حذف شد؛ آدرس WMS/WFS آن دیگر کار نمی‌کند.")
    return redirect("publish:ows", pk=db.pk)
