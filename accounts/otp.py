"""صدور و ارسال رمز یک‌بار مصرف با محدودیت نرخ."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from core.models import SiteSettings

from . import bale
from .models import OTPCode
from .sms import SMSError, send_otp

log = logging.getLogger(__name__)


@dataclass
class OTPResult:
    ok: bool
    message: str = ""
    wait_seconds: int = 0
    debug_code: str | None = None


def client_ip(request) -> str | None:
    """IP واقعی کاربر پشت پراکسی؛ از سمت راست X-Forwarded-For به اندازه پراکسی‌های قابل اعتماد."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    hops = settings.TRUSTED_PROXY_COUNT
    if xff and hops > 0:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.META.get("REMOTE_ADDR")


def seconds_until_resend(phone: str, conf: SiteSettings | None = None, channel: str = "sms") -> int:
    conf = conf or SiteSettings.get()
    last = OTPCode.objects.filter(phone=phone).order_by("-created_at").first()
    if not last:
        return 0
    if channel == "bale" and last.channel != "bale":
        return 0  # «پیامک نرسید، در بله بفرست» بدون انتظار مجاز است؛ تکرار بله دوباره انتظار دارد
    elapsed = (timezone.now() - last.created_at).total_seconds()
    return max(int(conf.otp_resend_seconds - elapsed), 0)


BALE_SENT = "کد تأیید را در پیام‌رسان بله فرستادیم (بازوی «کد تأیید»)."


def _send_bale(otp: OTPCode, phone: str, code: str, conf) -> bool:
    try:
        bale.send_otp(phone, code, conf)
    except bale.BaleError:
        log.exception("Bale OTP send failed for %s", phone)
        return False
    otp.channel = "bale"
    otp.sent_ok = True
    otp.save(update_fields=["channel", "sent_ok"])
    return True


def request_code(phone: str, ip: str | None, channel: str = "sms") -> OTPResult:
    conf = SiteSettings.get()
    if channel == "bale" and not (conf.bale_ready and conf.bale_button):
        return OTPResult(False, "ارسال کد از طریق بله فعال نیست.")
    wait = seconds_until_resend(phone, conf, channel)
    if wait:
        return OTPResult(False, f"برای ارسال دوباره {wait} ثانیه صبر کنید.", wait)

    hour_ago = timezone.now() - timedelta(hours=1)
    if OTPCode.objects.filter(phone=phone, created_at__gte=hour_ago).count() >= conf.otp_max_per_phone_hour:
        return OTPResult(False, "تعداد درخواست کد برای این شماره زیاد بوده است. یک ساعت دیگر تلاش کنید.")
    if ip and OTPCode.objects.filter(ip=ip, created_at__gte=hour_ago).count() >= conf.otp_max_per_ip_hour:
        return OTPResult(False, "تعداد درخواست‌ها از این اینترنت زیاد بوده است. کمی بعد تلاش کنید.")

    otp, code = OTPCode.issue(phone, ip, conf)
    show = settings.DEBUG and conf.sms_backend == "console"
    debug = code if show else None

    if channel == "bale":
        if _send_bale(otp, phone, code, conf):
            return OTPResult(True, BALE_SENT + " اگر بله ندارید، از ارسال دوباره پیامک استفاده کنید.",
                             conf.otp_resend_seconds, debug_code=debug)
        otp.sent_ok = False
        otp.save(update_fields=["sent_ok"])
        return OTPResult(False, "ارسال کد در بله ممکن نشد. دوباره پیامک بگیرید یا کمی بعد تلاش کنید.")

    try:
        send_otp(phone, code)
    except SMSError:
        log.exception("OTP send failed for %s", phone)
        if conf.bale_ready and conf.bale_fallback and _send_bale(otp, phone, code, conf):
            return OTPResult(True, "ارسال پیامک ممکن نشد؛ " + BALE_SENT, conf.otp_resend_seconds, debug_code=debug)
        otp.sent_ok = False
        otp.save(update_fields=["sent_ok"])
        return OTPResult(False, "ارسال پیامک ممکن نشد. چند دقیقه دیگر دوباره تلاش کنید.")
    return OTPResult(True, "کد تأیید پیامک شد.", conf.otp_resend_seconds, debug_code=debug)


def verify_code(phone: str, code: str) -> tuple[bool, str]:
    conf = SiteSettings.get()
    otp = OTPCode.objects.filter(phone=phone, used_at__isnull=True, sent_ok=True).order_by("-created_at").first()
    if otp is None or otp.expires_at <= timezone.now():
        return False, "کد منقضی شده است. کد جدید بگیرید."
    if otp.attempts >= conf.otp_max_attempts:
        return False, "تعداد تلاش‌ها بیش از حد مجاز بود. کد جدید بگیرید."
    if otp.check_code(code, conf.otp_max_attempts):
        return True, ""
    left = conf.otp_max_attempts - otp.attempts
    if left <= 0:
        return False, "کد اشتباه بود و این کد باطل شد. کد جدید بگیرید."
    return False, f"کد اشتباه است. {left} بار دیگر می‌توانید تلاش کنید."
