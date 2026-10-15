from django.contrib import admin, messages
from django.shortcuts import redirect
from django.template.defaultfilters import filesizeformat
from django.urls import path

from jobs.models import Job

from . import basemap, osm
from .models import Area


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ("name", "level", "province", "name_en", "population")
    list_filter = ("level", "province")
    search_fields = ("name", "name_en", "province")
    readonly_fields = ("name", "name_en", "level", "province", "osm_id", "population", "bbox")
    exclude = ("geometry",)
    change_list_template = "admin/iranmap/area/change_list.html"

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        return [path("rebuild/<str:what>/", self.admin_site.admin_view(self.rebuild), name="iranmap_rebuild"),
                *super().get_urls()]

    def rebuild(self, request, what):
        if request.method != "POST" or what not in ("basemap", "osm", "areas"):
            return redirect("admin:iranmap_area_changelist")
        kind = Job.Kind.BASEMAP if what == "basemap" else Job.Kind.OSM_REFRESH
        if Job.objects.filter(kind=kind, status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).exists():
            messages.warning(request, "این کار همین الان در صف یا در حال اجراست.")
        else:
            Job.objects.create(kind=kind, trigger=Job.Trigger.MANUAL, user=None, status=Job.Status.QUEUED,
                               params={"download": what == "osm"})
            messages.success(request, "در صف worker قرار گرفت؛ نتیجه در «کارهای پس‌زمینه» دیده می‌شود.")
        return redirect("admin:iranmap_area_changelist")

    def changelist_view(self, request, extra_context=None):
        bm, src = basemap.info(), osm.source_info()
        last = {k: Job.objects.filter(kind=k).first() for k in (Job.Kind.BASEMAP, Job.Kind.OSM_REFRESH)}
        status = [
            ("نقشه پایه ایران (PMTiles)",
             f"{filesizeformat(bm['size'])} — به‌روز شده {bm['updated']:%Y-%m-%d}" if bm else "ساخته نشده", last[Job.Kind.BASEMAP]),
            ("فایل OSM ایران (Geofabrik)",
             f"{filesizeformat(src['size'])} — به‌روز شده {src['updated']:%Y-%m-%d}" if src else "دانلود نشده",
             last[Job.Kind.OSM_REFRESH]),
        ]
        return super().changelist_view(request, {**(extra_context or {}), "map_status": status})
