from django.contrib import admin

from .models import SatRequest


@admin.register(SatRequest)
class SatRequestAdmin(admin.ModelAdmin):
    list_display = ["created_at", "database", "product", "scene_date", "area_km2", "status", "charged"]
    list_filter = ["status", "product", "charged"]
    search_fields = ["database__db_name", "scene_id", "token"]
    readonly_fields = ["token", "database", "user", "product", "scene_id", "scene_date", "cloud", "bbox", "area_km2",
                       "est_bytes", "remote", "raster", "created_at", "finished_at"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False
