"""پنل مدیریت سکوی پلاگین: وضعیت و مجوز هر پلاگین، و سازمان‌های مشتری.

(کمک‌تابع‌های داشبورد پنل در kernel/dash.py است.)
"""
from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.utils.html import format_html

from . import workspace
from .models import Entitlement, Organization, OrgMember, PluginState
from .plugins import registry


def sync_states() -> int:
    """برای هر پلاگین غیرسیستمیِ نصب‌شده یک ردیف وضعیت (پیش‌فرض: روشن و باز) می‌سازد تا در پنل قابل کنترل باشد."""
    made = 0
    for p in registry.plugins.values():
        if p.kind != "system":
            _, new = PluginState.objects.get_or_create(plugin_id=p.id)
            made += new
    return made


class EntitlementForm(forms.ModelForm):
    class Meta:
        model = Entitlement
        fields = ("kind", "subject", "source", "expires_at", "limits", "note")

    def clean(self):
        data = super().clean()
        kind, subject = data.get("kind"), (data.get("subject") or "").strip()
        if not kind:
            return data
        data["subject"] = subject
        if kind == Entitlement.Kind.ALL:
            data["subject"] = ""
            return data
        if not subject:
            raise forms.ValidationError("شناسه‌ی دارنده را بنویسید.")
        if kind == Entitlement.Kind.PLAN:
            return data
        if not subject.isdigit():
            raise forms.ValidationError("شناسه‌ی عددی بنویسید.")
        exists = {
            Entitlement.Kind.ORG: lambda: Organization.objects.filter(pk=subject).exists(),
            Entitlement.Kind.USER: lambda: get_user_model().objects.filter(pk=subject).exists(),
            Entitlement.Kind.WORKSPACE: lambda: workspace.peek(int(subject)) is not None,
        }[kind]()
        if not exists:
            raise forms.ValidationError("دارنده‌ای با این شناسه پیدا نشد.")
        return data


class EntitlementInline(admin.TabularInline):
    model = Entitlement
    form = EntitlementForm
    extra = 0
    fields = ("kind", "subject", "source", "expires_at", "limits", "note")


@admin.register(PluginState)
class PluginStateAdmin(admin.ModelAdmin):
    list_display = ("title", "plugin_id", "kind", "version", "access", "enabled", "grants", "health")
    list_filter = ("access", "enabled")
    search_fields = ("plugin_id", "note")
    inlines = [EntitlementInline]
    actions = ["make_restricted", "make_open", "turn_on", "turn_off"]
    fields = ("plugin_id", "enabled", "access", "note")
    readonly_fields = ("plugin_id",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        sync_states()
        return super().changelist_view(request, extra_context)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("entitlements")

    @admin.display(description="پلاگین")
    def title(self, obj):
        p = registry.plugins.get(obj.plugin_id)
        return p.name if p else format_html('<span class="muted">{} (نصب نیست)</span>', obj.plugin_id)

    @admin.display(description="نوع")
    def kind(self, obj):
        p = registry.plugins.get(obj.plugin_id)
        return {"system": "سیستمی", "feature": "قابلیت", "custom": "اختصاصی"}.get(p.kind, p.kind) if p else "—"

    @admin.display(description="نسخه")
    def version(self, obj):
        p = registry.plugins.get(obj.plugin_id)
        return p.version if p else "—"

    @admin.display(description="مجوز")
    def grants(self, obj):
        return len(obj.entitlements.all())

    @admin.display(description="سلامت")
    def health(self, obj):
        if obj.plugin_id in registry.errors:
            return format_html('<b style="color:#b42318">{}</b>', "خطای بارگذاری")
        return "سالم" if obj.plugin_id in registry.plugins else "نصب نیست"

    def save_formset(self, request, form, formset, change):
        for inst in formset.save(commit=False):
            if isinstance(inst, Entitlement) and inst.granted_by_id is None:
                inst.granted_by = request.user
            inst.save()
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()

    @admin.action(description="محدود به دارندگان مجوز")
    def make_restricted(self, request, qs):
        self.message_user(request, f"{qs.update(access=PluginState.Access.RESTRICTED)} پلاگین محدود شد.", messages.SUCCESS)

    @admin.action(description="باز برای همه")
    def make_open(self, request, qs):
        self.message_user(request, f"{qs.update(access=PluginState.Access.OPEN)} پلاگین باز شد.", messages.SUCCESS)

    @admin.action(description="روشن کردن")
    def turn_on(self, request, qs):
        self.message_user(request, f"{qs.update(enabled=True)} پلاگین روشن شد.", messages.SUCCESS)

    @admin.action(description="خاموش کردن (ناپدید برای همه)")
    def turn_off(self, request, qs):
        self.message_user(request, f"{qs.update(enabled=False)} پلاگین خاموش شد.", messages.WARNING)


class OrgMemberInline(admin.TabularInline):
    model = OrgMember
    extra = 0
    raw_id_fields = ("user",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "member_count", "created_at")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [OrgMemberInline]

    @admin.display(description="اعضا")
    def member_count(self, obj):
        return obj.members.count()
