"""انتشار پلاگین از ویزارد (docs/adr/0008، مرحله‌ی ۵): پیش‌نویس ← بسته‌ی مهرشده‌ی «panel» ← بررسی ← فعال‌سازی ← دسترسی و قیمت.

- بدون امضای بیرونی: ورود دومرحله‌ی تازه (در نمای پنل)، همان بررسی کامل بسته، ثبت نسخه و گزارش. «تأیید نفر دوم» تنظیم اختیاری پنل است؛
  وقتی روشن باشد نسخه «منتظر تأیید» می‌ماند و مدیر دیگر از «پیشرفته ← نسخه‌ها» فعالش می‌کند (دسترسی هنگام فعال‌شدن اعمال می‌شود).
- نسخه‌ی تازه همیشه از آخرین نسخه‌ی موجود بالاتر است (وصله‌ی خودکار)؛ نسخه‌ی قبلی برای بازگشت می‌ماند.
- دسترسی: عمومی رایگان (باز)، عمومی پولی (محدود + آگهی در فروشگاه با kernel.market)، اختصاصی (محدود + مجوز برای هدف‌های مشخص).
"""
from __future__ import annotations

import logging

from django.db import transaction

from . import entitlements, market, pkg, studio, wizard, wizard_code
from .models import PluginRelease, PluginState
from .plugins import registry

log = logging.getLogger(__name__)
MODES = ("public_free", "public_paid", "private")
TARGET_KINDS = ("org", "user", "workspace", "plan")
LIMIT_KEYS = ("page_views_per_month", "ingest_rows_per_month", "form_submits_per_month")


class PublishError(Exception):
    """پیام فارسی (یا چند پیام) برای مدیر."""


def normalize_access(a: dict) -> dict:
    """دسترسی و قیمت را اعتبارسنجی و استاندارد می‌کند؛ PublishError با پیام فارسی."""
    mode = (a or {}).get("mode")
    if mode not in MODES:
        raise PublishError("نوع دسترسی را انتخاب کنید: عمومی رایگان، عمومی پولی یا اختصاصی.")
    out: dict = {"mode": mode}
    if mode == "public_paid":
        try:
            lst = market.Listing(title="x", price_toman=int(a.get("price_toman") or 0), duration_days=int(a["duration_days"] if a.get("duration_days") not in (None, "") else 30),
                                 scope=a.get("scope") or "workspace", trial_days=int(a.get("trial_days") or 0), limits=a.get("limits") or {})
            lst.validate()
        except (ValueError, TypeError) as exc:
            raise PublishError("قیمت، مدت یا دوره‌ی آزمایشی عدد صحیح باشد.") from exc
        except market.MarketError as exc:
            raise PublishError(str(exc)) from exc
        if lst.price_toman <= 0:
            raise PublishError("قیمت پلاگین پولی باید بیشتر از صفر باشد (یا «عمومی رایگان» را انتخاب کنید).")
        out.update(price_toman=lst.price_toman, duration_days=lst.duration_days, scope=lst.scope, trial_days=lst.trial_days,
                   limits={k: v for k, v in (a.get("limits") or {}).items() if k in LIMIT_KEYS})
    elif mode == "private":
        targets = []
        for t in a.get("targets") or []:
            kind, subject = t.get("kind"), str(t.get("subject", "")).strip()
            if kind not in TARGET_KINDS or not subject:
                raise PublishError("هر هدف نوع و شناسه می‌خواهد.")
            days = t.get("days")
            if days not in (None, "", 0):
                try:
                    days = int(days)
                except (TypeError, ValueError):
                    raise PublishError("مدت هدف (روز) عدد صحیح باشد.") from None
                if not 1 <= days <= 3650:
                    raise PublishError("مدت هدف بین ۱ و ۳۶۵۰ روز باشد.")
            else:
                days = None
            targets.append({"kind": kind, "subject": subject, "days": days})
        if not targets:
            raise PublishError("برای پلاگین اختصاصی دست‌کم یک سازمان، کاربر، پایگاه یا پلن مشخص کنید.")
        out["targets"] = targets
    return out


def check_targets(access: dict) -> list[str]:
    """وجود هدف‌های اختصاصی را می‌سنجد (فقط پیام؛ نبودن مانع انتشار است)."""
    from django.contrib.auth import get_user_model

    from . import workspace
    from .models import Organization

    bad = []
    for t in access.get("targets", []):
        k, v = t["kind"], t["subject"]
        ok = True
        if k == "org":
            ok = v.isdigit() and Organization.objects.filter(pk=int(v)).exists()
        elif k == "user":
            ok = v.isdigit() and get_user_model().objects.filter(pk=int(v)).exists()
        elif k == "workspace":
            ok = v.isdigit() and workspace.peek(int(v)) is not None
        if not ok:
            bad.append(f"{k}:{v}")
    return bad


