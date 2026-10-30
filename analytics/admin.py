from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.template.response import TemplateResponse
from django.utils.html import format_html

from . import classify as cl
from . import reports
from .models import Event, SourceReport, TrackedLink, Visit, Visitor


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

    def get_urls(self):
        from django.urls import path

        return [path("export/", self.admin_site.admin_view(self.export_view), name="analytics_export"),
                *super().get_urls()]

    def export_view(self, request):
        """خروجی اکسل کامل (همه‌ی رویدادها و وضعیت سایت)؛ days=0 یعنی همه‌ی زمان‌ها."""
        from django.http import HttpResponse
        from django.utils import timezone

        from . import export

        if not self.has_module_permission(request):
            raise PermissionDenied
        try:
            days = max(0, min(int(request.GET.get("days", 90)), 3650))
        except ValueError:
            days = 90
        resp = HttpResponse(export.build(days),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="postgis-analytics-{timezone.now():%Y%m%d-%H%M}.xlsx"'
        resp["Cache-Control"] = "no-store"
        return resp

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
                    "visits_count", "user", "flag")
    list_filter = ("flag", "first_source", "first_medium", "device", "in_app")
    actions = ["clear_flag", "mark_bot"]
    search_fields = ("vid", "first_campaign", "first_landing", "user__phone")
    date_hierarchy = "first_seen"
    list_select_related = ("user",)

    @admin.display(description="شناسه")
    def vid_short(self, obj):
        return obj.vid[:8]

    @admin.action(description="برداشتن برچسب (دوباره در آمار شمرده شود)")
    def clear_flag(self, request, queryset):
        n = queryset.exclude(flag="").update(flag="")
        self.message_user(request, f"برچسب {n} بازدیدکننده برداشته شد.")

    @admin.action(description="برچسب «مشکوک به ربات»")
    def mark_bot(self, request, queryset):
        n = queryset.filter(user__isnull=True, flag="").update(flag=Visitor.FLAG_BOT)
        self.message_user(request, f"{n} بازدیدکننده مشکوک به ربات علامت خورد.")


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


class TrackedLinkForm(forms.ModelForm):
    class Meta:
        model = TrackedLink
        exclude = ("clicks", "last_click_at")

    def clean_destination(self):
        value = (self.cleaned_data.get("destination") or "/").strip()
        if not value.startswith("/") or value.startswith("//") or "\\" in value or "://" in value:
            raise ValidationError("مقصد باید مسیر داخل همین سایت باشد و با / شروع شود؛ مثلاً / یا /accounts/login/")
        return value

    def clean_slug(self):
        return self.cleaned_data["slug"].lower()

    def _norm(self, name, limit):
        value = cl.clean(self.cleaned_data.get(name), limit)
        return value.replace(" ", "-")

    def clean_utm_source(self):
        value = self._norm("utm_source", 80)
        if not value:
            raise ValidationError("منبع الزامی است؛ مثلاً linkedin یا telegram")
        return value

    def clean_utm_medium(self):
        return self._norm("utm_medium", 40) or "none"

    def clean_utm_campaign(self):
        return self._norm("utm_campaign", 120)

    def clean_utm_content(self):
        return self._norm("utm_content", 120)

    def clean_utm_term(self):
        return self._norm("utm_term", 120)


@admin.register(TrackedLink)
class TrackedLinkAdmin(admin.ModelAdmin):
    """سازنده UTM + لینک کوتاه: لینک را بساز، در تبلیغ یا کانال بگذار و در «گزارش منابع ورود» نتیجه را ببین."""

    form = TrackedLinkForm
    list_display = ("name", "short_link", "utm_source", "utm_medium", "utm_campaign", "clicks", "visitors", "signups",
                    "is_active")
    list_filter = ("is_active", "utm_source", "utm_medium")
    search_fields = ("name", "slug", "utm_campaign")
    readonly_fields = ("short_link", "full_link", "clicks", "last_click_at", "created_at")
    fields = ("name", "slug", "destination", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
              "is_active", "short_link", "full_link", "clicks", "last_click_at", "created_at")

    def _abs(self, path):
        return settings.CANONICAL_URL + path

    @admin.display(description="لینک کوتاه (این را در تبلیغ بگذارید)")
    def short_link(self, obj):
        if not obj.pk:
            return "پس از ذخیره ساخته می‌شود"
        url = self._abs(f"/go/{obj.slug}/")
        return format_html('<input type="text" readonly dir="ltr" size="52" value="{}" onfocus="this.select()">', url)

    @admin.display(description="لینک کامل با UTM (بدون کوتاه‌کننده)")
    def full_link(self, obj):
        if not obj.pk:
            return "پس از ذخیره ساخته می‌شود"
        return format_html('<input type="text" readonly dir="ltr" size="80" value="{}" onfocus="this.select()">',
                           self._abs(obj.target_path()))

    def _visitors(self, obj):
        qs = Visitor.objects.filter(first_source=obj.utm_source, first_medium=obj.utm_medium)
        return qs.filter(first_campaign=obj.utm_campaign) if obj.utm_campaign else qs

    @admin.display(description="بازدیدکننده جدید")
    def visitors(self, obj):
        return self._visitors(obj).count()

    @admin.display(description="ثبت‌نام")
    def signups(self, obj):
        return Event.objects.filter(name=Event.SIGNUP, visitor__in=self._visitors(obj)).values("visitor").distinct().count()
