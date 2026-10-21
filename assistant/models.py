import secrets

from django.conf import settings
from django.db import models


def new_token() -> str:
    return secrets.token_hex(10)  # ۲۰ نویسه


class Usage(models.Model):
    """یک پرسش از دستیار؛ فقط شمارنده و ابرداده (متن پرسش و پاسخ ذخیره نمی‌شود).

    برای محدودیت نرخ، گزارش مدیر و بازخورد «مفید بود؟» استفاده می‌شود. جست‌وجوی بی‌پاسخ جدا در
    kb.MissedQuery (بدون هیچ نشانی از کاربر) ثبت می‌شود تا مقاله بعدی را بنویسیم.
    """

    class Status(models.TextChoices):
        OK = "ok", "پاسخ داده شد"
        NO_ANSWER = "no_answer", "پاسخی در منابع نبود"
        ERROR = "error", "خطای سرویس"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="+")
    actor = models.CharField(max_length=40, db_index=True, help_text="u:<id> یا g:<HMAC آی‌پی>")
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.OK)
    mode = models.CharField("روش بازیابی", max_length=10, blank=True)
    path = models.CharField("صفحه", max_length=200, blank=True)
    sources = models.JSONField("مقاله‌های منبع", default=list, blank=True)
    answer_chars = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    helpful = models.BooleanField("مفید بود", null=True, blank=True)
    feedback_token = models.CharField(max_length=24, editable=False, default=new_token)

    class Meta:
        verbose_name = "پرسش از دستیار"
        verbose_name_plural = "پرسش‌های دستیار"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["actor", "created_at"])]

    def __str__(self):
        return f"{self.get_status_display()} — {self.created_at:%Y-%m-%d %H:%M}"
