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
class DraftMetaForm(forms.ModelForm):
    class Meta:
        model = PluginDraft
        fields = ("plugin_id", "name", "version", "kind", "requires", "readme")
        widgets = {"kind": forms.Select(choices=[("custom", "اختصاصی"), ("feature", "قابلیت")]),
                   "readme": forms.Textarea(attrs={"rows": 3})}


@admin.register(PluginDraft)
class PluginDraftAdmin(admin.ModelAdmin):
    """استودیو: ویرایش پیش‌نویس، بررسی زنده، پیش‌نمایش روی یک پایگاه داده و خروجی بدون امضا برای plugin_pack."""

    list_display = ("plugin_id", "name", "version", "page_count", "updated_by", "updated_at")
    search_fields = ("plugin_id", "name")
    change_form_template = "admin/kernel/plugindraft/studio_redirect.html"

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
        from . import wizard_admin

        return [path("wizard/", wrap(wizard_admin.view), name="kernel_plugindraft_wizard_new"),
                path("<int:pk>/wizard/<int:step>/", wrap(wizard_admin.view), name="kernel_plugindraft_wizard"),
                path("studio/new/", wrap(self.studio_view), name="kernel_plugindraft_new"),
                path("<int:pk>/studio/", wrap(self.studio_view), name="kernel_plugindraft_studio"),
                path("<int:pk>/export/", wrap(self.export_view), name="kernel_plugindraft_export"),
                *super().get_urls()]

    def add_view(self, request, form_url="", extra_context=None):
        from django.urls import reverse

        return redirect(reverse("admin:kernel_plugindraft_new"))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        from django.urls import reverse

        return redirect(reverse("admin:kernel_plugindraft_studio", args=[object_id]))

    def export_view(self, request, pk):
        from django.http import HttpResponse
        from django.shortcuts import get_object_or_404

        if not self._allowed(request):
            raise PermissionDenied
        d = get_object_or_404(PluginDraft, pk=pk)
        steps = studio.check(d)
        if not studio.ok(steps):
            messages.error(request, "پیش‌نویس هنوز بررسی را نمی‌گذراند؛ خروجی ساخته نمی‌شود.")
            return redirect("admin:kernel_plugindraft_studio", pk=d.pk)
        r = HttpResponse(studio.export_zip(d), content_type="application/zip")
        r["Content-Disposition"] = f'attachment; filename="{d.plugin_id}-{d.version}-draft.zip"'
        return r

    def studio_view(self, request, pk=None):

        from django.shortcuts import get_object_or_404
        from django.template.response import TemplateResponse
        from django.urls import reverse

        if not self._allowed(request):
            raise PermissionDenied
        draft = get_object_or_404(PluginDraft, pk=pk) if pk else None
        meta = DraftMetaForm(request.POST if request.method == "POST" else None, instance=draft)
        steps, preview_html, texts = [], "", dict(draft.pages) if draft else {}
        codes, alert_mins, trial_out, trial_name = (dict(draft.code) if draft else {}), (dict(draft.alerts) if draft else {}), None, ""
        tests, tests_out = (dict(draft.tests) if draft else {}), None
        if request.method == "POST":
            op = request.POST.get("op", "save")
            texts = {k[5:]: v for k, v in request.POST.items() if k.startswith("page_") and pagekit_key(k[5:])}
            codes = {k[5:]: v for k, v in request.POST.items() if k.startswith("code_") and pagekit_key(k[5:])}
            tests = {k[5:]: v for k, v in request.POST.items() if k.startswith("test_") and pagekit_key(k[5:])}
            alert_mins = {}
            for k, v in request.POST.items():
                if k.startswith("alert_") and pagekit_key(k[6:]) and v.strip().isdigit():
                    alert_mins[k[6:]] = int(v.strip())
            if op == "addpage":
                key = request.POST.get("newkey", "").strip()
                tpl = studio.TEMPLATES.get(request.POST.get("template", "monitor"), studio.TEMPLATES["monitor"])[0]
                if not pagekit_key(key) or key in texts:
                    messages.error(request, "کلید صفحه نامعتبر یا تکراری است (حروف کوچک لاتین، رقم و _).")
                else:
                    texts[key] = tpl.format(key=key)
            if op == "addhandler":
                name = request.POST.get("newhandler", "").strip()
                tpl = studio.HANDLER_TEMPLATES.get(request.POST.get("htemplate", "block"), studio.HANDLER_TEMPLATES["block"])[0]
                if not pagekit_key(name) or name in codes:
                    messages.error(request, "نام handler نامعتبر یا تکراری است (حروف کوچک لاتین، رقم و _؛ دست‌کم ۲ نویسه).")
                else:
                    codes[name] = tpl
                    tests[name] = studio.HANDLER_TESTS.get(request.POST.get("htemplate", "block"), studio.HANDLER_TESTS["block"])
            if op.startswith("delpage:"):
                texts.pop(op.split(":", 1)[1], None)
            if op.startswith("delhandler:"):
                gone = op.split(":", 1)[1]
                codes.pop(gone, None)
                alert_mins.pop(gone, None)
                tests.pop(gone, None)
            if meta.is_valid():
                d = meta.save(commit=False)
                d.pages, d.code, d.alerts, d.updated_by = texts, codes, {k: v for k, v in alert_mins.items() if k in codes}, request.user
                d.tests = {k: v for k, v in tests.items() if k in codes}
                if draft is None and PluginDraft.objects.filter(plugin_id=d.plugin_id).exists():
                    messages.error(request, "پیش‌نویسی با این شناسه هست.")
                else:
                    d.save()
                    draft = d
                    if op in ("save", "addpage", "addhandler") or op.startswith(("delpage:", "delhandler:")):
                        messages.success(request, "پیش‌نویس ذخیره شد.")
                        return redirect(reverse("admin:kernel_plugindraft_studio", args=[d.pk]))
                    steps = studio.check(d)
                    if op == "preview":
                        if not stepup.ok(request):
                            return redirect(stepup.url(request))
                        preview_html = self._preview(request, d)
                    if op == "runtests":
                        if not stepup.ok(request):
                            return redirect(stepup.url(request))
                        tests_out = studio.run_tests(d)
                    if op.startswith("trial:"):
                        if not stepup.ok(request):
                            return redirect(stepup.url(request))
                        trial_name = op.split(":", 1)[1]
                        trial_out = self._trial(request, d, trial_name)
        if draft and not steps and request.method == "GET":
            steps = studio.check(draft)
        return TemplateResponse(request, "admin/kernel/plugindraft/studio.html", {
            **self.admin_site.each_context(request), "title": "استودیوی پلاگین", "draft": draft, "meta": meta,
            "texts": sorted(texts.items()), "steps": steps, "valid": studio.ok(steps), "preview_html": preview_html,
            "templates": [(k, v[1]) for k, v in studio.TEMPLATES.items()], "opts": self.model._meta,
            "codes": sorted(codes.items()), "alert_mins": alert_mins, "handler_templates": [(k, v[1]) for k, v in studio.HANDLER_TEMPLATES.items()],
            "roles": {k: v[0] for k, v in (studio.roles(draft).items() if draft else [])}, "trial": trial_out, "trial_name": trial_name, "tests": dict(sorted(tests.items())), "tests_out": tests_out,
            "installed": bool(draft and studio.installed(draft.plugin_id))})

    def _trial(self, request, d, name):
        """اجرای آزمایشی یک handler با ورودی نمونه؛ پایگاه داده‌ی اختیاری فقط‌خواندنی و با ثبت فعالیت."""
        import json as _json

        from . import workspace as ws_mod
        from .runner import sandbox

        try:
            params = _json.loads(request.POST.get("trial_params", "").strip() or "{}")
            if not isinstance(params, dict):
                raise ValueError
        except ValueError:
            return {"ok": False, "error": "ورودی نمونه باید یک شیء JSON باشد.", "result": "", "verdict": [], "logs": []}
        up = request.FILES.get("trial_file")
        if up is not None and up.size > sandbox.MAX_FILE:
            return {"ok": False, "error": "فایل نمونه بیش از ۳ مگابایت است.", "result": "", "verdict": [], "logs": []}
        ws = None
        db = request.POST.get("trial_db", "").strip()
        if db:
            ws = ws_mod.peek(int(db)) if db.isdigit() else None
            if ws is None or not getattr(ws, "is_live", False):
                return {"ok": False, "error": "پایگاه داده‌ی فعال با این شناسه نیست.", "result": "", "verdict": [], "logs": []}
        out = studio.trial(d, name, params, up.read(sandbox.MAX_FILE + 1) if up is not None else None, ws)
        if ws is not None:
            ws_mod.log_event("plugin_studio", f"اجرای آزمایشی {d.plugin_id}/{name} روی پایگاه داده {ws.pk}", user=request.user, database=ws)
        return out

    def _preview(self, request, d):
        from django.template.loader import render_to_string

        from . import workspace as ws_mod

        pk = request.POST.get("preview_db", "")
        key = request.POST.get("preview_page", "")
        ws = ws_mod.peek(int(pk)) if pk.isdigit() else None
        if ws is None or not getattr(ws, "is_live", False):
            messages.error(request, "پایگاه داده‌ی فعال با این شناسه نیست.")
            return ""
        try:
            ctx = studio.preview_page(d, key, ws, {})
        except Exception as exc:  # noqa: BLE001 - خطای مشخصات یا اتصال: پیام کوتاه
            messages.error(request, f"پیش‌نمایش ممکن نشد: {str(exc)[:200]}")
            return ""
        ws_mod.log_event("plugin_studio", f"پیش‌نمایش {d.plugin_id}/{key} روی پایگاه داده {ws.pk}", user=request.user, database=ws)
        return render_to_string("kernel/_page_body.html", {**ctx, "SITE": {}}, request=request)


def pagekit_key(k: str) -> bool:
    return bool(pagekit.KEY_RE.fullmatch(k))


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
        mutating = {"add_key", "remove_key", "toggle_key", "save_runner", "save_publish"}
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
            "health_ok": ok, "health": detail, "from_panel": platform._from_panel(), "second_approval": pkg.second_approval_required(), **(extra_context or {})})

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
