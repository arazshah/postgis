from django.conf import settings
from django.db import models


class DeviceProfile(models.Model):
    """وضعیت ورود هر حساب روی دستگاه: تا رمز پیش‌فرض/موقت عوض نشده، فقط صفحه‌ی تغییر رمز باز است."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="device_profile")
    must_change_password = models.BooleanField("باید رمز را عوض کند", default=True, db_index=True)
    password_changed_at = models.DateTimeField("آخرین تغییر رمز", null=True, blank=True)

    class Meta:
        verbose_name = "وضعیت ورود دستگاه"
        verbose_name_plural = "وضعیت ورود دستگاه"

    def __str__(self):
        return f"{self.user_id}:{'must' if self.must_change_password else 'ok'}"