def next_version(plugin_id: str, wanted: str) -> str:
    """نسخه‌ی بالاتر از همه‌ی نسخه‌های موجود (و حداقل خواسته‌شده)."""
    top = (0, 0, 0)
    for v in PluginRelease.objects.filter(plugin_id=plugin_id).exclude(status=PluginRelease.Status.REJECTED).values_list("version", flat=True):
        try:
            top = max(top, pkg._semver(v))
        except pkg.PackageError:
            continue
    try:
        want = pkg._semver(wanted)
    except pkg.PackageError:
        want = (1, 0, 0)
    if want > top:
        return ".".join(map(str, want))
    return f"{top[0]}.{top[1]}.{top[2] + 1}"


def apply_access(plugin_id: str, access: dict) -> None:
    """دسترسی انتخاب‌شده را روی پلاگین فعال اعمال می‌کند (تکرارپذیر)."""
    mode = access.get("mode")
    st, _ = PluginState.objects.get_or_create(plugin_id=plugin_id)
    st.enabled = True
    st.access = PluginState.Access.OPEN if mode == "public_free" else PluginState.Access.RESTRICTED
    st.save()
    p = registry.plugins.get(plugin_id)
    if mode == "private":
        for t in access.get("targets", []):
            entitlements.grant(plugin_id, t["kind"], t["subject"], source="manual", days=t.get("days"), note="ویزارد")
    if mode == "public_paid":
        lst = access.get("listing") or {}
        market.upsert(plugin_id, market.Listing(
            title=(p.name if p else plugin_id), summary=str(access.get("summary", "")), price_toman=access["price_toman"], duration_days=access["duration_days"],
            scope=access["scope"], trial_days=access["trial_days"], limits=access.get("limits") or {}, is_public=True,
            category=str(lst.get("category") or ""), features=tuple(str(f) for f in lst.get("features") or []), details=str(lst.get("details") or "")))
    else:
        market.remove(plugin_id)
    entitlements.invalidate()


@transaction.atomic
def _create_release(draft, user, access: dict, notes: str = "") -> PluginRelease:
    draft.version = next_version(draft.plugin_id, draft.version)
    draft.save(update_fields=["version", "updated_at"])
    try:
        rel = pkg.submit(studio.sealed_zip(draft), user)
    except pkg.PackageError as exc:
        raise PublishError(str(exc)) from exc
    rel.access = access
    rel.notes = notes[:2000]
    rel.spec = draft.wizard or {}
    rel.save(update_fields=["access", "notes", "spec"])
    return rel


def publish(draft, user, access: dict, notes: str = "") -> dict:
    """انتشار. {release, active, message} یا PublishError. ورود دومرحله‌ی تازه را نمای فراخوان می‌سنجد (stepup)."""
    access = {**normalize_access(access), "summary": str(((draft.wizard or {}).get("intro") or {}).get("summary", ""))[:240],
              "listing": (draft.wizard or {}).get("listing") or {}}
    try:
        wizard_code.validate_code(draft.wizard or {})
        wizard.compile_pages(draft.plugin_id, draft.wizard or {})
    except wizard.WizardError as exc:
        raise PublishError(str(exc)) from exc
    if draft.code:
        from .runner import client

        if client.mode() not in ("local", "remote"):
            raise PublishError("پلاگین دارای کد است و اجرای کد در این استقرار خاموش است؛ حالت «راه‌دور» را در پیشرفته ← کلیدهای ناشر روشن کنید.")
    if not draft.pages:
        raise PublishError("پلاگین دست‌کم یک صفحه‌ی کامل لازم دارد.")
    steps = studio.check(draft)
    if not studio.ok(steps):
        raise PublishError("بررسی بسته موفق نبود: " + "؛ ".join(f"{s['stage']}: {s['detail']}" for s in steps if not s["ok"]))
    rel = _create_release(draft, user, access, notes)
    if rel.status != PluginRelease.Status.CHECKED:
        raise PublishError("بررسی نسخه موفق نبود: " + "؛ ".join(str(r.get("detail", "")) for r in rel.report if not r.get("ok", True)))
    why = pkg.can_approve(rel, user)
    if why:
        return {"release": rel, "active": False, "message": "نسخه ثبت شد و منتظر تأیید مدیر دیگر است (پیشرفته ← نسخه‌ها)."}
    try:
        pkg.activate(rel, user, apply_access=False)
    except pkg.PackageError as exc:
        raise PublishError(str(exc)) from exc
    pkg.sync()  # نام و مانیفست در رجیستری باشد تا آگهی از آن ساخته شود
    try:
        apply_access(draft.plugin_id, access)
    except market.MarketError as exc:
        # نسخه فعال شد (محدود و بدون مجوز) ولی آگهی ساخته نشد؛ مدیر باید ببیند
        log.warning("market listing failed for %s: %s", draft.plugin_id, exc)
        return {"release": rel, "active": True, "message": f"منتشر شد ولی دسترسی/آگهی فروشگاه اعمال نشد: {exc}"}
    return {"release": rel, "active": True, "message": "منتشر و فعال شد."}
