"""بازگشت کاربران با پیامک (docs/adr/0012): مسیر، دسته‌ی در انتظار تأیید، پیام هر کاربر و ترجیح دریافت."""
import secrets

from django.conf import settings
from django.db import models


def new_code() -> str:
    return secrets.token_urlsafe(6)


class Route(models.Model):
    """تنظیم یک مسیر بازگشت (تعریف مسیر در `winback.routes` است): روشن‌بودن، شناسه‌ی قالب sms.ir و هدیه."""

    class Gift(models.TextChoices):
        NONE = "none", "بدون هدیه"
        TRIAL = "trial", "آزمایش رایگان یک پلاگین"
        EXTEND = "extend", "چند روز تمدید پایگاه"

    key = models.CharField("کلید", max_length=30, unique=True, editable=False)
    enabled = models.BooleanField("روشن", default=False,
                                  help_text="روشن‌بودن یعنی هر شب فهرست پیشنهادی ساخته شود؛ ارسال همیشه بعد از تأیید مدیر است.")
    template_id = models.CharField("شناسه‌ی قالب sms.ir", max_length=12, blank=True,
                                   help_text="متن قالب را از ردیف همین مسیر کپی و در sms.ir بسازید؛ بعد از تأیید، شناسه را اینجا بگذارید.")
    gift_kind = models.CharField("هدیه‌ی بازگشت", max_length=10, choices=Gift.choices, default=Gift.NONE)
    gift_plugin = models.CharField("پلاگین هدیه", max_length=60, blank=True)
    gift_days = models.PositiveSmallIntegerField("روزِ هدیه", default=7)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "مسیر بازگشت"
        verbose_name_plural = "مسیرهای بازگشت"
        ordering = ["key"]

    def __str__(self):
        from .routes import DEFS

        d = DEFS.get(self.key)
        return d.title if d else self.key


class Preference(models.Model):
    """رضایت: پیش‌فرض عضو است (ردیف نداشتن = عضو)؛ لغو با یک ضربه از لینک پیامک یا پروفایل."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="winback_pref")
    marketing = models.BooleanField("پیام‌های پیشنهادی", default=True)
    changed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ترجیح پیام"
        verbose_name_plural = "ترجیح پیام‌ها"


class Batch(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "منتظر تأیید مدیر"
        APPROVED = "approved", "تأییدشده و زمان‌بندی‌شده"
        CANCELLED = "cancelled", "لغوشده"

    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="batches", verbose_name="مسیر")
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField("ساخته‌شده", auto_now_add=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="تأییدکننده")
    approved_at = models.DateTimeField("زمان تأیید", null=True, blank=True)

    class Meta:
        verbose_name = "دسته‌ی ارسال"
        verbose_name_plural = "دسته‌های ارسال (منتظر تأیید)"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.route} — {self.created_at:%Y-%m-%d}"


class Message(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "منتظر تأیید"
        SCHEDULED = "scheduled", "زمان‌بندی‌شده"
        SENT = "sent", "ارسال‌شده"
        FAILED = "failed", "ناموفق"
        SKIPPED = "skipped", "رد شد"
        CONTROL = "control", "گروه کنترل (نمی‌رود)"

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="messages")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="winback_messages")
    route_key = models.CharField(max_length=30, db_index=True)
    phone = models.CharField(max_length=11)
    params = models.JSONField(default=dict)
    dest = models.CharField("مقصد", max_length=200, default="/")
    code = models.CharField(max_length=12, unique=True, default=new_code)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    reason = models.CharField("دلیل رد/خطا", max_length=200, blank=True)
    send_at = models.DateTimeField(null=True, blank=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField("بازگشت", null=True, blank=True)
    paid_toman = models.PositiveIntegerField("پرداخت بعد از پیام", default=0)
    gift_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "پیام بازگشت"
        verbose_name_plural = "پیام‌های بازگشت"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "status", "sent_at"])]

    def __str__(self):
        return f"{self.route_key} → {self.phone}"
