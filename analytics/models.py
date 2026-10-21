from django.conf import settings
from django.db import models


class Visitor(models.Model):
    """بازدیدکننده (حتی ثبت‌نام‌نکرده) با کوکی gp_vid؛ منبع اولین ورود (first-touch) اینجا می‌ماند."""

    vid = models.CharField("شناسه", max_length=32, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="کاربر", null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="visitors")
    first_seen = models.DateTimeField("اولین بازدید", auto_now_add=True)
    last_seen = models.DateTimeField("آخرین بازدید", auto_now_add=True)
    visits_count = models.PositiveIntegerField("تعداد بازدید", default=0)
    linked_at = models.DateTimeField("زمان اتصال به کاربر", null=True, blank=True)
    # first-touch
    first_source = models.CharField("منبع اولیه", max_length=80, blank=True)
    first_medium = models.CharField("نوع منبع اولیه", max_length=40, blank=True)
    first_campaign = models.CharField("کمپین اولیه", max_length=120, blank=True)
    first_referrer = models.CharField("ارجاع‌دهنده اولیه", max_length=120, blank=True)
    first_landing = models.CharField("صفحه فرود اولیه", max_length=300, blank=True)
    device = models.CharField("دستگاه", max_length=12, blank=True)
    browser = models.CharField("مرورگر", max_length=24, blank=True)
    in_app = models.CharField("مرورگر داخلی برنامه", max_length=24, blank=True)
    language = models.CharField("زبان", max_length=12, blank=True)

    class Meta:
        verbose_name = "بازدیدکننده"
        verbose_name_plural = "بازدیدکننده‌ها"
        indexes = [models.Index(fields=["first_seen"]), models.Index(fields=["first_source", "first_medium"])]

    def __str__(self):
        return self.vid[:8]


class Visit(models.Model):
    """یک نشست (۳۰ دقیقه بدون فعالیت یا ورود تازه از کمپین/سایت دیگر = نشست جدید)."""

    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name="visits")
    started_at = models.DateTimeField("شروع", auto_now_add=True)
    last_seen = models.DateTimeField("آخرین فعالیت", auto_now_add=True)
    source = models.CharField("منبع", max_length=80, blank=True)
    medium = models.CharField("نوع", max_length=40, blank=True)
    campaign = models.CharField("کمپین", max_length=120, blank=True)
    content = models.CharField("محتوا", max_length=120, blank=True)
    term = models.CharField("کلمه", max_length=120, blank=True)
    click_id = models.CharField("شناسه کلیک", max_length=24, blank=True)
    referrer_host = models.CharField("دامنه ارجاع‌دهنده", max_length=120, blank=True)
    referrer_url = models.CharField("نشانی ارجاع‌دهنده", max_length=300, blank=True)
    landing_path = models.CharField("صفحه فرود", max_length=300, blank=True)
    last_path = models.CharField("آخرین صفحه", max_length=300, blank=True)
    pages = models.PositiveIntegerField("صفحه‌های دیده‌شده", default=1)
    device = models.CharField("دستگاه", max_length=12, blank=True)
    browser = models.CharField("مرورگر", max_length=24, blank=True)
    in_app = models.CharField("مرورگر داخلی برنامه", max_length=24, blank=True)
    ip_hash = models.CharField("هش IP", max_length=16, blank=True)

    class Meta:
        verbose_name = "بازدید"
        verbose_name_plural = "بازدیدها"
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["started_at"]), models.Index(fields=["source", "medium", "campaign"])]

    def __str__(self):
        return f"{self.source or 'direct'} / {self.medium or 'none'}"


class Event(models.Model):
    """رویداد قیف (سمت سرور): درخواست کد، تأیید کد، ثبت‌نام، ساخت پایگاه داده ..."""

    OTP_REQUESTED = "otp_requested"
    OTP_SEND_FAILED = "otp_send_failed"
    OTP_WRONG = "otp_wrong"
    OTP_VERIFIED = "otp_verified"
    SIGNUP = "signup"
    LOGIN = "login"
    DB_CREATED = "db_created"

    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name="events")
    visit = models.ForeignKey(Visit, on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    name = models.CharField("رویداد", max_length=40)
    path = models.CharField("مسیر", max_length=300, blank=True)
    meta = models.JSONField("جزئیات", default=dict, blank=True)
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "رویداد"
        verbose_name_plural = "رویدادها"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["name", "created_at"])]

    def __str__(self):
        return self.name


class SourceReport(Visit):
    """فقط برای نمایش گزارش «منابع ورود» در پنل مدیریت."""

    class Meta:
        proxy = True
        verbose_name = "گزارش منابع ورود"
        verbose_name_plural = "گزارش منابع ورود"
