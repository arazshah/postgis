"""کارهای طولانی (بکاپ، بازگردانی، ورود فایل) که سرویس worker جدا از وب‌سایت اجرا می‌کند."""
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone


class Job(models.Model):
    class Kind(models.TextChoices):
        BACKUP = "backup", "بکاپ"
        RESTORE = "restore", "بازگردانی"
        RESTORE_TEST = "restore_test", "آزمون بازگردانی"
        IMPORT = "import", "ورود فایل"
        BASEMAP = "basemap", "ساخت نقشه پایه ایران"
        OSM_REFRESH = "osm_refresh", "به‌روزرسانی داده OSM ایران"
        OSM_IMPORT = "osm_import", "داده آماده ایران"
        ASK = "ask", "پرسش فارسی"

    class Status(models.TextChoices):
        DRAFT = "draft", "منتظر تأیید کاربر"
        QUEUED = "queued", "در صف"
        RUNNING = "running", "در حال اجرا"
        DONE = "done", "انجام شد"
        FAILED = "failed", "ناموفق"
        EXPIRED = "expired", "منقضی (فایل پاک شد)"

    class Trigger(models.TextChoices):
        AUTO = "auto", "خودکار"
        MANUAL = "manual", "دستی"
        SYSTEM = "system", "سیستمی"

    kind = models.CharField("نوع", max_length=20, choices=Kind.choices)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True)
    trigger = models.CharField("شروع‌کننده", max_length=10, choices=Trigger.choices, default=Trigger.MANUAL)
    database = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE, null=True, blank=True,
                                 related_name="jobs", verbose_name="پایگاه داده")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="+", verbose_name="درخواست‌دهنده")
    source = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name="بکاپ مبنا")
    params = models.JSONField(default=dict, blank=True)
    file = models.CharField("فایل", max_length=300, blank=True)
    size_bytes = models.BigIntegerField("حجم فایل", default=0)
    message = models.TextField("پیام", blank=True)
    created_at = models.DateTimeField("ثبت", default=timezone.now, db_index=True)
    started_at = models.DateTimeField("شروع", null=True, blank=True)
    finished_at = models.DateTimeField("پایان", null=True, blank=True)
    expires_at = models.DateTimeField("انقضای فایل", null=True, blank=True)
    alerted = models.BooleanField(default=False, editable=False)

    class Meta:
        verbose_name = "کار پس‌زمینه"
        verbose_name_plural = "کارهای پس‌زمینه و بکاپ‌ها"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["kind", "status", "database"])]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk}"

    @property
    def path(self) -> Path | None:
        return Path(settings.BACKUP_ROOT) / self.file if self.file else None

    @property
    def downloadable(self) -> bool:
        return self.kind == self.Kind.BACKUP and self.status == self.Status.DONE and bool(self.file)

    @property
    def active(self) -> bool:
        return self.status in (self.Status.QUEUED, self.Status.RUNNING)
