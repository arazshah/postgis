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
    use_in_migrations = True

    def _create_user(self, phone, password, **extra):
        phone = normalize_mobile(phone)
        email = extra.pop("email", None)
        user = self.model(phone=phone, email=(self.normalize_email(email).lower() if email else None), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()  # ورود فقط با رمز یک‌بار مصرف
        user.save(using=self._db)
        return user

    def create_user(self, phone, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(phone, password, **extra)

    def create_superuser(self, phone, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create_user(phone, password, **extra)


class User(AbstractUser):
    """کاربر با ورود از طریق شماره موبایل و رمز یک‌بار مصرف."""

    username = None
    phone = models.CharField("موبایل", max_length=11, unique=True)
    email = models.EmailField("ایمیل", unique=True, null=True, blank=True)
    full_name = models.CharField("نام و نام خانوادگی", max_length=150, blank=True)
    organization = models.CharField("دانشگاه / سازمان", max_length=200, blank=True)
    phone_verified_at = models.DateTimeField("تأیید موبایل", null=True, blank=True)

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"

    def __str__(self):
        return self.full_name or self.phone

    def save(self, *args, **kwargs):
        if self.email == "":
            self.email = None
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.full_name or self.phone


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
    def issue(cls, phone: str, ip: str | None) -> tuple["OTPCode", str]:
        length = settings.OTP_LENGTH
        code = "".join(secrets.choice("0123456789") for _ in range(length))
        # کدهای قبلی این شماره باطل می‌شوند
        cls.objects.filter(phone=phone, used_at__isnull=True).update(used_at=timezone.now())
        otp = cls.objects.create(phone=phone, code_hash=_hash_code(phone, code), ip=ip,
                                 expires_at=timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS))
        return otp, code

    @property
    def is_usable(self) -> bool:
        return (self.used_at is None and self.expires_at > timezone.now()
                and self.attempts < settings.OTP_MAX_ATTEMPTS and self.sent_ok)

    def check_code(self, code: str) -> bool:
        if not self.is_usable:
            return False
        self.attempts += 1
        ok = hmac.compare_digest(self.code_hash, _hash_code(self.phone, code))
        if ok:
            self.used_at = timezone.now()
        self.save(update_fields=["attempts", "used_at"])
        return ok
