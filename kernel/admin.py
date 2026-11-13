"""پنل مدیریت سکوی پلاگین: وضعیت و مجوز هر پلاگین، و سازمان‌های مشتری.

(کمک‌تابع‌های داشبورد پنل در kernel/dash.py است.)
"""
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.html import format_html, format_html_join

from . import conf, entitlements, notify, pagekit, pkg, platform, stepup, studio, workspace
from .models import (
    Entitlement,
    NotifyChannel,
    Organization,
    OrgMember,
    PluginDraft,
    PluginRelease,
    PluginState,
    PluginTrip,
    PluginUsage,
    PublisherKey,
    SourceHost,
    SourceState,
)
from .plugins import registry


def sync_states() -> int:
    """برای هر پلاگین غیرسیستمیِ نصب‌شده یک ردیف وضعیت (پیش‌فرض: روشن و باز) می‌سازد تا در پنل قابل کنترل باشد."""
    made = 0
    for p in registry.plugins.values():
        if p.kind != "system":
            # سطح ۳ به‌طور پیش‌فرض «محدود و بدون مجوز» است؛ مدیر باید آگاهانه مجوز بدهد (ADR-0007)
            defaults = {"access": PluginState.Access.RESTRICTED} if p.tier == 3 else {}
            _, new = PluginState.objects.get_or_create(plugin_id=p.id, defaults=defaults)
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
    list_display = ("title", "plugin_id", "kind", "tier", "version", "access", "enabled", "grants", "health")
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

    @admin.display(description="سطح")
    def tier(self, obj):
        p = registry.plugins.get(obj.plugin_id)
        if not p:
            return "—"
        return {1: "۱ (صفحه)", 2: "۲ (کد در جعبه)", 3: "۳ (کد درون‌پردازه)"}.get(p.tier, p.tier) if p.kind != "system" else "سیستمی"

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


@admin.register(PluginUsage)
class PluginUsageAdmin(admin.ModelAdmin):
    """گزارش مصرف: فقط‌خواندنی (شمارنده‌ها را فقط هسته می‌نویسد)."""

    list_display = ("plugin_id", "metric", "day", "workspace_id", "user_id", "count")
    list_filter = ("plugin_id", "metric", "day")
    search_fields = ("plugin_id", "metric")
    date_hierarchy = "day"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------- استودیوی ساخت پلاگین
