"""صدور و ارسال رمز یک‌بار مصرف با محدودیت نرخ."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

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


def seconds_until_resend(phone: str) -> int:
    last = OTPCode.objects.filter(phone=phone).order_by("-created_at").first()
    if not last:
        return 0
    elapsed = (timezone.now() - last.created_at).total_seconds()
    return max(int(settings.OTP_RESEND_SECONDS - elapsed), 0)


def request_code(phone: str, ip: str | None) -> OTPResult:
    wait = seconds_until_resend(phone)
    if wait:
        return OTPResult(False, f"برای ارسال دوباره {wait} ثانیه صبر کنید.", wait)

    hour_ago = timezone.now() - timedelta(hours=1)
    if OTPCode.objects.filter(phone=phone, created_at__gte=hour_ago).count() >= settings.OTP_MAX_PER_PHONE_HOUR:
        return OTPResult(False, "تعداد درخواست کد برای این شماره زیاد بوده است. یک ساعت دیگر تلاش کنید.")
    if ip and OTPCode.objects.filter(ip=ip, created_at__gte=hour_ago).count() >= settings.OTP_MAX_PER_IP_HOUR:
        return OTPResult(False, "تعداد درخواست‌ها از این اینترنت زیاد بوده است. کمی بعد تلاش کنید.")

    otp, code = OTPCode.issue(phone, ip)
    try:
        send_otp(phone, code)
    except SMSError:
        log.exception("OTP send failed for %s", phone)
        otp.sent_ok = False
        otp.save(update_fields=["sent_ok"])
        return OTPResult(False, "ارسال پیامک ممکن نشد. چند دقیقه دیگر دوباره تلاش کنید.")
    return OTPResult(True, "کد تأیید پیامک شد.", settings.OTP_RESEND_SECONDS,
                     debug_code=code if settings.OTP_SHOW_IN_DEBUG else None)


def verify_code(phone: str, code: str) -> tuple[bool, str]:
    otp = OTPCode.objects.filter(phone=phone, used_at__isnull=True, sent_ok=True).order_by("-created_at").first()
    if otp is None or otp.expires_at <= timezone.now():
        return False, "کد منقضی شده است. کد جدید بگیرید."
    if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        return False, "تعداد تلاش‌ها بیش از حد مجاز بود. کد جدید بگیرید."
    if otp.check_code(code):
        return True, ""
    left = settings.OTP_MAX_ATTEMPTS - otp.attempts
    if left <= 0:
        return False, "کد اشتباه بود و این کد باطل شد. کد جدید بگیرید."
    return False, f"کد اشتباه است. {left} بار دیگر می‌توانید تلاش کنید."
