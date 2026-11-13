"""صفحه‌ی «ورود به استودیوی دیداری» برای پلاگین‌های قبلی (docs/adr/0010، مرحله‌ی ۹): پیش‌نمایش گزارش راستی‌آزمایی، سپس ساخت یا به‌روزرسانی پیش‌نویس.

- منبع: `?draft=<pk>` (پیش‌نویس استودیوی TOML قدیمی، درجا تبدیل می‌شود) یا `?release=<id>` (نسخه‌ی منتشرشده/نصب‌شده؛ پیش‌نویس تازه‌ای با همان شناسه ساخته می‌شود).
- POST همیشه دوباره از منبع درون‌ریزی می‌کند (نقشه از مرورگر نمی‌آید). اگر گزارش تفاوت یا خطا دارد، تأیید صریح (`confirm`) لازم است.
- چیزی منتشر یا اجرا نمی‌شود؛ انتشار نسخه‌ی تازه همان مسیر معمول استودیو (تأیید تازه، مانع‌های کیفیت) است.
"""
from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse

from . import importer, pkg, wizard_admin
from .models import PluginDraft, PluginRelease, PluginState


def _load(request):
    """(Imported، پیش‌نویس موجود یا None، نوع منبع، منبع)؛ ImportFailed با پیام فارسی."""
    if request.GET.get("draft") or request.POST.get("draft"):
        d = get_object_or_404(PluginDraft, pk=int(request.GET.get("draft") or request.POST.get("draft")))
        return importer.from_draft(d), d, "draft", d
    rel = get_object_or_404(PluginRelease, pk=int(request.GET.get("release") or request.POST.get("release") or 0))
    try:
        imp = importer.from_files(pkg.read_archive(bytes(rel.blob)))
    except pkg.PackageError as exc:
        raise importer.ImportFailed(str(exc)) from exc
    return imp, PluginDraft.objects.filter(plugin_id=rel.plugin_id).first(), "release", rel


def _seed_access(spec: dict, rel: PluginRelease) -> None:
    """دسترسی و آگهی نسخه‌ی منتشرشده (اگر از استودیو بوده) یا وضعیت باز بودن پلاگین نصب‌شده."""
    acc = dict(rel.access or {})
    if acc.get("mode"):
        spec["listing"] = acc.pop("listing", None) or {}
        acc.pop("summary", None)
        spec["access"] = acc
    elif PluginState.objects.filter(plugin_id=rel.plugin_id, enabled=True, access=PluginState.Access.OPEN).exists():
        spec["access"] = {"mode": "public_free"}


def _record(draft, spec, label, user):
    from .studio_api import _record as rec

    rec(draft, spec, label, user)


@admin.site.admin_view
def view(request):
    if not wizard_admin._allowed(request):
        raise PermissionDenied
    ctx = {**admin.site.each_context(request), "title": "ورود به استودیوی دیداری"}
    try:
        imp, draft, kind, src = _load(request)
    except (importer.ImportFailed, ValueError) as exc:
        messages.error(request, str(exc) if isinstance(exc, importer.ImportFailed) else "منبع نامعتبر است.")
        return redirect(reverse("plugin_hub") + "?tab=create")
    designer = reverse("admin:kernel_plugindraft_designer", args=[draft.pk]) if draft else ""
    visual = bool(draft and draft.wizard)
    blocked = ""
    if kind == "release" and draft and not visual:
        blocked = "برای این پلاگین پیش‌نویس TOML هست؛ اول همان را وارد کنید (از «پلاگین‌ها ← ساخت») یا حذفش کنید."
    needs_confirm = bool(imp.report["notes"] or imp.report["errors"])
    if request.method == "POST" and not visual and not blocked:
        if needs_confirm and request.POST.get("confirm") != "1":
            messages.error(request, "گزارش تفاوت یا خطا دارد؛ تأیید «با تفاوت‌ها ادامه بده» لازم است.")
        else:
            d = draft or PluginDraft(plugin_id=imp.plugin_id, name=imp.name, version=imp.version, kind=imp.kind or "custom",
                                     requires=imp.requires or "databases", readme=imp.readme)
            spec = imp.spec
            if kind == "release":
                _seed_access(spec, src)
            if d.pk is None:
                d.wizard = spec
                d.updated_by = request.user
                d.save()
            err = wizard_admin._save(d, spec, request.user)
            _record(d, spec, "ورود از " + ("TOML" if kind == "draft" else f"نسخه‌ی {src.version}"), request.user)
            messages.success(request, f"«{imp.name}» به استودیوی دیداری آمد" + (f" (توجه: {err})" if err else "") + ". نسخه‌ی تازه از همین‌جا منتشر می‌شود.")
            return redirect(reverse("admin:kernel_plugindraft_designer", args=[d.pk]))
    return TemplateResponse(request, "admin/kernel/plugin_import.html", {**ctx, "imp": imp, "report": imp.report, "kind": kind, "source": src, "visual": visual,
                                                                        "designer": designer, "blocked": blocked, "needs_confirm": needs_confirm})
