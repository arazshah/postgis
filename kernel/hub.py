"""صفحه‌ی یکپارچه‌ی «پلاگین‌ها» در پنل مدیریت (docs/adr/0008): همه‌ی کارهای پلاگین در یک جا، با چهار زبانه.

- «همه‌ی پلاگین‌ها»: کارت هر پلاگین (نوع، سطح، نسخه، وضعیت، مجوز، سلامت) و منوی کارها.
- «ساخت»: ساخت پلاگین تازه (ویزارد در گام‌های بعدی؛ فعلاً استودیو).
- «مشترک‌ها و فروش»: مجوزهای اخیر و پیوند به افزونه‌های قابل خرید و سازمان‌ها.
- «پیشرفته»: بارگذاری بسته‌ی امضاشده، کلید ناشر و runner، قطع‌های خودکار، مصرف.
فقط خواندن و پیوند است؛ تغییرها همان صفحه‌های مدل‌های قبلی هستند (رفتار عوض نمی‌شود). هسته هیچ اپی را import نمی‌کند: پیوندها با نام مسیر ساخته می‌شوند.
"""
from __future__ import annotations

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, reverse

from . import conf, pkg, stepup
from .models import Entitlement, PluginDraft, PluginRelease, PluginState, PluginTrip
from .plugins import registry

TABS = (("all", "همه‌ی پلاگین‌ها"), ("create", "ساخت"), ("sales", "مشترک‌ها و فروش"), ("advanced", "پیشرفته"))
KIND = {"system": "سیستمی", "feature": "عمومی", "custom": "اختصاصی"}
TIER = {1: "صفحه (بدون کد)", 2: "کد در جعبه", 3: "کد درون‌پردازه"}


def _url(name: str, *args) -> str:
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ""


def allowed(request) -> bool:
    u = request.user
    return bool(u.is_active and u.is_staff and (u.is_superuser or u.has_perm("kernel.view_pluginstate")
                                                 or u.has_perm("kernel.change_pluginstate")))


def cards() -> list[dict]:
    """کارت هر پلاگین نصب‌شده؛ سیستمی‌ها آخر و بدون کار."""
    from .admin import sync_states

    sync_states()
    states = {s.plugin_id: s for s in PluginState.objects.prefetch_related("entitlements")}
    unseen = {}
    for t in PluginTrip.objects.filter(seen_at__isnull=True):
        unseen[t.plugin_id] = unseen.get(t.plugin_id, 0) + 1
    active = dict(PluginRelease.objects.filter(status=PluginRelease.Status.ACTIVE).values_list("plugin_id", "pk"))
    drafts = {d.plugin_id: d for d in PluginDraft.objects.all()}
    out = []
    for p in registry.plugins.values():
        st = states.get(p.id)
        dr = drafts.get(p.id)
        if dr is not None and dr.wizard:
            studio = ("باز کردن در استودیو", _url("admin:kernel_plugindraft_designer", dr.pk))
        elif p.id in active and not (dr is not None and not dr.wizard):
            studio = ("ویرایش در استودیو", _url("admin:kernel_plugindraft_import") + f"?release={active[p.id]}")
        else:
            studio = None
        system = p.kind == "system"
        if p.id in registry.errors:
            health = ("bad", "خطای بارگذاری")
        elif unseen.get(p.id):
            health = ("warn", f"{unseen[p.id]} قطع خودکار دیده‌نشده")
        else:
            health = ("ok", "سالم")
        if system:
            status = ("ok", "همیشه روشن")
        elif st is None:
            status = ("warn", "بدون وضعیت")
        elif not st.enabled:
            status = ("off", "خاموش")
        elif st.access == PluginState.Access.OPEN:
            status = ("ok", "روشن، باز برای همه")
        else:
            status = ("warn", "روشن، محدود به دارندگان مجوز")
        out.append({
            "id": p.id, "name": p.name, "description": p.description, "kind": KIND.get(p.kind, p.kind), "system": system,
            "tier": TIER.get(p.tier, "—") if not system else "", "version": p.version,
            "delivery": "بسته‌ی بارگذاری‌شده" if p.id in pkg._loaded else ("ایمیج" if not system else ""),
            "status": status, "health": health, "grants": len(st.entitlements.all()) if st else 0,
            "edit": _url("admin:kernel_pluginstate_change", st.pk) if st and not system else "",
            "studio": studio if not system else None,
            "options": _url("admin:kernel_pluginstate_options", st.pk) if st and conf.options(p.id) else "",
        })
    out.sort(key=lambda c: (c["system"], c["name"]))
    return out


