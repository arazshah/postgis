from django import forms
from django.contrib import admin, messages

from jobs.models import Job

from .models import GeoServerInstance, Raster


class GeoServerForm(forms.ModelForm):
    admin_password = forms.CharField(label="رمز مدیر GeoServer", required=False, widget=forms.PasswordInput,
                                     help_text="برای ساخت دستی: رمز مدیر GeoServer را وارد کنید (رمزنگاری‌شده ذخیره می‌شود).")

    class Meta:
        model = GeoServerInstance
        fields = ["status", "url", "admin_user", "memory_mb", "coolify_uuid", "message"]

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("admin_password"):
            obj.set_password(self.cleaned_data["admin_password"])
        if commit:
            obj.save()
        return obj


@admin.register(GeoServerInstance)
class GeoServerAdmin(admin.ModelAdmin):
    form = GeoServerForm
    list_display = ("database", "status", "url", "version", "updated_at")
    list_filter = ("status",)
    readonly_fields = ("version", "created_at", "updated_at")
    actions = ["configure"]

    @admin.action(description="ساخت یا پیکربندی دوباره (workspace، اتصال PostGIS و لایه‌ها)")
    def configure(self, request, queryset):
        for inst in queryset:
            Job.objects.create(kind=Job.Kind.GEOSERVER, database=inst.database, status=Job.Status.QUEUED)
            self.message_user(request, f"{inst.database}: در صف worker.", messages.SUCCESS)


@admin.register(Raster)
class RasterAdmin(admin.ModelAdmin):
    list_display = ("title", "database", "status", "bands", "size_bytes", "is_public", "created_at")
    list_filter = ("status", "is_public")
    search_fields = ("title", "database__db_name")
    readonly_fields = [f.name for f in Raster._meta.fields]

    def has_add_permission(self, request):
        return False
