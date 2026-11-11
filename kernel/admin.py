"""پنل مدیریت سکوی پلاگین: وضعیت و مجوز هر پلاگین، و سازمان‌های مشتری.

(کمک‌تابع‌های داشبورد پنل در kernel/dash.py است.)
"""
from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.html import format_html, format_html_join

from . import conf, entitlements, pkg, stepup, workspace
from .models import Entitlement, Organization, OrgMember, PluginRelease, PluginState
from .plugins import registry


def sync_states() -> int:
    """برای هر پلاگین غیرسیستمیِ نصب‌شده یک ردیف وضعیت (پیش‌فرض: روشن و باز) می‌سازد تا در پنل قابل کنترل باشد."""
    made = 0
    for p in registry.plugins.values():
        if p.kind != "system":
            _, new = PluginState.objects.get_or_create(plugin_id=p.id)
            made += new
    return made


def options_form(opts, data=None) -> forms.Form:
    """فرم پویا از گزینه‌های اعلام‌شده؛ مقدار secret هرگز پر نمی‌شود (فقط «تنظیم شده»)."""
    fields = {}
    for o in opts:
        common = {"label": o.label, "required": False, "help_text": o.help}
        if o.kind == "bool":
            fields[o.key] = forms.BooleanField(initial=bool(conf.get(o.plugin, o.key)), **common)
        elif o.kind == "int":
            fields[o.key] = forms.IntegerField(initial=conf.get(o.plugin, o.key), min_value=o.min, max_value=o.max, **common)
        elif o.kind == "choice":
            fields[o.key] = forms.ChoiceField(choices=o.choices, initial=conf.get(o.plugin, o.key), **common)
        elif o.kind == "secret":
            hint = "تنظیم شده؛ برای تغییر مقدار تازه بنویسید" if conf.is_set(o.plugin, o.key) else "تنظیم نشده"
            fields[o.key] = forms.CharField(widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
                                            label=o.label, required=False, help_text=f"{hint}. {o.help}".strip())
        else:
            fields[o.key] = forms.CharField(initial=conf.get(o.plugin, o.key), max_length=2000, **common)
    return type("OptionsForm", (forms.Form,), fields)(data)


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
    fields = ("plugin_id", "enabled", "access", "note", "options_link")
    readonly_fields = ("plugin_id", "options_link")

    @admin.display(description="تنظیمات پلاگین")
    def options_link(self, obj):
        from django.urls import reverse

        n = len(conf.options(obj.plugin_id))
        if not obj.pk or not n:
            return "—"
        return format_html('<a href="{}">{} گزینه؛ ویرایش</a>', reverse("admin:kernel_pluginstate_options", args=[obj.pk]), n)

    def get_urls(self):
        from django.urls import path

        return [path("<int:pk>/options/", self.admin_site.admin_view(self.options_view),
                     name="kernel_pluginstate_options")] + super().get_urls()

    def options_view(self, request, pk):
        from django.shortcuts import get_object_or_404
        from django.template.response import TemplateResponse
        from django.urls import reverse

        obj = get_object_or_404(PluginState, pk=pk)
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        opts = conf.options(obj.plugin_id)
        form = options_form(opts, request.POST if request.method == "POST" else None)
        back = reverse("admin:kernel_pluginstate_change", args=[obj.pk])
        if request.method == "POST" and form.is_valid():
            changing_secret = any(o.kind == "secret" and form.cleaned_data.get(o.key) for o in opts)
            if changing_secret and not stepup.ok(request):
                return redirect(stepup.url(request))
            for o in opts:
                conf.set_value(obj.plugin_id, o.key, form.cleaned_data.get(o.key))
            messages.success(request, "تنظیمات پلاگین ذخیره شد.")
            return redirect(back)
        return TemplateResponse(request, "admin/kernel/pluginstate/options.html", {
            **self.admin_site.each_context(request), "title": f"تنظیمات {obj.plugin_id}", "form": form, "obj": obj,
            "back": back, "opts": opts, "has_view_permission": True})

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
        n = qs.update(access=PluginState.Access.RESTRICTED)
        entitlements.invalidate()  # update سیگنال نمی‌فرستد
        self.message_user(request, f"{n} پلاگین محدود شد.", messages.SUCCESS)

    @admin.action(description="باز برای همه")
    def make_open(self, request, qs):
        n = qs.update(access=PluginState.Access.OPEN)
        entitlements.invalidate()
        self.message_user(request, f"{n} پلاگین باز شد.", messages.SUCCESS)

    @admin.action(description="روشن کردن")
    def turn_on(self, request, qs):
        n = qs.update(enabled=True)
        entitlements.invalidate()
        self.message_user(request, f"{n} پلاگین روشن شد.", messages.SUCCESS)

    @admin.action(description="خاموش کردن (ناپدید برای همه)")
    def turn_off(self, request, qs):
        n = qs.update(enabled=False)
        entitlements.invalidate()
        self.message_user(request, f"{n} پلاگین خاموش شد.", messages.WARNING)


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


