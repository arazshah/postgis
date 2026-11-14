"""دوستت را بیاور: لینک شخصی هر کاربر؛ بعد از ثبت‌نام دوست و ساخت اولین پایگاهش، پاداش به هر دو طرف.

- ما هیچ پیامکی به دوست نمی‌فرستیم (کاربر خودش لینک را در پیام‌رسان می‌گذارد)؛ فقط اعلان تراکنشی پاداش.
- ضد سوءاستفاده: فقط کاربر تازه (حداکثر ۳۰ دقیقه از ساخت حساب)، نه خود معرف، موبایل تأییدشده (ورود با OTP)، پاداش فقط بعد از
  ساخت پایگاه، و سقف پاداش ماهانه‌ی هر معرف.
"""
from __future__ import annotations

import datetime
import logging

from django.conf import settings
from django.db.models import Exists, OuterRef
from django.utils import timezone

from kernel import conf, workspace
from kernel.plugins import registry

from .models import InviteCode, Referral, Route

log = logging.getLogger(__name__)
PLUGIN = "winback"
SESSION_KEY = "winback_ref"
NEW_USER_MINUTES, MAX_AGE_DAYS, PER_TICK = 30, 60, 50


def enabled() -> bool:
    return bool(conf.get(PLUGIN, "ref_enabled"))


def code_for(user) -> InviteCode:
    obj, _ = InviteCode.objects.get_or_create(user=user)
    return obj


def link(code: str) -> str:
    return f"{settings.CANONICAL_URL}/r/invite/{code}/"


def remember(request, code: str) -> bool:
    if InviteCode.objects.filter(code=code).exists():
        request.session[SESSION_KEY] = code
        return True
    return False


def attach(sender=None, request=None, user=None, **_) -> None:
    """سیگنال ورود: اگر کاربر تازه با لینک دعوت آمده، ثبت می‌کند."""
    if request is None or user is None or not hasattr(request, "session"):
        return
    code = request.session.pop(SESSION_KEY, None)
    if not code or not enabled() or user.is_staff:
        return
    if timezone.now() - user.date_joined > datetime.timedelta(minutes=NEW_USER_MINUTES):
        return
    ic = InviteCode.objects.filter(code=code).select_related("user").first()
    if ic is None or ic.user_id == user.pk or not ic.user.is_active or ic.user.is_staff:
        return
    Referral.objects.get_or_create(referred=user, defaults={"referrer": ic.user})


def reward_text() -> str:
    kind, days = conf.get(PLUGIN, "ref_kind"), conf.get(PLUGIN, "ref_days")
    if kind == Route.Gift.COUPON:
        return f"{conf.get(PLUGIN, 'ref_percent')}٪ تخفیف روی خرید بعدی"
    if kind == Route.Gift.EXTEND:
        return f"{days} روز تمدید رایگان پایگاه"
    p = registry.plugins.get(conf.get(PLUGIN, "ref_plugin") or "")
    return f"{days} روز آزمایش رایگان «{p.name}»" if p else ""


def _give(user) -> bool:
    from . import services

    return services.give(conf.get(PLUGIN, "ref_kind"), user, plugin=conf.get(PLUGIN, "ref_plugin") or "",
                         days=int(conf.get(PLUGIN, "ref_days") or 7), percent=int(conf.get(PLUGIN, "ref_percent") or 20))


def _tell(user, text: str) -> None:
    try:
        workspace.notify_user(user, "هدیه‌ی دعوت دوستان", f"{text}\n{settings.CANONICAL_URL}/")
    except Exception:  # noqa: BLE001  اعلان نباید کار دوره‌ای را بشکند
        log.exception("referral notice failed")


def reward_due(now=None) -> int:
    """دعوت‌هایی که دوست پایگاه ساخته؛ پاداش هر دو طرف (یک بار). سقف ماهانه‌ی معرف و پیکربندی ناقص: معلق می‌ماند."""
    from databases.models import UserDatabase

    if not enabled() or not reward_text():
        return 0
    now = now or timezone.now()
    cap = int(conf.get(PLUGIN, "ref_cap") or 10)
    has_db = UserDatabase.objects.filter(owner=OuterRef("referred"), status__in=UserDatabase.LIVE_STATUSES)
    due = (Referral.objects.filter(rewarded_at__isnull=True, created_at__gte=now - datetime.timedelta(days=MAX_AGE_DAYS))
           .filter(Exists(has_db)).select_related("referrer", "referred").order_by("created_at")[:PER_TICK])
    done = 0
    for r in due:
        month = Referral.objects.filter(referrer=r.referrer, rewarded_at__gte=now - datetime.timedelta(days=30)).count()
        if month >= cap or not r.referrer.is_active:
            continue
        got_friend, got_ref = _give(r.referred), _give(r.referrer)
        if not (got_friend or got_ref):
            continue
        r.rewarded_at = now
        r.note = "" if got_friend and got_ref else f"پاداش جزئی: دوست={got_friend}، معرف={got_ref}"
        r.save(update_fields=["rewarded_at", "note"])
        text = f"هدیه‌ی دعوت شما فعال شد: {reward_text()}."
        if got_friend:
            _tell(r.referred, text)
        if got_ref:
            _tell(r.referrer, text)
        done += 1
    return done


def stats(user) -> dict:
    mine = Referral.objects.filter(referrer=user)
    return {"invited": mine.count(), "rewarded": mine.filter(rewarded_at__isnull=False).count()}
