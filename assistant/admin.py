from django.contrib import admin
from django.db.models import Count, Q

from .models import Usage


@admin.register(Usage)
class UsageAdmin(admin.ModelAdmin):
    list_display = ["created_at", "status", "mode", "path", "answer_chars", "latency_ms", "helpful"]
    list_filter = ["status", "mode", "helpful", "created_at"]
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in Usage._meta.fields]
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        agg = Usage.objects.aggregate(
            total=Count("id"), ok=Count("id", filter=Q(status="ok")),
            none=Count("id", filter=Q(status="no_answer")), err=Count("id", filter=Q(status="error")),
            up=Count("id", filter=Q(helpful=True)), down=Count("id", filter=Q(helpful=False)))
        self.message_user(
            request,
            f"کل پرسش‌ها {agg['total']} — پاسخ‌داده‌شده {agg['ok']} — بدون پاسخ در منابع {agg['none']} — "
            f"خطا {agg['err']} — مفید {agg['up']} / نامفید {agg['down']}. "
            "پرسش‌های بی‌پاسخ را در «جست‌وجوهای بی‌نتیجه» پایگاه دانش ببینید و برایشان مقاله بنویسید.")
        return super().changelist_view(request, extra_context)
