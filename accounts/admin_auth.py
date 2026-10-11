"""فرم ورود پنل مدیریت با قفل موقت پس از تلاش‌های ناموفق."""
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.cache import cache
from django.core.exceptions import ValidationError

from .otp import client_ip

MAX_FAILS = 8
WINDOW = 15 * 60


class LockoutAdminAuthenticationForm(AdminAuthenticationForm):
    error_messages = {
        **AdminAuthenticationForm.error_messages,
        "invalid_login": "نام کاربری یا رمز عبور اشتباه است.",
        "inactive": "این حساب غیرفعال است.",
    }

    def _key(self):
        return f"adminfail:{client_ip(self.request) if self.request else 'na'}"

    def clean(self):
        key = self._key()
        if cache.get(key, 0) >= MAX_FAILS:
            raise ValidationError("به دلیل تلاش‌های ناموفق زیاد، ورود ۱۵ دقیقه قفل شد.", code="locked")
        try:
            cleaned = super().clean()
        except ValidationError:
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, WINDOW)
            raise
        cache.delete(key)
        return cleaned