@admin.register(PluginDraft)
class PluginDraftAdmin(admin.ModelAdmin):
    """استودیو: ویرایش پیش‌نویس، بررسی زنده، پیش‌نمایش روی یک پایگاه داده و خروجی بدون امضا برای plugin_pack."""

    list_display = ("plugin_id", "name", "version", "page_count", "updated_by", "updated_at")
    search_fields = ("plugin_id", "name")

    def _allowed(self, request):
        return request.user.has_perm("kernel.upload_pluginrelease")

    def has_module_permission(self, request):
        return self._allowed(request)

    has_view_permission = has_change_permission = has_add_permission = lambda self, request, obj=None: self._allowed(request)

    def has_delete_permission(self, request, obj=None):
        return self._allowed(request)

    @admin.display(description="صفحه‌ها")
    def page_count(self, obj):
        return len(obj.pages or {})

    def get_urls(self):
        from django.urls import path

        wrap = self.admin_site.admin_view
        from . import import_view, new_view, studio_api

        return [path("import/", import_view.view, name="kernel_plugindraft_import"),
                path("<int:pk>/designer/", wrap(studio_api.designer), name="kernel_plugindraft_designer"),
                path("<int:pk>/designer/api/state/", wrap(studio_api.state), name="kernel_plugindraft_api_state"),
                path("<int:pk>/designer/api/op/", wrap(studio_api.op), name="kernel_plugindraft_api_op"),
                path("<int:pk>/designer/api/preview/<str:page>/", wrap(studio_api.preview), name="kernel_plugindraft_api_preview"),
                path("<int:pk>/designer/api/revisions/", wrap(studio_api.revisions), name="kernel_plugindraft_api_revisions"),
                path("<int:pk>/designer/api/assistant/", wrap(studio_api.assistant), name="kernel_plugindraft_api_assistant"),
                path("<int:pk>/designer/api/access/", wrap(studio_api.access), name="kernel_plugindraft_api_access"),
                path("<int:pk>/designer/api/media/", wrap(studio_api.media), name="kernel_plugindraft_api_media"),
                path("<int:pk>/designer/api/stats/", wrap(studio_api.stats), name="kernel_plugindraft_api_stats"),
                path("<int:pk>/designer/api/preview-live/", wrap(studio_api.preview_live), name="kernel_plugindraft_api_preview_live"),
                path("<int:pk>/designer/api/files/", wrap(studio_api.files), name="kernel_plugindraft_api_files"),
                path("<int:pk>/designer/api/releases/", wrap(studio_api.releases), name="kernel_plugindraft_api_releases"),
                path("<int:pk>/designer/api/compare/", wrap(studio_api.compare), name="kernel_plugindraft_api_compare"),
                path("<int:pk>/designer/api/rollback/", wrap(studio_api.rollback), name="kernel_plugindraft_api_rollback"),
                path("<int:pk>/designer/api/restore-release/", wrap(studio_api.restore_release), name="kernel_plugindraft_api_restore_release"),
                path("<int:pk>/designer/api/publish/", wrap(studio_api.publish_view), name="kernel_plugindraft_api_publish"),
                path("<int:pk>/designer/api/run/", wrap(studio_api.run), name="kernel_plugindraft_api_run"),
                path("<int:pk>/designer/api/restore/", wrap(studio_api.restore), name="kernel_plugindraft_api_restore"),
                path("new/", new_view.view, name="kernel_plugindraft_new"),
                path("wizard/", wrap(self.to_new), name="kernel_plugindraft_wizard_new"),  # نشانی‌های ویزارد و استودیوی قدیمی به استودیوی دیداری می‌رسند
                path("studio/new/", wrap(self.to_new)),
                path("<int:pk>/wizard/<int:step>/", wrap(self.to_designer), name="kernel_plugindraft_wizard"),
                path("<int:pk>/studio/", wrap(self.to_designer), name="kernel_plugindraft_studio"),
                path("<int:pk>/export/", wrap(self.export_view), name="kernel_plugindraft_export"),
                *super().get_urls()]

    def add_view(self, request, form_url="", extra_context=None):
        from django.urls import reverse

        return redirect(reverse("admin:kernel_plugindraft_new"))

    def to_new(self, request):
        from django.urls import reverse

        return redirect(reverse("admin:kernel_plugindraft_new"))

    def to_designer(self, request, pk, step=None):
        """پیش‌نویس استودیوی دیداری ← خودش؛ پیش‌نویس TOML قدیمی ← صفحه‌ی ورود (تبدیل بی‌اتلاف)."""
        from django.urls import reverse

        d = PluginDraft.objects.filter(pk=pk).first()
        if d is not None and not d.wizard:
            return redirect(reverse("admin:kernel_plugindraft_import") + f"?draft={d.pk}")
        return redirect(reverse("admin:kernel_plugindraft_designer", args=[pk]))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return self.to_designer(request, object_id)

    def export_view(self, request, pk):
        from django.http import HttpResponse
        from django.shortcuts import get_object_or_404

        if not self._allowed(request):
            raise PermissionDenied
        d = get_object_or_404(PluginDraft, pk=pk)
        steps = studio.check(d)
        if not studio.ok(steps):
            messages.error(request, "پیش‌نویس هنوز بررسی را نمی‌گذراند؛ خروجی ساخته نمی‌شود (در استودیو «کیفیت» را ببینید).")
            return self.to_designer(request, d.pk)
        r = HttpResponse(studio.export_zip(d), content_type="application/zip")
        r["Content-Disposition"] = f'attachment; filename="{d.plugin_id}-{d.version}-draft.zip"'
        return r