# ---------------------------------------------------------------------- نسخه‌ها و بارگذاری بسته‌ی پلاگین
class UploadForm(forms.Form):
    package = forms.FileField(label="بسته‌ی پلاگین (.gpkgx)", help_text="بسته باید با کلید یکی از ناشران مجاز امضا شده باشد (حداکثر ۲ مگابایت).")


@admin.register(PluginRelease)
class PluginReleaseAdmin(admin.ModelAdmin):
    list_display = ("plugin_id", "version", "name", "publisher", "status", "uploaded_by", "uploaded_at", "activated_at")
    list_filter = ("status", "publisher")
    search_fields = ("plugin_id", "name", "sha256")
    actions = ["activate_selected", "deactivate_selected"]
    change_list_template = "admin/kernel/pluginrelease/change_list.html"
    readonly_fields = ("plugin_id", "version", "name", "kind", "publisher", "sha256", "size", "status", "report_table",
                       "manifest_view", "uploaded_by", "approved_by", "uploaded_at", "activated_at")
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # فقط مشاهده؛ تغییر وضعیت با کنش‌های مجاز

    def has_delete_permission(self, request, obj=None):
        return False  # ردپای بسته‌ها ماندگار است

    def get_urls(self):
        from django.urls import path

        return [path("upload/", self.admin_site.admin_view(self.upload_view), name="kernel_pluginrelease_upload"),
                *super().get_urls()]

    def changelist_view(self, request, extra_context=None):
        extra = {"can_upload": request.user.has_perm("kernel.upload_pluginrelease"), **(extra_context or {})}
        return super().changelist_view(request, extra)

    def upload_view(self, request):
        from django.template.response import TemplateResponse
        from django.urls import reverse

        if not request.user.has_perm("kernel.upload_pluginrelease"):
            raise PermissionDenied
        if not stepup.ok(request):
            return redirect(stepup.url(request))
        form = UploadForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            try:
                rel = pkg.submit(form.cleaned_data["package"].read(), request.user)
            except pkg.PackageError as exc:
                messages.error(request, str(exc))
            else:
                (messages.success if rel.status == PluginRelease.Status.CHECKED else messages.error)(
                    request, "بسته بررسی شد و منتظر تأیید است." if rel.status == PluginRelease.Status.CHECKED
                    else "بسته در بررسی رد شد؛ گزارش را ببینید.")
                return redirect(reverse("admin:kernel_pluginrelease_change", args=[rel.pk]))
        return TemplateResponse(request, "admin/kernel/pluginrelease/upload.html", {
            **self.admin_site.each_context(request), "form": form, "title": "بارگذاری بسته‌ی پلاگین", "opts": self.model._meta,
            "keys": sorted(pkg.publisher_keys()) if _keys_ok() else []})

    @admin.display(description="گزارش بررسی")
    def report_table(self, obj):
        rows = format_html_join("", "<tr><td>{}</td><td>{}</td></tr>", (
            ("✓ " + s["stage"] if s["ok"] else "✗ " + s["stage"], s.get("detail", "")) for s in obj.report))
        return format_html("<table>{}</table>", rows)

    @admin.display(description="مانیفست")
    def manifest_view(self, obj):
        import json

        return format_html('<pre dir="ltr" style="white-space:pre-wrap">{}</pre>', json.dumps(obj.manifest, ensure_ascii=False, indent=2))

    @admin.action(description="تأیید و فعال‌سازی (یا بازگشت به این نسخه)")
    def activate_selected(self, request, qs):
        if not request.user.has_perm("kernel.activate_pluginrelease"):
            raise PermissionDenied
        if not stepup.ok(request):
            return redirect(stepup.url(request))
        for rel in qs:
            try:
                pkg.activate(rel, request.user)
            except pkg.PackageError as exc:
                self.message_user(request, f"{rel}: {exc}", messages.ERROR)
            else:
                self.message_user(request, f"{rel} فعال شد. تا مجوز ندهید هیچ مشتری آن را نمی‌بیند (از «پلاگین‌ها و مجوزها»).",
                                  messages.SUCCESS)
        entitlements.invalidate()

    @admin.action(description="غیرفعال‌سازی (برداشتن از سامانه)")
    def deactivate_selected(self, request, qs):
        if not request.user.has_perm("kernel.activate_pluginrelease"):
            raise PermissionDenied
        if not stepup.ok(request):
            return redirect(stepup.url(request))
        for rel in qs:
            pkg.deactivate(rel)
            self.message_user(request, f"{rel} غیرفعال شد.", messages.WARNING)
        entitlements.invalidate()


def _keys_ok() -> bool:
    try:
        pkg.publisher_keys()
        return True
    except pkg.PackageError:
        return False