def recent_grants(limit: int = 40) -> list[Entitlement]:
    return list(Entitlement.objects.select_related("state").order_by("-created_at")[:limit])


def advanced_links() -> list[dict]:
    rows = [
        ("بارگذاری بسته‌ی امضاشده", "فایل .gpkgx از بیرون؛ بررسی خودکار و تأیید نفر دوم.", _url("admin:kernel_pluginrelease_upload")),
        ("نسخه‌ها و بازگشت", "همه‌ی نسخه‌های بسته‌ها؛ فعال‌سازی نسخه‌ی قبلی.", _url("admin:kernel_pluginrelease_changelist")),
        ("کلید ناشر و اجرای کد", "کلید عمومی بسته‌ها و تنظیم runner کد سطح ۲.", _url("admin:kernel_publisherkey_changelist")),
        ("قطع‌های خودکار", "پلاگینی که به‌خاطر خطای پیاپی کنار گذاشته شد.", _url("admin:kernel_plugintrip_changelist")),
        ("مصرف پلاگین‌ها", "شمارنده‌های مصرف و سقف‌ها.", _url("admin:kernel_pluginusage_changelist")),
    ]
    return [{"title": t, "hint": h, "url": u} for t, h, u in rows if u]


def sales_links() -> list[dict]:
    rows = [("افزونه‌های قابل خرید", "قیمت، مدت و دارنده‌ی هر افزونه‌ی فروشی.", _url("admin:billing_pluginaddon_changelist")),
            ("سازمان‌های مشتری", "مجوز به‌نام سازمان.", _url("admin:kernel_organization_changelist"))]
    return [{"title": t, "hint": h, "url": u} for t, h, u in rows if u]


@admin.site.admin_view
def hub(request):
    if not allowed(request):
        raise PermissionDenied
    tab = request.GET.get("tab", "all")
    if tab not in dict(TABS):
        tab = "all"
    ctx = {**admin.site.each_context(request), "title": "پلاگین‌ها", "tab": tab, "tabs": TABS}
    if tab == "all":
        allc = cards()
        ctx["cards"] = [c for c in allc if not c["system"]]
        ctx["system_cards"] = [c for c in allc if c["system"]]
    elif tab == "create":
        ctx["new_url"] = _url("admin:kernel_plugindraft_new")
        ctx["drafts"] = [{"name": d.name, "id": d.plugin_id, "url": _url("admin:kernel_plugindraft_designer", d.pk) if d.wizard else _url("admin:kernel_plugindraft_import") + f"?draft={d.pk}", "wizard": bool(d.wizard)} for d in PluginDraft.objects.all()[:30]]
    elif tab == "sales":
        ctx.update(grants=recent_grants(), links=sales_links())
    else:
        ctx["links"] = advanced_links()
    return TemplateResponse(request, "admin/kernel/hub.html", ctx)


def install_sample(request):
    """ساخت و انتشار پلاگین‌های نمونه‌ی «هواشناسی آنلاین» و «شناسنامه باغات» (docs/plugins/testing-guide.md): فقط POST، تأیید تازه و مجوز فعال‌سازی نسخه."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from . import publish, samples

    if not allowed(request):
        raise PermissionDenied
    if request.method != "POST":
        return redirect("plugin_hub")
    if not request.user.has_perm("kernel.activate_pluginrelease"):
        raise PermissionDenied
    if not stepup.ok(request):
        return redirect(stepup.url(request))
    try:
        for res in samples.install(request.user):
            (messages.success if res["active"] else messages.warning)(request, f"«{res['name']}»: {res['message']}")
        messages.info(request, "حالا با حساب مشتری یک پایگاه PostGIS فعال را باز کنید؛ در ریل کناری پایگاه، زیر «داده»، «هواشناسی آنلاین» و «شناسنامه باغات» پیدا می‌شوند "
                               "(تا ۳۰ ثانیه ممکن است دیر بیایند). در «بازار پلاگین» هم در بخش رایگان هستند.")
    except publish.PublishError as exc:
        messages.error(request, f"ساخت نمونه‌ها انجام نشد: {exc}")
    return redirect(reverse("plugin_hub") + "?tab=create")
