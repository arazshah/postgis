"""بخش «ماهواره» صفحه‌ی تنظیمات پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html

from kernel import conf, stepup
from satgate import runtime as gate_runtime
from satgate import spec

from . import sources


def _configured() -> bool:
    from . import client

    return client.configured()


def tab_status(obj):
    if _configured():
        return ("ok", "فعال")
    return ("bad", "ناقص") if (obj.satgate_url or obj.satgate_secret_encrypted) else ("warn", "خاموش")


def satgate_status(obj):
    from django.conf import settings

    from .models import SatRequest

    if not _configured():
        return format_html('<b style="color:#b54708">تنظیم نشده — بخش «تصویر ماهواره‌ای» برای کاربران «به‌زودی» نشان داده می‌شود.</b>')
    env = " (از متغیر محیطی)" if not obj.satgate_url and settings.SATGATE_URL else ""
    n = SatRequest.objects.exclude(status=SatRequest.Status.FAILED).count()
    bad = SatRequest.objects.filter(status=SatRequest.Status.FAILED).count()
    return format_html('<b style="color:#1a7f4b">تنظیم شده{}</b> — {} درخواست موفق یا در جریان، {} ناموفق.', env, n, bad)


def satgate_tools(obj):
    return format_html('<a class="button" href="{}">آزمایش اتصال به دروازه</a> '
                       '<span class="help">اول تغییرها را ذخیره کنید؛ آزمون با مقدار ذخیره‌شده انجام می‌شود.</span>',
                       reverse("admin:core_sitesettings_satgatetest"))


def satgate_test_view(request, model_admin):
    from . import probe

    steps = probe.run()
    for ok, text in steps:
        (messages.success if ok else messages.error)(request, text)
    if all(ok for ok, _ in steps):
        messages.success(request, "همه‌ی مراحل موفق بود؛ دروازه آماده‌ی کار است.")


def after_save(request, obj):
    new = getattr(obj, "_new_satgate_secret", "")
    if new:
        messages.warning(request, format_html(
            "کلید تازه‌ی دروازه ساخته شد؛ همین حالا کپی کنید، دوباره نمایش داده نمی‌شود و روی دروازه به‌عنوان "
            "<code>SATGATE_SECRET</code> بگذارید: <code dir=\"ltr\" style=\"user-select:all\">{}</code>", new))


# ---------------------------------------------------------------------- صفحه‌ی «منابع ماهواره»
def sources_link(obj):
    return format_html('<a class="button" href="{}">مدیریت منابع و تأمین‌کننده‌ها</a> '
                       '<span class="help">روشن و خاموش کردن ماهواره‌ها، کلید حساب‌ها، هزینه‌ی هر دریافت از سهمیه‌ی مشترک.</span>',
                       reverse("admin:core_sitesettings_satsources"))


def _live() -> dict:
    """وضعیت ماهواره‌ها از کش دروازه (بدون درخواست تازه؛ برای سنجش واقعی «آزمایش اتصال» را بزنید)."""
    from django.core.cache import cache

    return cache.get("satmissions") or {}


def _provider_cards(v: dict) -> list[dict]:
    cards = []
    for p in spec.PROVIDERS.values():
        st = sources.provider_state(p.key)
        ready = p.ready({n: "x" for n in st["creds"]})
        if not p.implemented:
            status, badge = "گام بعد", "warn"
        elif not st["enabled"]:
            status, badge = "خاموش", "bad"
        elif not ready:
            status, badge = "کلید لازم", "warn"
        else:
            status, badge = "روشن", "ok"
        creds = [{"name": n, "label": label, "secret": secret, "is_set": n in st["creds"],
                  "value": "" if secret else (v.get(f"prov_{p.key}_{n}") or "")} for n, label, secret in p.creds]
        cards.append({"key": p.key, "title": p.title, "hint": p.hint, "enabled": st["enabled"], "status": status, "badge": badge,
                      "url_editable": p.key in sources.URL_PROVIDERS, "url": v.get(f"prov_{p.key}_url") or "",
                      "default_url": p.stac_url, "creds": creds, "signup": p.signup, "implemented": p.implemented,
                      "hosts": "، ".join(p.hosts)})
    return cards


def _mission_rows(v: dict) -> list[dict]:
    live, rows = _live(), []
    groups = dict(spec.GROUPS)
    for m in spec.MISSIONS.values():
        st = live.get(m.key)
        entry = None
        if isinstance(st, dict):
            entry = {"badge": "ok" if st.get("ok") else "bad", "text": "در دسترس" if st.get("ok") else (st.get("error") or "در دسترس نیست")[:60]}
        prefer = v.get(f"m_{m.key}_prefer") or m.primary.provider
        rows.append({"key": m.key, "title": m.title, "agency": m.agency, "group": groups.get(m.group, m.group), "res": m.res_m,
                     "enabled": v.get(f"m_{m.key}_enabled", True), "weight": v.get(f"m_{m.key}_weight") or m.weight,
                     "max_km2": v.get(f"m_{m.key}_max_km2") or 0, "live": entry,
                     "provider": spec.PROVIDERS[m.primary.provider].title,
                     "prefer_choices": [(s.provider, spec.PROVIDERS[s.provider].title, s.provider == prefer) for s in m.sources]
                     if len(m.sources) > 1 else []})
    return rows


def _save(request, v: dict) -> list[str]:
    """مقدارهای فرم را اعتبارسنجی و ذخیره می‌کند؛ فهرست خطاها (خالی = موفق)."""
    errors, post = [], request.POST
    plan: list[tuple[str, object]] = []
    for p in spec.PROVIDERS.values():
        plan.append((f"prov_{p.key}_enabled", f"prov_{p.key}_enabled" in post))
        if p.key in sources.URL_PROVIDERS:
            try:
                plan.append((f"prov_{p.key}_url", gate_runtime.safe_url(post.get(f"prov_{p.key}_url", ""))))
            except gate_runtime.ConfigError as exc:
                errors.append(f"{p.title}: {exc}")
        for name, _label, _secret in p.creds:
            key, val = f"prov_{p.key}_{name}", post.get(f"prov_{p.key}_{name}", "").strip()
            if post.get(f"clear_{p.key}_{name}"):
                conf.clear(sources.PLUGIN, key)
            elif val:
                plan.append((key, val))
    for m in spec.MISSIONS.values():
        plan.append((f"m_{m.key}_enabled", f"m_{m.key}_enabled" in post))
        for opt in ("weight", "max_km2"):
            plan.append((f"m_{m.key}_{opt}", post.get(f"m_{m.key}_{opt}", "")))
        if len(m.sources) > 1:
            plan.append((f"m_{m.key}_prefer", post.get(f"m_{m.key}_prefer", "")))
    for key, raw in plan:
        try:
            conf.set_value(sources.PLUGIN, key, raw)
        except ValueError as exc:
            errors.append(f"{key}: {exc}")
    return errors


def sources_view(request, model_admin):
    changing_secret = request.method == "POST" and any(
        request.POST.get(f"prov_{p.key}_{n}", "").strip() or request.POST.get(f"clear_{p.key}_{n}")
        for p in spec.PROVIDERS.values() for n, _, is_secret in p.creds if is_secret)
    if request.method == "POST":
        if changing_secret and not stepup.ok(request):
            return redirect(stepup.url(request))
        errors = _save(request, {})
        sources.invalidate()
        for e in errors:
            messages.error(request, e)
        if not errors:
            ok, msg = sources.push()
            (messages.success if ok else messages.warning)(request, "تنظیمات ذخیره شد. " + msg)
        return redirect(reverse("admin:core_sitesettings_satsources"))
    v = conf.get_all(sources.PLUGIN)
    return TemplateResponse(request, "admin/satellite/sources.html", {
        **model_admin.admin_site.each_context(request), "title": "منابع ماهواره", "providers": _provider_cards(v),
        "missions": _mission_rows(v), "back": reverse("admin:core_sitesettings_change", args=[1]), "has_view_permission": True})
