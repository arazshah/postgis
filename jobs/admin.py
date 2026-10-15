from django.contrib import admin
from django.template.defaultfilters import filesizeformat

from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "status", "trigger", "database", "size", "created_at", "finished_at", "short_msg")
    list_filter = ("kind", "status", "trigger")
    search_fields = ("database__db_name", "message")
    readonly_fields = [f.name for f in Job._meta.fields]

    @admin.display(description="حجم")
    def size(self, obj):
        return filesizeformat(obj.size_bytes) if obj.size_bytes else "—"

    @admin.display(description="پیام")
    def short_msg(self, obj):
        return obj.message[:80]

    def has_add_permission(self, request):
        return False
