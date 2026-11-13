"""ساخت پلاگین تازه با دستور آماده (docs/adr/0010، مرحله‌ی ۱۱): نام، شناسه، خلاصه، آیکون و یک دستور؛ سپس استودیوی دیداری.

جایگزین گام ۱ ویزارد قدیمی. شناسه بعداً عوض نمی‌شود و پیشوند جدول‌هاست؛ با پیش‌نویس یا پلاگین نصب‌شده‌ی دیگر برخورد نمی‌کند.
"""
from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse

from . import recipes, studio_common, wizard
from .models import PluginDraft
from .plugins import registry


def _check(name: str, pid: str) -> str:
    if not name or len(name) > 120:
        return "نام پلاگین را بنویسید (حداکثر ۱۲۰ نویسه)."
    if not wizard.ID_RE.fullmatch(pid):
        return "شناسه‌ی پلاگین: حروف کوچک لاتین، رقم و _ (۲ تا ۴۱ نویسه، با حرف شروع شود)."
    if PluginDraft.objects.filter(plugin_id=pid).exists() or pid in registry.plugins:
        return "این شناسه از قبل پیش‌نویس یا پلاگین است؛ شناسه‌ی دیگری بدهید."
    return ""


@admin.site.admin_view
def view(request):
    if not studio_common.allowed(request):
        raise PermissionDenied
    ctx = {**admin.site.each_context(request), "title": "پلاگین تازه", "recipes": recipes.RECIPES, "icons": studio_common.ICON_CHOICES,
           "values": {"name": "", "plugin_id": "", "summary": "", "icon": "chart", "recipe": request.GET.get("recipe", "blank")}}
    if request.method == "POST":
        p = request.POST
        name, pid, key = p.get("name", "").strip(), p.get("plugin_id", "").strip(), p.get("recipe", "blank")
        ctx["values"] = {"name": name, "plugin_id": pid, "summary": p.get("summary", "").strip(), "icon": p.get("icon", "chart"), "recipe": key}
        err = _check(name, pid) or ("" if key in recipes.BY_KEY else "دستور آماده نامعتبر است.")
        if err:
            messages.error(request, err)
        else:
            spec = recipes.build(key, pid)
            if ctx["values"]["summary"]:
                spec["intro"]["summary"] = ctx["values"]["summary"][:240]
            if ctx["values"]["icon"] in studio_common.ICON_CHOICES:
                spec["intro"]["icon"] = ctx["values"]["icon"]
            draft = PluginDraft(plugin_id=pid, name=name, version="1.0.0", kind="custom", requires="databases", wizard=spec, updated_by=request.user)
            draft.save()
            err = studio_common.save(draft, spec, request.user)
            from .studio_api import _record

            _record(draft, spec, f"ساخت از «{recipes.BY_KEY[key].title}»", request.user)
            messages.success(request, f"«{name}» ساخته شد." + (f" توجه: {err}" if err else ""))
            return redirect(reverse("admin:kernel_plugindraft_designer", args=[draft.pk]))
    return render(request, "admin/kernel/plugin_new.html", ctx)
