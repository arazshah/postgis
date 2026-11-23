"""تأیید ایمیل و بازنشانی رمز با ایمیل. ارسال از `kernel.mail`؛ این ماژول فقط توکن و قاعده می‌سازد.

- پیوند تأیید امضاشده (۴۸ ساعت) و به **ایمیل همان لحظه** بسته است؛ با عوض‌شدن ایمیل بی‌اعتبار می‌شود.
- بازنشانی رمز با `default_token_generator` جنگو: یک‌بار مصرف (با تغییر رمز باطل می‌شود) و ۳ ساعته (PASSWORD_RESET_TIMEOUT).
- پاسخ «فراموشی رمز» هرگز نمی‌گوید این ایمیل ثبت شده یا نه (جلوگیری از شمارش حساب‌ها).
"""
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from kernel import mail

from .models import User

SALT, MAX_AGE = "accounts.email-verify", 48 * 3600
RESEND_SECONDS = 60


def _abs(path: str) -> str:
    return settings.CANONICAL_URL.rstrip("/") + path


def _name(user) -> str:
    return (user.full_name or "").split(" ")[0]


def make_token(user) -> str:
    return signing.dumps({"u": user.pk, "e": (user.email or "").lower()}, salt=SALT)


def send_verification(user, *, force: bool = False, live: bool = False) -> bool:
    """لینک تأیید را می‌فرستد. False اگر ایمیل ندارد/تأییدشده/خیلی زود دوباره خواسته شده."""
    if not user.email or user.email_verified_at:
        return False
    gate = f"emailverify:sent:{user.pk}"
    if not force and cache.get(gate):
        return False
    cache.set(gate, 1, RESEND_SECONDS)
    url = ((settings.LIVE_ORIGIN + reverse("live:auth_email_confirm", args=[make_token(user)]))
           if live else _abs(reverse("accounts:email_confirm", args=[make_token(user)])))
    mail.send("verify_email", user=user, context={"url": url, "name": _name(user)}, urgent=True)
    return True


def confirm(token: str):
    """کاربر را برمی‌گرداند و ایمیلش را تأییدشده می‌کند؛ None اگر توکن بد/منقضی/کهنه است."""
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:
        return None
    user = User.objects.filter(pk=data.get("u"), is_active=True).first()
    if user is None or (user.email or "").lower() != data.get("e"):
        return None
    if not user.email_verified_at:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])
        mail.send("welcome", user=user, key="welcome",
                  context={"name": _name(user), "start_url": _abs(reverse("databases:create"))})
    return user


def send_reset(email: str, *, live: bool = False) -> None:
    """اگر حساب سایت (نه مدیر) با این ایمیل هست، پیوند بازنشانی می‌فرستد؛ در غیر این صورت هیچ."""
    user = User.objects.filter(email__iexact=email.strip(), is_active=True, is_staff=False).first()
    if user is None or not user.email:
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    args = [uid, default_token_generator.make_token(user)]
    url = ((settings.LIVE_ORIGIN + reverse("live:auth_password_reset", args=args))
           if live else _abs(reverse("accounts:password_reset", args=args)))
    mail.send("password_reset", user=user, context={"url": url, "name": _name(user)}, urgent=True)


def user_from_uid(uidb64: str, token: str):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)), is_active=True, is_staff=False)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        return None
    return user if default_token_generator.check_token(user, token) else None


def password_changed(user) -> None:
    if user.email:
        mail.send("password_changed", user=user, context={})


def email_changed(old: str | None, user) -> None:
    """ایمیل تازه تأیید می‌خواهد؛ به نشانی قبلی هم خبر امنیتی می‌رود."""
    user.email_verified_at = None
    user.save(update_fields=["email_verified_at"])
    if user.email:
        send_verification(user, force=True)
    if old:
        mail.send("email_changed", user=None, to=old, context={"new_email": user.email or "—"}, urgent=True)
