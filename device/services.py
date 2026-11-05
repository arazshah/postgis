"""منطق حساب‌های دستگاه: ساخت کاربر با رمز، قفل ورود، قواعد مدیر آخر."""
from __future__ import annotations

import re
import secrets

from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import User, normalize_mobile

from .models import DeviceProfile

DEFAULT_ADMIN = "admin"
DEFAULT_PASSWORD = "pgpro"
USERNAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,29}$")
MAX_FAILS = 8
WINDOW = 15 * 60


def normalize_username(value: str) -> str:
    value = (value or "").strip().lower()
    if not USERNAME_RE.match(value):
        raise ValidationError("نام کاربری باید با حرف انگلیسی شروع شود و ۳ تا ۳۰ کاراکتر از حروف کوچک، عدد و _ . - باشد.")
    return value


def temp_password() -> str:
    """رمز موقت خوانا (بدون حروف شبیه هم) برای ساخت حساب یا بازنشانی."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


def check_new_password(raw: str, user: User | None = None):
    if raw.strip().lower() in {DEFAULT_PASSWORD, DEFAULT_ADMIN}:
        raise ValidationError("این رمز پیش‌فرض دستگاه است؛ رمز دیگری انتخاب کنید.")
    validate_password(raw, user)


def create_user(username: str, password: str, *, full_name="", organization="", phone="", admin=False,
                must_change=True) -> User:
    username = normalize_username(username)
    if User.objects.filter(username=username).exists():
        raise ValidationError("این نام کاربری قبلاً استفاده شده است.")
    phone = normalize_mobile(phone) if phone.strip() else None
    if phone and User.objects.filter(phone=phone).exists():
        raise ValidationError("این شماره‌ی موبایل برای حساب دیگری ثبت شده است.")
    user = User(username=username, full_name=full_name.strip(), organization=organization.strip(), phone=phone,
                is_staff=False, is_superuser=admin, analytics_exclude=True)
    user.set_password(password)
    user.save()
    DeviceProfile.objects.create(user=user, must_change_password=must_change)
    return user


def set_password(user: User, raw: str, *, must_change: bool):
    user.set_password(raw)
    user.save(update_fields=["password"])
    DeviceProfile.objects.update_or_create(
        user=user, defaults={"must_change_password": must_change,
                             "password_changed_at": None if must_change else timezone.now()})


def active_admins():
    return User.objects.filter(is_superuser=True, is_active=True)


def is_last_admin(user: User) -> bool:
    return user.is_superuser and user.is_active and not active_admins().exclude(pk=user.pk).exists()


def find_login(identifier: str) -> User | None:
    """نام کاربری یا شماره‌ی موبایل."""
    ident = (identifier or "").strip()
    if not ident:
        return None
    user = User.objects.filter(username=ident.lower()).first()
    if user is None:
        try:
            user = User.objects.filter(phone=normalize_mobile(ident)).first()
        except ValidationError:
            user = None
    return user


# ---- قفل موقت ورود (به‌ازای IP + شناسه) ----
def _key(ip: str | None, ident: str) -> str:
    return f"pgpro-fail:{ip or 'na'}:{(ident or '').strip().lower()[:40]}"


def is_locked(ip, ident) -> bool:
    return cache.get(_key(ip, ident), 0) >= MAX_FAILS


def record_fail(ip, ident):
    key = _key(ip, ident)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, WINDOW)


def clear_fails(ip, ident):
    cache.delete(_key(ip, ident))