class SeenFilter(admin.SimpleListFilter):
    title = "وضعیت بررسی"
    parameter_name = "seen"

    def lookups(self, request, model_admin):
        return [("no", "دیده‌نشده"), ("yes", "دیده‌شده")]

    def queryset(self, request, queryset):
        if self.value() == "no":
            return queryset.filter(seen_at__isnull=True)
        if self.value() == "yes":
            return queryset.filter(seen_at__isnull=False)
        return queryset


@admin.register(PluginTrip)
class PluginTripAdmin(admin.ModelAdmin):
    """ردپای قطع‌کن خودکار؛ فقط‌خواندنی به‌جز علامت «دیده‌شده» (کارت داشبورد تا آن موقع می‌ماند)."""

    list_display = ("plugin_id", "version", "action", "restored_version", "errors", "runs", "tripped_at", "seen_at")
    list_filter = (SeenFilter, "action", "plugin_id")
    date_hierarchy = "tripped_at"
    actions = ["mark_seen"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="علامت‌گذاری به‌عنوان دیده‌شده")
    def mark_seen(self, request, queryset):
        from django.utils import timezone

        n = queryset.filter(seen_at__isnull=True).update(seen_at=timezone.now())
        self.message_user(request, f"{n} مورد دیده‌شده شد.", messages.SUCCESS)


# ---------------------------------------------------------------------- سکو: کلیدهای ناشر و اجرای کد سطح ۲
def _clean_url(raw: str) -> str:
    """نشانی http(s) معتبر یا ValueError. نشانی IP محلی-پیوندی (مثل متادیتای ابر) پذیرفته نمی‌شود."""
    import ipaddress
    from urllib.parse import urlparse

    raw = (raw or "").strip().rstrip("/")
    if not raw:
        return ""
    u = urlparse(raw)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("نشانی باید با http:// یا https:// شروع شود.")
    try:
        ip = ipaddress.ip_address(u.hostname)
    except ValueError:
        return raw
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise ValueError("این نشانی پذیرفته نیست.")
    return raw


