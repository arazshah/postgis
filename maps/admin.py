from django.contrib import admin

from .models import MapLayer, WebMap


class MapLayerInline(admin.TabularInline):
    model = MapLayer
    extra = 0
    fields = ("table", "schema", "title", "position", "visible", "srid", "geom_type")
    readonly_fields = ("srid", "geom_type")


@admin.register(WebMap)
class WebMapAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "database", "is_public", "updated_at")
    list_filter = ("is_public",)
    search_fields = ("slug", "title", "database__db_name")
    readonly_fields = ("slug", "created_at", "updated_at")
    inlines = [MapLayerInline]
