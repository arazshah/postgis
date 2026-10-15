"""امکانات پلن سازمانی: GeoServer اختصاصی و سرویس رستر (GeoTIFF به کاشی تصویری)."""
import secrets
from pathlib import Path

from django.conf import settings
from django.db import models

from databases.crypto import decrypt, encrypt


def _slug() -> str:
    return secrets.token_hex(4)


class GeoServerInstance(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "درخواست شده"
        PROVISIONING = "provisioning", "در حال ساخت"
        ACTIVE = "active", "فعال"
        FAILED = "failed", "ناموفق"
        STOPPED = "stopped", "متوقف"

    database = models.OneToOneField("databases.UserDatabase", on_delete=models.CASCADE, related_name="geoserver")
    slug = models.SlugField(unique=True, default=_slug)
    status = models.CharField("وضعیت", max_length=12, choices=Status.choices, default=Status.REQUESTED)
    url = models.URLField("آدرس GeoServer", blank=True, help_text="مثلاً https://gs-ab12.postgis.ir/geoserver")
    admin_user = models.CharField("کاربر مدیر", max_length=60, default="admin")
    admin_password_encrypted = models.TextField(blank=True, editable=False)
    memory_mb = models.PositiveIntegerField("حافظه (مگابایت)", default=1536)
    coolify_uuid = models.CharField("شناسه Coolify", max_length=64, blank=True)
    version = models.CharField("نسخه", max_length=30, blank=True)
    message = models.TextField("آخرین پیام", blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "GeoServer اختصاصی"
        verbose_name_plural = "GeoServerهای اختصاصی"

    def __str__(self):
        return f"GeoServer {self.database}"

    def set_password(self, raw: str):
        self.admin_password_encrypted = encrypt(raw)

    def get_password(self) -> str:
        return decrypt(self.admin_password_encrypted)


class Raster(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "در حال پردازش"
        READY = "ready", "آماده"
        FAILED = "failed", "ناموفق"

    COLORMAPS = [("gray", "خاکستری"), ("terrain", "ارتفاع (terrain)"), ("viridis", "viridis"), ("rdylgn", "قرمز تا سبز"),
                 ("blues", "آبی"), ("spectral", "طیفی")]

    database = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE, related_name="rasters")
    slug = models.SlugField(unique=True, default=_slug)
    title = models.CharField("عنوان", max_length=120)
    original_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PROCESSING)
    message = models.TextField(blank=True)
    size_bytes = models.BigIntegerField(default=0)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    bands = models.PositiveSmallIntegerField(default=0)
    dtype = models.CharField(max_length=20, blank=True)
    crs = models.CharField(max_length=60, blank=True)
    bounds = models.JSONField("محدوده WGS84", default=list, blank=True)
    stats = models.JSONField("کمینه و بیشینه هر باند", default=list, blank=True)
    colormap = models.CharField("رنگ‌بندی", max_length=12, choices=COLORMAPS, default="terrain")
    rgb = models.BooleanField("نمایش رنگی (باندهای ۱، ۲، ۳)", default=False)
    is_public = models.BooleanField("عمومی", default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "رستر"
        verbose_name_plural = "رسترها"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def path(self) -> Path:
        return Path(settings.RASTER_ROOT) / str(self.database_id) / f"{self.slug}.tif"
