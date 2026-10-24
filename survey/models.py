"""
برداشت میدانی: هر پروژه یک schema جدا (s_<شناسه>) در پایگاه داده مکانی کاربر دارد.

- اینجا (پایگاه داده پنل) فقط فراداده پروژه‌ها و فهرست درایورهای گیرنده نگهداری می‌شود؛
  داده برداشت (نقطه، خط، چندضلعی) در پایگاه داده خود کاربر است.
"""
from django.conf import settings
from django.db import models


class SurveyProject(models.Model):
    database = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE, related_name="survey_projects",
                                 verbose_name="پایگاه داده")
    slug = models.SlugField("نام schema", max_length=11, help_text="s_ و هشت حرف کوچک یا رقم؛ پس از ساخت تغییر نمی‌کند.")
    name = models.CharField("نام پروژه", max_length=120)
    srid = models.PositiveIntegerField("سیستم مختصات (SRID)")
    template = models.CharField("قالب پروژه", max_length=40, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateTimeField("بایگانی‌شده در", null=True, blank=True)

    class Meta:
        verbose_name = "پروژه برداشت میدانی"
        verbose_name_plural = "پروژه‌های برداشت میدانی"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["database", "slug"], name="survey_project_db_slug_uniq"),
        ]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    @property
    def archived(self) -> bool:
        return self.archived_at is not None


class GnssDriver(models.Model):
    class Level(models.TextChoices):
        BUILTIN = "builtin", "داخلی"
        TESTED = "tested", "آزموده‌شده"
        COMPATIBLE = "compatible", "سازگار"
        EXPERIMENTAL = "experimental", "آزمایشی"
        PRIVATE = "private", "خصوصی"

    driver_id = models.SlugField("شناسه درایور", max_length=41)
    version = models.CharField("نسخه", max_length=20)
    api_version = models.PositiveSmallIntegerField("نسخه قرارداد")
    manifest = models.JSONField("مشخصات", default=dict)
    level = models.CharField("سطح", max_length=14, choices=Level.choices, default=Level.BUILTIN)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="+", verbose_name="مالک (درایور خصوصی)")
    enabled = models.BooleanField("فعال", default=True)
    bundle_hash = models.CharField(max_length=64, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "درایور گیرنده GNSS"
        verbose_name_plural = "درایورهای گیرنده GNSS"
        ordering = ["driver_id", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["driver_id", "version"], name="gnss_driver_id_version_uniq"),
        ]

    def __str__(self):
        return f"{self.driver_id} {self.version}"


class NtripProfile(models.Model):
    """اتصال به یک کستر NTRIP برای دریافت تصحیحات RTK. گذرواژه رمز‌شده ذخیره می‌شود و هرگز به مرورگر برنمی‌گردد."""
    project = models.ForeignKey(SurveyProject, on_delete=models.CASCADE, related_name="ntrip_profiles")
    name = models.CharField("نام", max_length=80)
    host = models.CharField("میزبان", max_length=253)
    port = models.PositiveIntegerField("درگاه", default=2101)
    mountpoint = models.CharField("Mountpoint", max_length=40, blank=True)
    username = models.CharField("نام کاربری", max_length=80, blank=True)
    password_enc = models.TextField("گذرواژه (رمز‌شده)", blank=True)
    tls = models.BooleanField("TLS", default=False)
    send_gga = models.BooleanField("ارسال موقعیت (GGA) به کستر", default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "اتصال NTRIP"
        verbose_name_plural = "اتصال‌های NTRIP"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.host})"


class NtripSession(models.Model):
    """وضعیت اشتراکی یک رله؛ در پایگاه داده است چون درخواست‌های بعدی ممکن است به worker دیگری برسند."""
    id = models.UUIDField(primary_key=True)
    profile = models.ForeignKey(NtripProfile, on_delete=models.CASCADE, related_name="sessions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    gga = models.CharField(max_length=120, blank=True)
    gga_seq = models.PositiveIntegerField(default=0)
    closed = models.BooleanField(default=False)
    bytes_out = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "closed"])]
