import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def attachment_path(instance, filename):
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "bin").lower()[:5]
    return f"tickets/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext}"


class Ticket(models.Model):
    class Category(models.TextChoices):
        SALES = "sales", "خرید پلن و مالی"
        TECH = "tech", "مشکل فنی و اتصال"
        DATABASE = "database", "پایگاه داده من"
        OTHER = "other", "سایر"

    class Status(models.TextChoices):
        OPEN = "open", "منتظر پاسخ پشتیبانی"
        ANSWERED = "answered", "پاسخ داده شد"
        CLOSED = "closed", "بسته شده"

    number = models.CharField("شماره تیکت", max_length=16, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tickets",
                             verbose_name="کاربر")
    subject = models.CharField("موضوع", max_length=150)
    category = models.CharField("دسته", max_length=12, choices=Category.choices, default=Category.TECH)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.OPEN)
    database = models.ForeignKey("databases.UserDatabase", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="tickets", verbose_name="پایگاه داده مرتبط")
    plan = models.ForeignKey("databases.Plan", on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="tickets", verbose_name="پلن مورد نظر")
    created_at = models.DateTimeField("زمان ثبت", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین فعالیت", default=timezone.now)
    closed_at = models.DateTimeField("زمان بستن", null=True, blank=True)

    class Meta:
        verbose_name = "تیکت"
        verbose_name_plural = "تیکت‌ها"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.number} – {self.subject}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = f"T-{timezone.now():%y%m}-{secrets.token_hex(2).upper()}{secrets.randbelow(10)}"
        super().save(*args, **kwargs)

    @property
    def is_closed(self) -> bool:
        return self.status == self.Status.CLOSED


class TicketMessage(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages", verbose_name="تیکت")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                               related_name="+", verbose_name="نویسنده")
    is_staff = models.BooleanField("پاسخ پشتیبانی", default=False)
    body = models.TextField("متن")
    attachment = models.FileField("پیوست", upload_to=attachment_path, blank=True)
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "پیام"
        verbose_name_plural = "پیام‌ها"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.ticket.number} #{self.pk}"

    @property
    def attachment_name(self) -> str:
        return self.attachment.name.rsplit("/", 1)[-1] if self.attachment else ""