@admin.register(PublisherKey)
class PublisherKeyAdmin(admin.ModelAdmin):
    """صفحه‌ی «سکو»: کلید عمومی ناشران (کلید خصوصی در مرورگر ساخته می‌شود و به سرور نمی‌رسد) و تنظیم اجرای کد سطح ۲."""

    list_display = ("name", "active", "added_by", "created_at")

    def has_module_permission(self, request):
        return request.user.is_superuser or request.user.has_perm("kernel.change_publisherkey")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from django.template.response import TemplateResponse

        if not self.has_module_permission(request):
            raise PermissionDenied
        mutating = {"add_key", "remove_key", "toggle_key", "save_runner", "save_publish", "save_sources"}
        action = request.POST.get("action", "") if request.method == "POST" else ""
        if action in mutating and not stepup.ok(request):
            return redirect(stepup.url(request))
        if action:
            self._handle(request, action)
            return redirect(request.path)
        rows = PublisherKey.objects.select_related("added_by")
        ok, detail = platform.runner_health() if platform.runner_mode() == "remote" else (False, "حالت اجرا «خاموش» است.")
        return TemplateResponse(request, "admin/kernel/platform.html", {
            **self.admin_site.each_context(request), "title": "سکو: کلیدهای ناشر و اجرای کد", "opts": self.model._meta,
            "keys": rows, "env_keys": sorted(_env_key_names()), "mode": platform.runner_mode(),
            "url": platform.get("runner_url"), "callback": platform.get("runner_callback"),
            "timeout": platform.get("runner_timeout", "10"), "default_url": platform.DEFAULT_URL,
            "default_callback": platform.DEFAULT_CALLBACK, "token_ok": bool(platform.runner_token()),
            "health_ok": ok, "health": detail, "from_panel": platform._from_panel(), "second_approval": pkg.second_approval_required(), "sources_on": platform.sources_enabled(), **(extra_context or {})})

    def _handle(self, request, action: str) -> None:
        import logging

        log = logging.getLogger(__name__)
        post = request.POST
        if action == "add_key":
            name, key = post.get("name", "").strip(), post.get("public_key", "").strip()
            if not platform.NAME_RE.fullmatch(name):
                return messages.error(request, "نام ناشر: حروف کوچک انگلیسی، عدد، - و _ (۲ تا ۴۰ نویسه).")
            if not platform.valid_public_key(key):
                return messages.error(request, "کلید عمومی نامعتبر است (base64 یک کلید Ed25519).")
            if PublisherKey.objects.filter(name=name).exists() or name in _env_key_names():
                return messages.error(request, "ناشری با این نام از پیش هست.")
            PublisherKey.objects.create(name=name, public_key=key, added_by=request.user)
            log.warning("publisher key added: %s by user %s", name, request.user.pk)
            messages.success(request, f"کلید ناشر «{name}» افزوده شد. بسته‌های امضاشده با آن پذیرفته می‌شوند.")
        elif action in ("remove_key", "toggle_key"):
            k = PublisherKey.objects.filter(pk=post.get("pk")).first()
            if k is None:
                return messages.error(request, "کلید پیدا نشد.")
            if action == "remove_key":
                k.delete()
                log.warning("publisher key removed: %s by user %s", k.name, request.user.pk)
                messages.warning(request, f"کلید «{k.name}» حذف شد؛ بسته‌های فعال از پیش بررسی‌شده می‌مانند.")
            else:
                k.active = not k.active
                k.save(update_fields=["active"])
                messages.success(request, f"کلید «{k.name}» {'فعال' if k.active else 'غیرفعال'} شد.")
        elif action == "save_runner":
            mode = post.get("mode", "off")
            if mode not in platform.RUNNER_MODES:
                return messages.error(request, "حالت اجرا نامعتبر است.")
            try:
                url, cb = _clean_url(post.get("url")), _clean_url(post.get("callback"))
                timeout = int(post.get("timeout") or 10)
                if not 2 <= timeout <= 60:
                    raise ValueError("مهلت بین ۲ تا ۶۰ ثانیه باشد.")
            except ValueError as exc:
                return messages.error(request, str(exc))
            for k, v in (("runner_mode", mode), ("runner_url", url), ("runner_callback", cb), ("runner_timeout", str(timeout))):
                platform.set_(k, v)
            log.warning("runner config changed by user %s: mode=%s", request.user.pk, mode)
            messages.success(request, "تنظیم اجرای کد ذخیره شد.")
        elif action == "save_publish":
            on = post.get("require_second_approval") == "1"
            platform.set_("require_second_approval", "1" if on else "")
            log.warning("second approval for wizard publish %s by user %s", "on" if on else "off", request.user.pk)
            messages.success(request, "تأیید مدیر دیگر برای انتشار ویزارد " + ("روشن شد." if on else "خاموش شد."))
        elif action == "save_sources":
            on = post.get("sources_enabled") == "1"
            platform.set_("sources_enabled", "1" if on else "")
            log.warning("external sources %s by user %s", "on" if on else "off", request.user.pk)
            messages.success(request, "واکشی از منابع بیرونی " + ("روشن شد." if on else "خاموش شد."))
        elif action == "test_runner":
            ok, detail = platform.runner_health()
            (messages.success if ok else messages.error)(request, detail)


def _env_key_names() -> set[str]:
    try:
        return set(pkg.parse_keys(getattr(settings, "PLUGIN_PUBLISHER_KEYS", "")))
    except pkg.PackageError:
        return set()


class NotifyChannelForm(forms.ModelForm):
    key = forms.ChoiceField(label="کانال", choices=[(k, v["label"]) for k, v in notify.CHANNELS.items()])
    new_token = forms.CharField(label="توکن ربات", required=False, widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "dir": "ltr"}),
                                help_text="رمزنگاری می‌شود و دیگر نمایش داده نمی‌شود. خالی = بدون تغییر.")

    class Meta:
        model = NotifyChannel
        fields = ("key", "enabled", "bot_username", "api_base")

    def clean_api_base(self):
        try:
            return notify.clean_base(self.cleaned_data.get("api_base", ""))
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from None


