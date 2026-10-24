from django.contrib import admin

from .models import GnssDriver, SurveyProject


@admin.register(SurveyProject)
class SurveyProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "database", "srid", "created_at", "archived_at")
    list_filter = ("srid",)
    search_fields = ("name", "slug", "database__db_name")
    readonly_fields = ("database", "slug", "srid", "created_by", "created_at")


@admin.register(GnssDriver)
class GnssDriverAdmin(admin.ModelAdmin):
    list_display = ("driver_id", "version", "level", "enabled", "owner")
    list_filter = ("level", "enabled")
    search_fields = ("driver_id",)
