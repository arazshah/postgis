import json

from django.contrib import admin, messages
from django.http import HttpResponse
from django.urls import path, reverse
from django.utils.html import format_html

from . import export
from .models import Article, ArticleChunk, Category, Feedback, MissedQuery


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "icon", "order", "is_active", "article_count")
    list_editable = ("order", "is_active")
    prepopulated_fields = {"slug": ("title",)}

    @admin.display(description="مقاله‌ها")
    def article_count(self, obj):
        return obj.articles.count()


@admin.action(description="انتشار مقاله‌های انتخاب‌شده")
def publish(modeladmin, request, queryset):
    for a in queryset:
        a.status = Article.Status.PUBLISHED
        a.save()


@admin.action(description="تبدیل به پیش‌نویس")
def unpublish(modeladmin, request, queryset):
    for a in queryset:
        a.status = Article.Status.DRAFT
        a.save()


@admin.action(description="ثبت بازبینی امروز")
def mark_reviewed(modeladmin, request, queryset):
    from django.utils import timezone

    queryset.update(reviewed_at=timezone.localdate())


@admin.action(description="بازگرداندن به نسخه فایل محتوا (ویرایش‌های پنل از بین می‌رود)")
def reset_to_file(modeladmin, request, queryset):
    from . import loader

    slugs = {f.slug for f in loader.load_articles()}
    done = 0
    for a in queryset.filter(slug__in=slugs):
        a.locked = False
        a.managed = True
        a.content_hash = ""
        a.save()
        done += 1
    if done:
        report = loader.sync()
        messages.success(request, f"{done} مقاله به نسخه فایل بازگردانده شد. ({report.summary()})")
    else:
        messages.warning(request, "برای مقاله‌های انتخاب‌شده فایل محتوا پیدا نشد.")


class ChunkInline(admin.TabularInline):
    model = ArticleChunk
    extra = 0
    can_delete = False
    fields = ("ordinal", "heading", "text")
    readonly_fields = ("ordinal", "heading", "text")
    verbose_name_plural = "تکه‌های بازیابی (برای دستیار؛ خودکار ساخته می‌شود)"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "kind", "audience", "status", "is_featured", "reviewed_at", "source", "view_link")
    list_filter = ("status", "audience", "kind", "category", "is_featured", "locked")
    search_fields = ("title", "summary", "keywords", "slug", "body")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("related",)
    actions = [publish, unpublish, mark_reviewed, reset_to_file]
    inlines = [ChunkInline]
    save_on_top = True
    fieldsets = (
        (None, {"fields": ("title", "slug", "category", "kind", "audience", "status")}),
        ("پاسخ", {"fields": ("summary", "body")}),
        ("جست‌وجو و پیوندها", {"fields": ("keywords", "related", "is_featured", "order", "reviewed_at")}),
        ("همگام‌سازی", {"fields": ("locked",), "classes": ("collapse",)}),
    )

    @admin.display(description="منبع")
    def source(self, obj):
        if not obj.managed:
            return "پنل"
        return "پنل (ویرایش‌شده)" if obj.locked else "فایل"

    @admin.display(description="نمایش")
    def view_link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">مشاهده</a>', obj.get_absolute_url())

    def save_model(self, request, obj, form, change):
        # ویرایش در پنل = نسخه معتبر؛ همگام‌سازی بعدی از فایل رویش نمی‌نویسد
        if change and obj.managed and form.changed_data and "locked" not in form.changed_data:
            obj.locked = True
        super().save_model(request, obj, form, change)

    def get_urls(self):
        return [
            path("export/", self.admin_site.admin_view(self.export_view), name="kb_article_export"),
            *super().get_urls(),
        ]

    def export_view(self, request):
        """دانلود JSONL تکه‌های همه مقاله‌ها (شامل مستندات داخلی) برای ساخت نمایه برداری دستیار."""
        if not self.has_view_permission(request):
            return HttpResponse(status=403)
        audience = request.GET.get("audience", "all")
        fmt = request.GET.get("format", "chunks")
        rows = (export.chunk_rows if fmt == "chunks" else export.article_rows)(audience)
        body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
        resp = HttpResponse(body, content_type="application/x-ndjson; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="kb-{fmt}-{audience}.jsonl"'
        return resp

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["export_url"] = reverse("admin:kb_article_export")
        return super().changelist_view(request, extra_context)


@admin.register(MissedQuery)
class MissedQueryAdmin(admin.ModelAdmin):
    list_display = ("sample", "count", "last_seen", "resolved")
    list_filter = ("resolved",)
    list_editable = ("resolved",)
    search_fields = ("sample",)
    ordering = ("resolved", "-count")

    def has_add_permission(self, request):
        return False


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("article", "helpful", "comment", "created_at")
    list_filter = ("helpful", "article__category")
    search_fields = ("article__title", "comment")
    readonly_fields = ("article", "helpful", "comment", "session_key", "created_at")

    def has_add_permission(self, request):
        return False
