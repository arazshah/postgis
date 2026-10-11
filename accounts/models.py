import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
MOBILE_RE = re.compile(r"^09\d{9}$")


def normalize_mobile(value: str) -> str:
    """
    ورودی‌های رایج را به قالب استاندارد 09XXXXXXXXX تبدیل می‌کند:
    ۰۹۱۲۳۴۵۶۷۸۹، +989123456789، 00989123456789، 989123456789، 9123456789
    """
    v = re.sub(r"[\s\-()]", "", (value or "").translate(_DIGITS))
    if v.startswith("+98"):
        v = "0" + v[3:]
    elif v.startswith("0098"):
        v = "0" + v[4:]
    elif v.startswith("98") and len(v) == 12:
        v = "0" + v[2:]
    elif v.startswith("9") and len(v) == 10:
        v = "0" + v
    if not MOBILE_RE.match(v):
        raise ValidationError("شماره موبایل معتبر نیست. نمونه درست: 09121234567")
    return v


class UserManager(BaseUserManager):
    """
    دو نوع حساب جدا:
    - کاربر سایت: فقط موبایل، ورود با رمز یک‌بار مصرف، بدون رمز عبور
    - مدیر: نام کاربری و رمز عبور، فقط برای پنل مدیریت
    """

    use_in_migrations = True

    def create_user(self, phone, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        email = extra.pop("email", None)
        user = self.model(phone=normalize_mobile(phone),
                          email=(self.normalize_email(email).lower() if email else None), **extra)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_admin(self, username, password, superuser=True, **extra):
        if not username or not password:
            raise ValueError("نام کاربری و رمز عبور مدیر الزامی است")
        user = self.model(username=username.strip(), is_staff=True, is_superuser=superuser, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra):
        # برای دستور createsuperuser
        extra.pop("is_staff", None)
        extra.pop("is_superuser", None)
        return self.create_admin(username, password, superuser=True, **extra)

    def get_by_natural_key(self, username):
        return self.get(username=username)


class User(AbstractUser):
    """کاربر سایت (موبایل) یا مدیر (نام کاربری/رمز)."""

    username = models.CharField("نام کاربری مدیر", max_length=150, unique=True, null=True, blank=True,
                                help_text="فقط برای حساب‌های مدیریتی. کاربران سایت نام کاربری ندارند.")
    phone = models.CharField("موبایل", max_length=11, unique=True, null=True, blank=True)
    email = models.EmailField("ایمیل", unique=True, null=True, blank=True)
    full_name = models.CharField("نام و نام خانوادگی", max_length=150, blank=True)
    organization = models.CharField("دانشگاه / سازمان", max_length=200, blank=True)
    phone_verified_at = models.DateTimeField("تأیید موبایل", null=True, blank=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(username__isnull=False) | models.Q(phone__isnull=False),
                name="user_has_username_or_phone",
            ),
        ]

    def __str__(self):
        return self.full_name or self.phone or self.username or f"#{self.pk}"

    def save(self, *args, **kwargs):
        for f in ("email", "username", "phone"):
            if getattr(self, f) == "":
                setattr(self, f, None)
        super().save(*args, **kwargs)

    @property
    def is_site_user(self) -> bool:
        return not self.is_staff

    @property
    def display_name(self):
        return self.full_name or self.phone or self.username


def _hash_code(phone: str, code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


class OTPCode(models.Model):
    """رمز یک‌بار مصرف؛ خود کد ذخیره نمی‌شود، فقط HMAC آن."""

    phone = models.CharField("موبایل", max_length=11, db_index=True)
    code_hash = models.CharField(max_length=64)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)
    sent_ok = models.BooleanField(default=True)

    class Meta:
        verbose_name = "رمز یک‌بار مصرف"
        verbose_name_plural = "رمزهای یک‌بار مصرف"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.phone} @ {self.created_at:%Y-%m-%d %H:%M}"

    @classmethod
    def issue(cls, phone: str, ip: str | None, conf) -> tuple["OTPCode", str]:
        length = conf.otp_length
        code = "".join(secrets.choice("0123456789") for _ in range(length))
        # کدهای قبلی این شماره باطل می‌شوند
        cls.objects.filter(phone=phone, used_at__isnull=True).update(used_at=timezone.now())
        otp = cls.objects.create(phone=phone, code_hash=_hash_code(phone, code), ip=ip,
                                 expires_at=timezone.now() + timedelta(seconds=conf.otp_ttl_seconds))
        return otp, code

    def is_usable(self, max_attempts: int) -> bool:
        return (self.used_at is None and self.expires_at > timezone.now()
                and self.attempts < max_attempts and self.sent_ok)

    def check_code(self, code: str, max_attempts: int) -> bool:
        if not self.is_usable(max_attempts):
            return False
        self.attempts += 1
        ok = hmac.compare_digest(self.code_hash, _hash_code(self.phone, code))
        if ok:
            self.used_at = timezone.now()
        self.save(update_fields=["attempts", "used_at"])
        return ok


class SiteUserManager(UserManager):
    def get_queryset(self):
        return super().get_queryset().filter(is_staff=False)


class AdminUserManager(UserManager):
    def get_queryset(self):
        return super().get_queryset().filter(is_staff=True)


class SiteUser(User):
    objects = SiteUserManager()

    class Meta:
        proxy = True
        verbose_name = "کاربر سایت"
        verbose_name_plural = "کاربران سایت"


class AdminUser(User):
    objects = AdminUserManager()

    class Meta:
        proxy = True
        verbose_name = "مدیر"
        verbose_name_plural = "مدیران"