@admin.register(NotifyChannel)
class NotifyChannelAdmin(admin.ModelAdmin):
    """کانال‌های هشدار (بله/تلگرام). تلگرام فیلتر است: نشانی رله‌ی سرور خارجی را در «نشانی پایه‌ی API» بگذارید."""

    form = NotifyChannelForm
    list_display = ("key", "enabled", "bot_username", "token_set", "api_base", "last_ok", "last_error")
    actions = ["test_connection"]

    @admin.display(boolean=True, description="توکن")
    def token_set(self, obj):
        return bool(obj.token_enc)

    def has_module_permission(self, request):
        return request.user.is_superuser or request.user.has_perm("kernel.change_notifychannel")

    def has_delete_permission(self, request, obj=None):
        return False

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST" and not stepup.ok(request):
            return redirect(stepup.url(request))
        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        import logging

        ch = notify.save_channel(form.cleaned_data["key"], enabled=form.cleaned_data["enabled"],
                                 token=form.cleaned_data.get("new_token", ""), bot_username=form.cleaned_data["bot_username"],
                                 api_base=form.cleaned_data["api_base"])
        obj.pk = ch.pk
        logging.getLogger(__name__).warning("notify channel %s changed by user %s", ch.key, request.user.pk)
        if form.cleaned_data["enabled"] and not ch.enabled:
            messages.warning(request, "بدون توکن نمی‌شود فعال کرد.")

    @admin.action(description="آزمون اتصال")
    def test_connection(self, request, queryset):
        for ch in queryset:
            ok, detail = notify.test_channel(ch.key)
            (messages.success if ok else messages.error)(request, f"{ch.key}: {detail}")


class SourceHostForm(forms.ModelForm):
    class Meta:
        model = SourceHost
        fields = ("host", "note")

    def clean_host(self):
        h = self.cleaned_data["host"].strip().lower()
        if not pagekit.valid_host(h):
            raise forms.ValidationError("نام دامنه‌ی معتبر بدهید (بدون https، مسیر، IP یا wildcard).")
        return h


@admin.register(SourceHost)
class SourceHostAdmin(admin.ModelAdmin):
    """میزبان‌های بیرونی که پلاگین‌ها مجازند از آن‌ها داده بگیرند (فهرست سفید دقیق). نمونه: api.open-meteo.com.
    سوئیچ کلی «منابع بیرونی» در صفحه‌ی «سکو» است. افزودن میزبان یعنی اعتماد به آن سرویس؛ فقط سرویس‌های شناخته‌شده را بیفزایید."""

    form = SourceHostForm
    list_display = ("host", "note", "added_by", "created_at")
    search_fields = ("host", "note")

    def has_module_permission(self, request):
        return request.user.is_superuser or request.user.has_perm("kernel.change_sourcehost")

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST" and not stepup.ok(request):
            return redirect(stepup.url(request))
        return super().changeform_view(request, object_id, form_url, extra_context)

    def delete_view(self, request, object_id, extra_context=None):
        if request.method == "POST" and not stepup.ok(request):
            return redirect(stepup.url(request))
        return super().delete_view(request, object_id, extra_context)

    def save_model(self, request, obj, form, change):
        import logging

        if not change:
            obj.added_by = request.user
        super().save_model(request, obj, form, change)
        logging.getLogger(__name__).warning("source host %s %s by user %s", obj.host, "changed" if change else "added", request.user.pk)


@admin.register(SourceState)
class SourceStateAdmin(admin.ModelAdmin):
    """وضعیت منابع بیرونی هر پایگاه (فقط‌خواندنی؛ کلید API نمایش داده نمی‌شود)."""

    list_display = ("plugin_id", "page", "key", "workspace_id", "enabled", "last_ok", "last_rows", "fails", "last_error")
    list_filter = ("enabled", "plugin_id")
    exclude = ("secret_enc", "inputs")
    readonly_fields = [f.name for f in SourceState._meta.fields if f.name not in ("secret_enc", "inputs")]

    def has_add_permission(self, request):
        return False

    def has_module_permission(self, request):
        return request.user.is_superuser or request.user.has_perm("kernel.view_sourcestate")
