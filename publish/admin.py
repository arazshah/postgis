from django.contrib import admin

from .models import ApiKey, DailyUsage, Layer, OwsProject, Service


class LayerInline(admin.TabularInline):
    model = Layer
    extra = 0
    fields = ("table", "schema", "is_public", "slug", "srid", "geom_type")
    readonly_fields = ("slug", "srid", "geom_type")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("slug", "database", "created_at")
    search_fields = ("slug", "database__db_name")
    inlines = [LayerInline]


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "prefix", "database", "created_at", "last_used_at", "revoked_at")
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at")
    search_fields = ("prefix", "database__db_name")


@admin.register(DailyUsage)
class DailyUsageAdmin(admin.ModelAdmin):
    list_display = ("database", "day", "requests")
    list_filter = ("day",)
    search_fields = ("database__db_name",)


@admin.register(OwsProject)
class OwsProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "service", "is_public", "wfs_enabled", "updated_at")
    list_filter = ("is_public", "source")
    search_fields = ("slug", "title", "service__database__db_name")
    readonly_fields = ("slug", "layers", "warnings", "created_at", "updated_at")
