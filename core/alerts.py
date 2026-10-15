"""اطلاع‌رسانی به مدیر سایت: پیامک به موبایل پشتیبانی و ایمیل پشتیبانی (هر کدام که تنظیم شده باشد)."""
import logging

from django.core.mail import send_mail

from .models import SiteSettings

log = logging.getLogger(__name__)


def notify_admins(subject: str, text: str, sms: bool = True) -> None:
    from accounts.models import normalize_mobile
    from accounts.sms import send_text

    conf = SiteSettings.get()
    if sms:
        try:
            phone = normalize_mobile(conf.support_phone or "")
        except Exception:  # noqa: BLE001
            phone = ""
        if phone:
            try:
                send_text(phone, f"{conf.site_name}: {subject}\n{text}"[:300])
            except Exception:  # noqa: BLE001
                log.exception("admin sms failed")
    if conf.support_email:
        send_mail(f"[{conf.site_name}] {subject}", text, None, [conf.support_email], fail_silently=True)
    log.warning("ADMIN ALERT %s: %s", subject, text)
