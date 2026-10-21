from django.contrib import admin
from django.template.response import TemplateResponse

from . import reports
from .models import Event, SourceReport, Visit, Visitor


class ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SourceReport)
class SourceReportAdmin(admin.ModelAdmin):
    """گزارش «منابع ورود»: از کدام تبلیغ/لینک/سایت آمدند و کجای قیف ثبت‌نام می‌مانند."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        try:
            days = int(request.GET.get("days", 30))
        except ValueError:
            days = 30
        ctx = {**self.admin_site.each_context(request), "title": "گزارش منابع ورود", "opts": self.model._meta,
               **reports.build(days)}
        return TemplateResponse(request, "admin/analytics/sources.html", ctx)


@admin.register(Visitor)
class VisitorAdmin(ReadOnly):
    list_display = ("vid_short", "first_seen", "first_source", "first_medium", "first_campaign", "device", "in_app",
                    "visits_count", "user")
    list_filter = ("first_source", "first_medium", "device", "in_app")
    search_fields = ("vid", "first_campaign", "first_landing", "user__phone")
    date_hierarchy = "first_seen"
    list_select_related = ("user",)

    @admin.display(description="شناسه")
    def vid_short(self, obj):
        return obj.vid[:8]


@admin.register(Visit)
class VisitAdmin(ReadOnly):
    list_display = ("started_at", "source", "medium", "campaign", "referrer_host", "landing_path", "pages", "device")
    list_filter = ("source", "medium", "device", "in_app")
    search_fields = ("campaign", "landing_path", "referrer_host")
    date_hierarchy = "started_at"


@admin.register(Event)
class EventAdmin(ReadOnly):
    list_display = ("created_at", "name", "path", "visitor")
    list_filter = ("name",)
    date_hierarchy = "created_at"
