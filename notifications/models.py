"""اعلان‌های کاربر: پایان یا شکست کارهای پس‌زمینه (تحلیل، ابزار، ورود فایل، بکاپ و…)."""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    class Level(models.TextChoices):
        SUCCESS = "success", "موفق"
        INFO = "info", "اطلاع"
        WARNING = "warning", "هشدار"
        ERROR = "error", "خطا"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    level = models.CharField("سطح", max_length=10, choices=Level.choices, default=Level.INFO)
    title = models.CharField("عنوان", max_length=160)
    body = models.TextField("متن", blank=True)
    detail = models.TextField("جزئیات فنی", blank=True)
    url = models.CharField("پیوند", max_length=300, blank=True)
    action = models.CharField("برچسب دکمه", max_length=40, blank=True)
    database = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE, null=True, blank=True,
                                 related_name="+")
    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "اعلان"
        verbose_name_plural = "اعلان‌ها"
        ordering = ["-id"]
        indexes = [models.Index(fields=["user", "read_at"])]
        constraints = [models.UniqueConstraint(fields=["job"], name="notification_one_per_job",
                                               condition=models.Q(job__isnull=False))]

    def __str__(self):
        return f"{self.title} ({self.user_id})"
